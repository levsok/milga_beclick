import logging
import os
from urllib.parse import urlparse

import requests


logger = logging.getLogger(__name__)
ALLOWED_EVENTS = {"user_registered", "scholarships_daily_update"}


def mask_email(email):
    if not email:
        return ""
    email = str(email)
    if "@" not in email:
        return "***"
    local_part, domain = email.split("@", 1)
    if not local_part:
        return f"***@{domain}"
    visible = local_part[:4]
    return f"{visible}***@{domain}"


def build_make_payload(email, event_title, html, subject, is_test=False):
    if event_title not in ALLOWED_EVENTS:
        raise ValueError(f"Invalid event_title: {event_title}")
    if not html or not str(html).strip():
        raise ValueError("html must be non-empty")

    resolved_email = email
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

    parsed_url = urlparse(webhook_url)
    print("[MAKE] posting to:", parsed_url.netloc)

    headers = {
        "Content-Type": "application/json",
        "x-make-apikey": api_key,
    }
    event_title = payload.get("event_title") if isinstance(payload, dict) else None
    masked_email = mask_email(payload.get("email") if isinstance(payload, dict) else None)
    logger.info(
        "Sending Make webhook event: event_title=%s email=%s",
        event_title,
        masked_email,
    )
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
    except requests.exceptions.RequestException as exc:
        print("[MAKE] exception:", exc)
        logger.error(
            "Make webhook error: event_title=%s email=%s error=%s",
            event_title,
            masked_email,
            exc,
        )
        return

    truncated_body = (response.text or "")[:200]
    print("[MAKE] status:", response.status_code)
    print("[MAKE] body:", truncated_body)
    logger.info(
        "Make webhook response: event_title=%s email=%s status=%s body=%s",
        event_title,
        masked_email,
        response.status_code,
        truncated_body,
    )
    if not response.ok:
        logger.error(
            "Make webhook failed: status=%s body=%s",
            response.status_code,
            truncated_body,
        )
