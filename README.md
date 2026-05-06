# content_feed_api

A minimal Django REST Framework project skeleton for a Content Feed API.

## Setup

1. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install Django djangorestframework
   ```
3. Configure environment variables:
   ```bash
   export DJANGO_SECRET_KEY='replace-with-secure-key'
   export DJANGO_DEBUG=True
   ```
4. Run migrations:
   ```bash
   python manage.py migrate
   ```
5. Start the development server:
   ```bash
   python manage.py runserver
   ```

## Production Database (PostgreSQL)

For production, use PostgreSQL instead of SQLite. Update `content_feed_api/settings.py` as follows:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'content_feed_api'),
        'USER': os.environ.get('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}
```

Install the PostgreSQL driver:

```bash
pip install psycopg2-binary
```

Set environment variables before deploying:

```bash
export POSTGRES_DB=content_feed_api
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD='replace-with-secure-password'
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
```

## API Endpoints

### Content

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/contents/` | Create content |
| `GET` | `/api/contents/` | List content (cursor-paginated) |
| `GET` | `/api/contents/{id}/` | Content detail with comment preview |
| `PUT` | `/api/contents/{id}/` | Full update content |
| `PATCH` | `/api/contents/{id}/` | Partial update content |
| `DELETE` | `/api/contents/{id}/` | Delete content |

**List query params:** `creator_id`, `is_active`, `search`, `page_size`, `cursor`

**Content detail — `comments` field structure:**
```json
{
  "results": [{ "id": 1, "user": {}, "text": "...", "created_at": "...", "parent_id": null, "reply_count": 3 }],
  "has_more": true
}
```
Returns up to 10 top-level comments. Use the comments list endpoint to paginate further.

---

### Reactions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/reactions/` | Create or update a reaction (`like` / `dislike`) |
| `DELETE` | `/api/reactions/` | Undo (deactivate) a reaction |

**Request body:** `user_id`, `content_id`, `reaction` (`like` or `dislike`)

---

### Comments

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/comments/` | Add a comment or reply |
| `GET` | `/api/contents/{id}/comments/` | Paginated top-level comments for content |
| `GET` | `/api/comments/{id}/replies/` | Paginated direct replies to a comment |

**`POST /api/comments/` body:** `user_id`, `content_id`, `text`, `parent_id` (optional — omit for top-level)

**Comment list / replies response shape (cursor-paginated):**
```json
{
  "next": "http://...",
  "previous": null,
  "results": [{ "id": 1, "user": {}, "text": "...", "created_at": "...", "parent_id": null, "reply_count": 2 }]
}
```

`reply_count` is the number of direct replies. Call `GET /api/comments/{id}/replies/` recursively to load deeper levels.

**Query params for list endpoints:** `page_size`, `cursor`

## Notes

- Uses the default Django `User` model for creator, reaction owner, and comment author.
- Uses SQLite by default for local development (`db.sqlite3`).
- `like_count`, `dislike_count`, and `comment_count` are denormalized fields on `Content`, updated atomically with `F()` expressions on every reaction/comment write.
- Content detail responses are cached in Redis (`REDIS_URL` env var). Falls back to in-memory cache when `REDIS_URL` is not set.
- All list endpoints use cursor pagination (set `CONTENT_DETAIL_CACHE_TTL` env var to control cache TTL, default 60s).
- Uses `select_related` and `prefetch_related` to avoid N+1 query issues.
