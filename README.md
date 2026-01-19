# Scholarship Autopilot (מלגה בקליק)

Flask app for a university project that helps students discover and track scholarships, with automated email notifications and admin analytics.

## Prerequisites
- Python 3.11+

## Setup (local)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment variables
Copy and edit:
```bash
cp .env.example .env
```
Set the values in `.env` (or your hosting provider):

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`
- `ADMIN_EMAIL`
- `SECRET_KEY`
- `DATABASE_URL`

Optional Make.com webhook values are also loaded from the environment.

## Database
The app uses SQLAlchemy and prefers a Postgres connection string via `DATABASE_URL` (recommended for Render).
If `DATABASE_URL` is missing, the app falls back to a local SQLite database for development only.

## Run locally
```bash
flask --app app:app run
```

## Production (Gunicorn)
```bash
gunicorn app:app
```

## Deploy checklist (Render)
- Set `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `ADMIN_EMAIL`, `SECRET_KEY`, `DATABASE_URL` in Render.
- Share the Notion database with the integration so the token has access.

## Notes
- Scheduler runs daily at 16:00 Asia/Jerusalem when the app is running.
- Make.com webhook secrets are loaded from environment variables.
