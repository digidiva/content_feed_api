from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Comment, Content, Reaction

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']


class RecursiveField(serializers.Serializer):
    def to_representation(self, value):
        serializer = self.parent.parent.__class__(value, context=self.context)
        return serializer.data


class CommentSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    replies = RecursiveField(many=True, read_only=True)

    class Meta:
        model = Comment
        fields = ['id', 'user', 'text', 'created_at', 'parent', 'replies']
        read_only_fields = ['id', 'user', 'created_at', 'replies']


class CommentCreateSerializer(serializers.ModelSerializer):
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source='user',
        write_only=True,
        error_messages={
            'does_not_exist': 'User with id "{pk_value}" does not exist.',
            'required': 'user_id is required.',
        },
    )
    content_id = serializers.PrimaryKeyRelatedField(
        queryset=Content.objects.all(),
        source='content',
        write_only=True,
        error_messages={
            'does_not_exist': 'Content with id "{pk_value}" does not exist.',
            'required': 'content_id is required.',
        },
    )
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Comment.objects.select_related('content'),
        allow_null=True,
        required=False,
        write_only=True,
        error_messages={
            'does_not_exist': 'Parent comment with id "{pk_value}" does not exist.',
        },
    )
    parent_id = serializers.PrimaryKeyRelatedField(
        read_only=True,
        source='parent',
    )

    class Meta:
        model = Comment
        fields = ['id', 'user_id', 'content_id', 'parent', 'parent_id', 'text', 'created_at']
        read_only_fields = ['id', 'created_at', 'parent_id']

    def to_internal_value(self, data):
        if 'parent_id' in data and 'parent' not in data:
            data = data.copy()
            data['parent'] = data.pop('parent_id')
        return super().to_internal_value(data)

    def validate_text(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Comment text is required.')
        return value

    def validate(self, attrs):
        content = attrs.get('content')
        parent = attrs.get('parent')

        if content and not content.is_active:
            raise serializers.ValidationError({'content_id': 'Cannot comment on inactive content.'})

        if parent and content and parent.content_id != content.id:
            raise serializers.ValidationError({'parent_id': 'Parent comment must belong to the same content.'})

        return attrs


class ReactionSerializer(serializers.ModelSerializer):
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source='user',
        write_only=True,
        error_messages={
            'does_not_exist': 'User with id "{pk_value}" does not exist.',
            'required': 'user_id is required.',
        },
    )
    content_id = serializers.PrimaryKeyRelatedField(
        queryset=Content.objects.all(),
        source='content',
        write_only=True,
        error_messages={
            'does_not_exist': 'Content with id "{pk_value}" does not exist.',
            'required': 'content_id is required.',
        },
    )
    reaction = serializers.ChoiceField(
        choices=[Reaction.LIKE, Reaction.DISLIKE],
        error_messages={
            'invalid_choice': 'Reaction must be either "like" or "dislike".',
            'required': 'reaction is required.',
        },
    )
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = Reaction
        fields = ['id', 'user_id', 'content_id', 'reaction', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at', 'is_active']
        validators = []

    def validate(self, attrs):
        content = attrs.get('content')
        if content and not content.is_active:
            raise serializers.ValidationError({'content_id': 'Cannot react to inactive content.'})
        return attrs


class ReactionUndoSerializer(serializers.Serializer):
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source='user',
        error_messages={
            'does_not_exist': 'User with id "{pk_value}" does not exist.',
            'required': 'user_id is required.',
        },
    )
    content_id = serializers.PrimaryKeyRelatedField(
        queryset=Content.objects.all(),
        source='content',
        error_messages={
            'does_not_exist': 'Content with id "{pk_value}" does not exist.',
            'required': 'content_id is required.',
        },
    )


class ContentBaseSerializer(serializers.ModelSerializer):
    creator = UserSerializer(read_only=True)
    creator_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source='creator',
        write_only=True,
        error_messages={
            'does_not_exist': 'Creator with id "{pk_value}" does not exist.',
            'required': 'creator_id is required.',
        },
    )
    like_count = serializers.IntegerField(read_only=True)
    dislike_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Content
        fields = [
            'id',
            'creator',
            'creator_id',
            'title',
            'body',
            'is_active',
            'created_at',
            'like_count',
            'dislike_count',
            'comment_count',
        ]
        read_only_fields = ['id', 'creator', 'created_at', 'like_count', 'dislike_count', 'comment_count']

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Title is required.')
        return value


class ContentDetailSerializer(ContentBaseSerializer):
    comments = serializers.SerializerMethodField()

    class Meta(ContentBaseSerializer.Meta):
        fields = ContentBaseSerializer.Meta.fields + ['comments']

    def get_comments(self, obj):
        prefetched_comments = getattr(obj, '_prefetched_objects_cache', {}).get('comments')
        if prefetched_comments is not None:
            comments = list(prefetched_comments)
        else:
            comments = list(obj.comments.select_related('user').order_by('created_at'))

        children_by_parent = {}
        for comment in comments:
            children_by_parent.setdefault(comment.parent_id, []).append(comment)

        def serialize_comment(comment):
            return {
                'id': comment.id,
                'user': UserSerializer(comment.user).data,
                'text': comment.text,
                'created_at': comment.created_at,
                'parent': comment.parent_id,
                'replies': [
                    serialize_comment(reply)
                    for reply in children_by_parent.get(comment.id, [])
                ],
            }

        return [
            serialize_comment(comment)
            for comment in children_by_parent.get(None, [])
        ]


class ContentListSerializer(ContentBaseSerializer):
    class Meta(ContentBaseSerializer.Meta):
        fields = ContentBaseSerializer.Meta.fields
