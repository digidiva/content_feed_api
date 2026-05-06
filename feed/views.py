import logging

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import filters, generics, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Comment, Content, Reaction
from .pagination import CommentCursorPagination, ContentCursorPagination
from .serializers import (
    CommentCreateSerializer,
    CommentListSerializer,
    ContentDetailSerializer,
    ContentListSerializer,
    ReactionSerializer,
    ReactionUndoSerializer,
)

logger = logging.getLogger(__name__)


def _update_reaction_counters(content_id, *, add=None, remove=None):
    """Apply F()-based like/dislike counter deltas atomically in a single UPDATE."""
    like_delta = dislike_delta = 0
    if add == Reaction.LIKE:
        like_delta += 1
    elif add == Reaction.DISLIKE:
        dislike_delta += 1
    if remove == Reaction.LIKE:
        like_delta -= 1
    elif remove == Reaction.DISLIKE:
        dislike_delta -= 1

    updates = {}
    if like_delta:
        updates['like_count'] = F('like_count') + like_delta
    if dislike_delta:
        updates['dislike_count'] = F('dislike_count') + dislike_delta
    if updates:
        Content.objects.filter(pk=content_id).update(**updates)


class LoggedExceptionMixin:
    def handle_exception(self, exc):
        if isinstance(exc, ValidationError):
            logger.warning(
                'Validation failure in content API',
                extra={
                    'view': self.__class__.__name__,
                    'errors': getattr(exc, 'detail', str(exc)),
                    'path': getattr(self.request, 'path', None),
                },
            )
            return super().handle_exception(exc)

        if isinstance(exc, (Http404, DjangoPermissionDenied)):
            return super().handle_exception(exc)

        logger.error(
            'Unexpected error in content API',
            extra={
                'view': self.__class__.__name__,
                'path': getattr(self.request, 'path', None),
            },
            exc_info=True,
        )
        return Response(
            {'detail': 'Unexpected error while processing the content API request.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ContentViewSet(LoggedExceptionMixin, viewsets.ModelViewSet):
    queryset = Content.objects.none()  # overridden by get_queryset; required for router basename inference
    pagination_class = ContentCursorPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ['title']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ContentDetailSerializer
        return ContentListSerializer

    def get_queryset(self):
        queryset = Content.objects.select_related('creator')

        creator_id = self.request.query_params.get('creator_id')
        is_active = self.request.query_params.get('is_active')
        if creator_id is not None:
            if not creator_id.isdigit() or int(creator_id) < 1:
                raise ValidationError({'creator_id': 'creator_id must be a positive integer.'})
            queryset = queryset.filter(creator_id=creator_id)
        if is_active is not None:
            active_filters = {'true': True, '1': True, 'yes': True, 'false': False, '0': False, 'no': False}
            normalized_is_active = is_active.lower()
            if normalized_is_active not in active_filters:
                raise ValidationError({'is_active': 'is_active must be one of true, false, 1, 0, yes, or no.'})
            queryset = queryset.filter(is_active=active_filters[normalized_is_active])

        if self.action == 'retrieve':
            queryset = queryset.prefetch_related(
                Prefetch(
                    'comments',
                    queryset=Comment.objects.select_related('user').order_by('created_at'),
                )
            )

        return queryset

    def retrieve(self, request, *args, **kwargs):
        cache_key = f"content_detail:{kwargs['pk']}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        instance = self.get_object()
        data = self.get_serializer(instance).data
        cache.set(cache_key, data, timeout=settings.CONTENT_DETAIL_CACHE_TTL)
        return Response(data)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        cache.delete(f"content_detail:{kwargs['pk']}")
        return response

    def partial_update(self, request, *args, **kwargs):
        response = super().partial_update(request, *args, **kwargs)
        cache.delete(f"content_detail:{kwargs['pk']}")
        return response

    def destroy(self, request, *args, **kwargs):
        response = super().destroy(request, *args, **kwargs)
        cache.delete(f"content_detail:{kwargs['pk']}")
        return response


class ReactionCreateUpdateView(LoggedExceptionMixin, APIView):
    def post(self, request, *args, **kwargs):
        serializer = ReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        content = serializer.validated_data['content']
        reaction_value = serializer.validated_data['reaction']

        try:
            with transaction.atomic():
                existing = (
                    Reaction.objects
                    .select_for_update()
                    .filter(user=user, content=content)
                    .first()
                )
                if existing is None:
                    reaction_obj = Reaction.objects.create(
                        user=user, content=content,
                        reaction=reaction_value, is_active=True,
                    )
                    created = True
                    _update_reaction_counters(content.id, add=reaction_value)
                else:
                    old_reaction, old_is_active = existing.reaction, existing.is_active
                    existing.reaction = reaction_value
                    existing.is_active = True
                    existing.save(update_fields=['reaction', 'is_active', 'updated_at'])
                    reaction_obj = existing
                    created = False
                    if not old_is_active:
                        _update_reaction_counters(content.id, add=reaction_value)
                    elif old_reaction != reaction_value:
                        _update_reaction_counters(content.id, add=reaction_value, remove=old_reaction)
        except IntegrityError:
            # Extremely rare: two concurrent requests both saw no existing row
            logger.warning(
                'Concurrent reaction create race condition',
                extra={'user_id': user.id, 'content_id': content.id},
            )
            reaction_obj = Reaction.objects.get(user=user, content=content)
            created = False

        cache.delete(f'content_detail:{content.id}')
        return Response(
            ReactionSerializer(reaction_obj).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request, *args, **kwargs):
        serializer = ReactionUndoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        content = serializer.validated_data['content']

        reaction_obj = get_object_or_404(Reaction, user=user, content=content)
        if not reaction_obj.is_active:
            return Response(
                {'detail': 'Reaction is already inactive.'},
                status=status.HTTP_200_OK,
            )

        with transaction.atomic():
            reaction_obj.is_active = False
            reaction_obj.save(update_fields=['is_active', 'updated_at'])
            _update_reaction_counters(content.id, remove=reaction_obj.reaction)
        cache.delete(f'content_detail:{content.id}')
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentCreateView(LoggedExceptionMixin, generics.CreateAPIView):
    serializer_class = CommentCreateSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        Content.objects.filter(pk=instance.content_id).update(comment_count=F('comment_count') + 1)
        cache.delete(f'content_detail:{instance.content_id}')


class ContentCommentListView(LoggedExceptionMixin, generics.ListAPIView):
    serializer_class = CommentListSerializer
    pagination_class = CommentCursorPagination

    def get_queryset(self):
        get_object_or_404(Content.objects.only('id'), pk=self.kwargs['content_pk'])
        return (
            Comment.objects
            .filter(content_id=self.kwargs['content_pk'], parent__isnull=True)
            .select_related('user')
            .annotate(reply_count=Count('replies'))
            .order_by('created_at', 'id')
        )


class CommentRepliesView(LoggedExceptionMixin, generics.ListAPIView):
    serializer_class = CommentListSerializer
    pagination_class = CommentCursorPagination

    def get_queryset(self):
        get_object_or_404(Comment.objects.only('id'), pk=self.kwargs['pk'])
        return (
            Comment.objects
            .filter(parent_id=self.kwargs['pk'])
            .select_related('user')
            .annotate(reply_count=Count('replies'))
            .order_by('created_at', 'id')
        )
