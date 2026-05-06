from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .models import Comment, Content, Reaction

User = get_user_model()


class FeedApiTestCase(TestCase):
    def setUp(self):
        cache.clear()
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


# ---------------------------------------------------------------------------
# Content CRUD
# ---------------------------------------------------------------------------

class ContentCreateTest(FeedApiTestCase):
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
        }
        response = self.client.post(reverse('content-list'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', response.data)


# ---------------------------------------------------------------------------
# Content list — cursor-paginated responses use response.data['results']
# ---------------------------------------------------------------------------

class ContentListTest(FeedApiTestCase):
    def test_list_returns_paginated_shape(self):
        response = self.client.get(reverse('content-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)

    def test_list_filters_by_creator_and_active(self):
        response = self.client.get(
            reverse('content-list'), {'creator_id': self.creator.id, 'is_active': 'true'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.content.id)

        response = self.client.get(
            reverse('content-list'), {'creator_id': self.creator.id, 'is_active': 'false'}
        )
        results = response.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.inactive_content.id)

    def test_list_search_by_title(self):
        Content.objects.create(
            creator=self.creator,
            title='Summer Launch',
            body='https://example.com/media/summer.jpg',
            is_active=True,
        )
        response = self.client.get(reverse('content-list'), {'search': 'Launch'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        self.assertGreaterEqual(len(results), 2)
        self.assertTrue(all('Launch' in item['title'] for item in results))

    def test_list_invalid_creator_id_returns_error(self):
        response = self.client.get(reverse('content-list'), {'creator_id': 'abc'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('creator_id', response.data)

    def test_list_invalid_is_active_returns_error(self):
        response = self.client.get(reverse('content-list'), {'is_active': 'maybe'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('is_active', response.data)


# ---------------------------------------------------------------------------
# Content detail — comments shape changed to {results, has_more, reply_count}
# ---------------------------------------------------------------------------

class ContentDetailTest(FeedApiTestCase):
    def test_detail_comments_shape(self):
        top = Comment.objects.create(user=self.other_user, content=self.content, text='Great post')
        Comment.objects.create(user=self.third_user, content=self.content, parent=top, text='I agree')

        response = self.client.get(reverse('content-detail', args=[self.content.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        comments = response.data['comments']
        self.assertIn('results', comments)
        self.assertIn('has_more', comments)
        self.assertFalse(comments['has_more'])
        self.assertEqual(len(comments['results']), 1)
        self.assertEqual(comments['results'][0]['id'], top.id)
        self.assertEqual(comments['results'][0]['reply_count'], 1)
        self.assertNotIn('replies', comments['results'][0])

    def test_detail_comments_has_more_when_over_limit(self):
        for i in range(11):
            Comment.objects.create(user=self.other_user, content=self.content, text=f'Comment {i}')

        response = self.client.get(reverse('content-detail', args=[self.content.id]))
        comments = response.data['comments']
        self.assertEqual(len(comments['results']), 10)
        self.assertTrue(comments['has_more'])

    def test_detail_shows_denormalized_counters(self):
        # Set counters directly to verify the detail endpoint reads them from the model field
        self.content.like_count = 3
        self.content.dislike_count = 1
        self.content.comment_count = 5
        self.content.save(update_fields=['like_count', 'dislike_count', 'comment_count'])

        response = self.client.get(reverse('content-detail', args=[self.content.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['like_count'], 3)
        self.assertEqual(response.data['dislike_count'], 1)
        self.assertEqual(response.data['comment_count'], 5)

    def test_detail_unknown_content_returns_404(self):
        response = self.client.get(reverse('content-detail', args=[99999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Denormalized counters — verified via refresh_from_db after API calls
# ---------------------------------------------------------------------------

class ReactionCounterTest(FeedApiTestCase):
    def _react(self, user, reaction):
        return self.client.post(
            reverse('reaction-create-update'),
            {'user_id': user.id, 'content_id': self.content.id, 'reaction': reaction},
            format='json',
        )

    def _undo(self, user):
        return self.client.delete(
            reverse('reaction-create-update'),
            {'user_id': user.id, 'content_id': self.content.id},
            format='json',
        )

    def test_like_increments_like_count(self):
        self._react(self.other_user, 'like')
        self.content.refresh_from_db()
        self.assertEqual(self.content.like_count, 1)
        self.assertEqual(self.content.dislike_count, 0)

    def test_dislike_increments_dislike_count(self):
        self._react(self.other_user, 'dislike')
        self.content.refresh_from_db()
        self.assertEqual(self.content.like_count, 0)
        self.assertEqual(self.content.dislike_count, 1)

    def test_switch_like_to_dislike_swaps_counters(self):
        self._react(self.other_user, 'like')
        self._react(self.other_user, 'dislike')
        self.content.refresh_from_db()
        self.assertEqual(self.content.like_count, 0)
        self.assertEqual(self.content.dislike_count, 1)

    def test_same_reaction_again_does_not_change_counters(self):
        self._react(self.other_user, 'like')
        self._react(self.other_user, 'like')
        self.content.refresh_from_db()
        self.assertEqual(self.content.like_count, 1)

    def test_undo_decrements_counter(self):
        self._react(self.other_user, 'like')
        self._undo(self.other_user)
        self.content.refresh_from_db()
        self.assertEqual(self.content.like_count, 0)

    def test_reactivate_after_undo_increments_counter(self):
        self._react(self.other_user, 'like')
        self._undo(self.other_user)
        self._react(self.other_user, 'like')
        self.content.refresh_from_db()
        self.assertEqual(self.content.like_count, 1)

    def test_multiple_users_accumulate_correctly(self):
        self._react(self.other_user, 'like')
        self._react(self.third_user, 'like')
        self._react(self.creator, 'dislike')
        self.content.refresh_from_db()
        self.assertEqual(self.content.like_count, 2)
        self.assertEqual(self.content.dislike_count, 1)


class CommentCounterTest(FeedApiTestCase):
    def test_comment_create_increments_comment_count(self):
        self.client.post(
            reverse('comment-create'),
            {'user_id': self.other_user.id, 'content_id': self.content.id, 'text': 'Nice'},
            format='json',
        )
        self.content.refresh_from_db()
        self.assertEqual(self.content.comment_count, 1)

    def test_reply_create_also_increments_comment_count(self):
        parent = Comment.objects.create(user=self.other_user, content=self.content, text='Parent')
        self.client.post(
            reverse('comment-create'),
            {'user_id': self.third_user.id, 'content_id': self.content.id,
             'parent_id': parent.id, 'text': 'Reply'},
            format='json',
        )
        self.content.refresh_from_db()
        self.assertEqual(self.content.comment_count, 1)


# ---------------------------------------------------------------------------
# Reaction flow
# ---------------------------------------------------------------------------

class ReactionFlowTest(FeedApiTestCase):
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

        response = self.client.delete(
            reverse('reaction-create-update'),
            {'user_id': self.other_user.id, 'content_id': self.content.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Reaction.objects.get(user=self.other_user, content=self.content).is_active)

    def test_undo_already_inactive_returns_200(self):
        self.client.post(
            reverse('reaction-create-update'),
            {'user_id': self.other_user.id, 'content_id': self.content.id, 'reaction': 'like'},
            format='json',
        )
        self.client.delete(
            reverse('reaction-create-update'),
            {'user_id': self.other_user.id, 'content_id': self.content.id},
            format='json',
        )
        response = self.client.delete(
            reverse('reaction-create-update'),
            {'user_id': self.other_user.id, 'content_id': self.content.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_reaction_on_inactive_content_fails(self):
        payload = {'user_id': self.other_user.id, 'content_id': self.inactive_content.id, 'reaction': 'like'}
        response = self.client.post(reverse('reaction-create-update'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content_id', response.data)


# ---------------------------------------------------------------------------
# Comment flow
# ---------------------------------------------------------------------------

class CommentFlowTest(FeedApiTestCase):
    def test_comment_create_and_reply(self):
        payload = {'user_id': self.other_user.id, 'content_id': self.content.id, 'text': 'Nice work'}
        response = self.client.post(reverse('comment-create'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['text'], payload['text'])

        parent_id = response.data['id']
        response = self.client.post(
            reverse('comment-create'),
            {'user_id': self.third_user.id, 'content_id': self.content.id,
             'parent_id': parent_id, 'text': 'Agree'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Comment.objects.get(id=response.data['id']).parent_id, parent_id)

    def test_comment_parent_mismatch_returns_error(self):
        other_content = Content.objects.create(
            creator=self.creator,
            title='Other Content',
            body='https://example.com/media/other.jpg',
            is_active=True,
        )
        parent = Comment.objects.create(user=self.other_user, content=other_content, text='Other')
        response = self.client.post(
            reverse('comment-create'),
            {'user_id': self.third_user.id, 'content_id': self.content.id,
             'parent_id': parent.id, 'text': 'Invalid reply'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent_id', response.data)

    def test_comment_on_inactive_content_returns_error(self):
        response = self.client.post(
            reverse('comment-create'),
            {'user_id': self.other_user.id, 'content_id': self.inactive_content.id,
             'text': 'Cannot comment here'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content_id', response.data)


# ---------------------------------------------------------------------------
# Content comment list endpoint — GET /contents/<id>/comments/
# ---------------------------------------------------------------------------

class ContentCommentListTest(FeedApiTestCase):
    def test_returns_only_top_level_comments_with_reply_count(self):
        top = Comment.objects.create(user=self.other_user, content=self.content, text='Top')
        Comment.objects.create(user=self.third_user, content=self.content, parent=top, text='Reply')

        response = self.client.get(reverse('content-comment-list', args=[self.content.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], top.id)
        self.assertEqual(results[0]['reply_count'], 1)

    def test_excludes_replies_from_results(self):
        top = Comment.objects.create(user=self.other_user, content=self.content, text='Top')
        reply = Comment.objects.create(user=self.third_user, content=self.content, parent=top, text='Reply')

        response = self.client.get(reverse('content-comment-list', args=[self.content.id]))
        ids = [c['id'] for c in response.data['results']]
        self.assertNotIn(reply.id, ids)
        self.assertEqual(len(ids), 1)

    def test_is_cursor_paginated(self):
        for i in range(25):
            Comment.objects.create(user=self.other_user, content=self.content, text=f'Comment {i}')

        response = self.client.get(reverse('content-comment-list', args=[self.content.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 20)
        self.assertIsNotNone(response.data['next'])

    def test_unknown_content_returns_404(self):
        response = self.client.get(reverse('content-comment-list', args=[99999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Comment replies endpoint — GET /comments/<id>/replies/
# ---------------------------------------------------------------------------

class CommentRepliesTest(FeedApiTestCase):
    def test_returns_direct_children_with_reply_count(self):
        top = Comment.objects.create(user=self.other_user, content=self.content, text='Top')
        reply = Comment.objects.create(user=self.third_user, content=self.content, parent=top, text='Reply')
        Comment.objects.create(user=self.other_user, content=self.content, parent=reply, text='Nested')

        response = self.client.get(reverse('comment-replies', args=[top.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], reply.id)
        self.assertEqual(results[0]['reply_count'], 1)

    def test_nested_reply_own_replies_endpoint(self):
        top = Comment.objects.create(user=self.other_user, content=self.content, text='Top')
        reply = Comment.objects.create(user=self.third_user, content=self.content, parent=top, text='Reply')
        nested = Comment.objects.create(user=self.other_user, content=self.content, parent=reply, text='Nested')

        response = self.client.get(reverse('comment-replies', args=[reply.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], nested.id)

    def test_is_cursor_paginated(self):
        top = Comment.objects.create(user=self.other_user, content=self.content, text='Top')
        for i in range(25):
            Comment.objects.create(user=self.third_user, content=self.content, parent=top, text=f'Reply {i}')

        response = self.client.get(reverse('comment-replies', args=[top.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 20)
        self.assertIsNotNone(response.data['next'])

    def test_unknown_comment_returns_404(self):
        response = self.client.get(reverse('comment-replies', args=[99999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
