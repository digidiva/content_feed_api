from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CommentCreateView, ContentViewSet, ReactionCreateUpdateView

router = DefaultRouter()
router.register(r'contents', ContentViewSet, basename='content')

urlpatterns = [
    path('', include(router.urls)),
    path('reactions/', ReactionCreateUpdateView.as_view(), name='reaction-create-update'),
    path('comments/', CommentCreateView.as_view(), name='comment-create'),
]
