from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .models import Comment, Content, Reaction

User = get_user_model()


class FeedApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.creator = User.objects.create_user(username='creator', password='password')
        self.other_user = User.objects.create_user(username='other', password='password')
        self.third_user = User.objects.create_user(username='third', password='password')

        self.content = Content.objects.create(
            creator=self.creator,
            title='Spring Launch',
            body='https://example.com/media/spring.jpg',
            is_active=True,
        )
        self.inactive_content = Content.objects.create(
            creator=self.creator,
            title='Hidden Draft',
            body='https://example.com/media/draft.jpg',
            is_active=False,
        )

    def test_create_content_success(self):
        payload = {
            'creator_id': self.other_user.id,
            'title': 'New Media Post',
            'body': 'https://example.com/media/video.mp4',
            'is_active': True,
        }
        response = self.client.post(reverse('content-list'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], payload['title'])
        self.assertEqual(response.data['creator']['id'], self.other_user.id)
        self.assertTrue(response.data['is_active'])

    def test_create_content_missing_title_returns_error(self):
        payload = {
            'creator_id': self.other_user.id,
            'body': 'https://example.com/media/video.mp4',
            'is_active': True,
        }
        response = self.client.post(reverse('content-list'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', response.data)

    def test_list_content_filters_by_creator_and_active(self):
        response = self.client.get(reverse('content-list'), {'creator_id': self.creator.id, 'is_active': 'true'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.content.id)

        response = self.client.get(reverse('content-list'), {'creator_id': self.creator.id, 'is_active': 'false'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.inactive_content.id)

    def test_list_content_search_and_ordering(self):
        Content.objects.create(
            creator=self.creator,
            title='Summer Launch',
            body='https://example.com/media/summer.jpg',
            is_active=True,
        )
        response = self.client.get(reverse('content-list'), {'search': 'Launch', 'ordering': '-created_at'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 2)
        self.assertTrue(all('Launch' in item['title'] for item in response.data))

    def test_content_detail_includes_nested_comments_and_counts(self):
        top_comment = Comment.objects.create(
            user=self.other_user,
            content=self.content,
            text='Great post',
        )
        Comment.objects.create(
            user=self.third_user,
            content=self.content,
            parent=top_comment,
            text='I agree',
        )
        Reaction.objects.create(user=self.other_user, content=self.content, reaction=Reaction.LIKE)
        Reaction.objects.create(user=self.third_user, content=self.content, reaction=Reaction.DISLIKE)

        response = self.client.get(reverse('content-detail', args=[self.content.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['like_count'], 1)
        self.assertEqual(response.data['dislike_count'], 1)
        self.assertEqual(response.data['comment_count'], 2)
        self.assertEqual(len(response.data['comments']), 1)
        self.assertEqual(len(response.data['comments'][0]['replies']), 1)

    def test_reaction_create_update_and_undo(self):
        payload = {'user_id': self.other_user.id, 'content_id': self.content.id, 'reaction': 'like'}
        response = self.client.post(reverse('reaction-create-update'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['reaction'], 'like')
        self.assertTrue(response.data['is_active'])

        payload['reaction'] = 'dislike'
        response = self.client.post(reverse('reaction-create-update'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['reaction'], 'dislike')
        self.assertTrue(response.data['is_active'])

        response = self.client.delete(reverse('reaction-create-update'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        reaction = Reaction.objects.get(user=self.other_user, content=self.content)
        self.assertFalse(reaction.is_active)

    def test_reaction_on_inactive_content_fails(self):
        payload = {'user_id': self.other_user.id, 'content_id': self.inactive_content.id, 'reaction': 'like'}
        response = self.client.post(reverse('reaction-create-update'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content_id', response.data)

    def test_comment_create_and_reply(self):
        payload = {
            'user_id': self.other_user.id,
            'content_id': self.content.id,
            'text': 'Nice work',
        }
        response = self.client.post(reverse('comment-create'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['text'], payload['text'])

        parent_id = response.data['id']
        reply_payload = {
            'user_id': self.third_user.id,
            'content_id': self.content.id,
            'parent_id': parent_id,
            'text': 'Agree with this',
        }
        response = self.client.post(reverse('comment-create'), reply_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_reply = Comment.objects.get(id=response.data['id'])
        self.assertEqual(created_reply.parent_id, parent_id)

    def test_comment_parent_mismatch_returns_error(self):
        other_content = Content.objects.create(
            creator=self.creator,
            title='Other Content',
            body='https://example.com/media/other.jpg',
            is_active=True,
        )
        parent_comment = Comment.objects.create(
            user=self.other_user,
            content=other_content,
            text='Other content comment',
        )
        payload = {
            'user_id': self.third_user.id,
            'content_id': self.content.id,
            'parent_id': parent_comment.id,
            'text': 'Invalid reply',
        }
        response = self.client.post(reverse('comment-create'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent_id', response.data)

    def test_comment_on_inactive_content_returns_error(self):
        payload = {
            'user_id': self.other_user.id,
            'content_id': self.inactive_content.id,
            'text': 'Cannot comment here',
        }
        response = self.client.post(reverse('comment-create'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content_id', response.data)

    def test_invalid_filter_values_return_error(self):
        response = self.client.get(reverse('content-list'), {'creator_id': 'abc'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('creator_id', response.data)

        response = self.client.get(reverse('content-list'), {'is_active': 'maybe'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('is_active', response.data)
