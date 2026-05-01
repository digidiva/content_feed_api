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

- `POST /api/contents/` - create content
- `GET /api/contents/` - list content
- `GET /api/contents/{id}/` - content detail
- `POST /api/reactions/` - create or update a reaction
- `POST /api/comments/` - add a comment or reply

## Notes

- Uses default Django `User` model for creator, reaction owner, and comment author.
- Uses SQLite by default for local development (`db.sqlite3`).
- Queryset annotations include like, dislike, and comment counts.
- Uses `select_related` and `prefetch_related` to avoid N+1 query issues.
