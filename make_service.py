import logging
import os

import requests


logger = logging.getLogger(__name__)
ALLOWED_EVENTS = {"user_registered", "scholarships_daily_update"}
TEST_EMAIL = os.getenv("MAKE_TEST_EMAIL", "test@example.com")

def build_make_payload(email, event_title, html, subject, is_test=False):
    if event_title not in ALLOWED_EVENTS:
        raise ValueError(f"Invalid event_title: {event_title}")
    if not html or not str(html).strip():
        raise ValueError("html must be non-empty")

    resolved_email = TEST_EMAIL if is_test else email
    if not resolved_email or not str(resolved_email).strip():
        raise ValueError("email must be non-empty")
    return {
        "email": str(resolved_email).strip(),
        "event_title": event_title,
        "is_test": bool(is_test),
        "subject": subject,
        "html": html,
    }


def notify_make(payload, timeout_seconds=7):
    webhook_url = os.getenv("MAKE_WEBHOOK_URL")
    api_key = os.getenv("MAKE_WEBHOOK_API_KEY")
    if not webhook_url or not api_key:
        logger.warning("Make webhook not configured; skipping event")
        return

    headers = {
        "Content-Type": "application/json",
        "x-make-apikey": api_key,
    }
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
        if not response.ok:
            logger.error(
                "Make webhook failed: status=%s body=%s",
                response.status_code,
                response.text,
            )
    except requests.exceptions.RequestException as exc:
        logger.error("Make webhook error: %s", exc)
