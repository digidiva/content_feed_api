import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import filters, generics, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Comment, Content, Reaction
from .serializers import (
    CommentCreateSerializer,
    ContentDetailSerializer,
    ContentListSerializer,
    ReactionSerializer,
    ReactionUndoSerializer,
)

logger = logging.getLogger(__name__)


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
    queryset = Content.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title']
    ordering_fields = ['created_at', 'like_count']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ContentDetailSerializer
        return ContentListSerializer

    def get_queryset(self):
        queryset = (
            Content.objects.select_related('creator')
            .annotate(
                like_count=Count(
                    'reactions',
                    filter=Q(reactions__reaction=Reaction.LIKE, reactions__is_active=True),
                    distinct=True,
                ),
                dislike_count=Count(
                    'reactions',
                    filter=Q(reactions__reaction=Reaction.DISLIKE, reactions__is_active=True),
                    distinct=True,
                ),
                comment_count=Count('comments', distinct=True),
            )
        )

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
            comments_prefetch = Prefetch(
                'comments',
                queryset=Comment.objects.select_related('user').order_by('created_at'),
            )
            queryset = queryset.prefetch_related(comments_prefetch)

        return queryset

    def perform_create(self, serializer):
        serializer.save()


class ReactionCreateUpdateView(LoggedExceptionMixin, APIView):
    def post(self, request, *args, **kwargs):
        serializer = ReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        content = serializer.validated_data['content']
        reaction_value = serializer.validated_data['reaction']

        try:
            with transaction.atomic():
                reaction_obj, created = Reaction.objects.update_or_create(
                    user=user,
                    content=content,
                    defaults={'reaction': reaction_value, 'is_active': True},
                )
        except IntegrityError:
            logger.warning(
                'Concurrent duplicate reaction write resolved',
                extra={
                    'user_id': user.id,
                    'content_id': content.id,
                    'reaction': reaction_value,
                },
            )
            reaction_obj = Reaction.objects.get(user=user, content=content)
            reaction_obj.reaction = reaction_value
            reaction_obj.is_active = True
            reaction_obj.save(update_fields=['reaction', 'is_active', 'updated_at'])
            created = False

        output_serializer = ReactionSerializer(reaction_obj)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        serializer = ReactionUndoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        content = serializer.validated_data['content']

        reaction_obj = get_object_or_404(
            Reaction.objects.select_related('user', 'content'),
            user=user,
            content=content,
        )
        if not reaction_obj.is_active:
            return Response(
                {'detail': 'Reaction is already inactive.'},
                status=status.HTTP_200_OK,
            )

        reaction_obj.is_active = False
        reaction_obj.save(update_fields=['is_active', 'updated_at'])

        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentCreateView(LoggedExceptionMixin, generics.CreateAPIView):
    serializer_class = CommentCreateSerializer

    def perform_create(self, serializer):
        serializer.save()
