from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CommentCreateView,
    CommentRepliesView,
    ContentCommentListView,
    ContentViewSet,
    ReactionCreateUpdateView,
)

router = DefaultRouter()
router.register(r'contents', ContentViewSet, basename='content')

urlpatterns = [
    path('', include(router.urls)),
    path('reactions/', ReactionCreateUpdateView.as_view(), name='reaction-create-update'),
    path('comments/', CommentCreateView.as_view(), name='comment-create'),
    path('contents/<int:content_pk>/comments/', ContentCommentListView.as_view(), name='content-comment-list'),
    path('comments/<int:pk>/replies/', CommentRepliesView.as_view(), name='comment-replies'),
]
