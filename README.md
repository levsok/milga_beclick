<<<<<<< HEAD
# milga_beclick
Automated reminder system for the Scholarship Project. Handles deadline tracking, periodic checks, and email notification triggers.
=======
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
Set the values in `.env`.

## Run locally
```bash
flask --app app:app run
```

## Production (Gunicorn)
```bash
gunicorn app:app
```

## Notes
- Scheduler runs daily at 16:00 Asia/Jerusalem when the app is running.
- Make.com webhook secrets are loaded from environment variables.
>>>>>>> 4ad9b4a (Initial commit)
