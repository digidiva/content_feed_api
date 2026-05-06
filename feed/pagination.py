from rest_framework.pagination import CursorPagination


class ContentCursorPagination(CursorPagination):
    # -id tiebreaker: two rows can share the same created_at microsecond, never the same id
    ordering = ('-created_at', '-id')
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class CommentCursorPagination(CursorPagination):
    ordering = ('created_at', 'id')
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
