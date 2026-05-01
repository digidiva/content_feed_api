from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Content(TimeStampedModel):
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='contents',
    )
    title = models.CharField(max_length=255)
    body = models.URLField(max_length=1024, help_text='URL for an image or video asset')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class Reaction(TimeStampedModel):
    LIKE = 'like'
    DISLIKE = 'dislike'
    REACTION_CHOICES = [
        (LIKE, 'Like'),
        (DISLIKE, 'Dislike'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reactions',
    )
    content = models.ForeignKey(
        Content,
        on_delete=models.CASCADE,
        related_name='reactions',
    )
    reaction = models.CharField(max_length=7, choices=REACTION_CHOICES)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('user', 'content')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user_id} {self.reaction} {self.content_id} (active={self.is_active})'


class Comment(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='comments',
    )
    content = models.ForeignKey(
        Content,
        on_delete=models.CASCADE,
        related_name='comments',
    )
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='replies',
    )
    text = models.TextField()

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Comment {self.id} by user {self.user_id}'
