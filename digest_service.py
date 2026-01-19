import html
import logging
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

from make_service import build_make_payload, notify_make
from models import DailyJobRun, User, UserScholarship, db
from notion_service import fetch_scholarships


logger = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("Asia/Jerusalem")
JOB_NAME = "scholarships_digest"
DAILY_RUN_TIME = time(hour=16, minute=0)
INTERESTED_STATUSES = ("מעוניין", "הגשתי", "התקבלתי")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
if not ADMIN_EMAIL:
    logger.warning("ADMIN_EMAIL is not set; admin notifications will be skipped.")
OPEN_FIELD_NAMES = [
    "תאריך פתיחה",
    "מועד פתיחה",
    "פתיחה",
    "open",
    "start",
    "from",
]
CLOSE_FIELD_NAMES = [
    "תאריך סיום",
    "מועד אחרון",
    "דדליין",
    "deadline",
    "close",
    "end",
    "to",
]
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d")


def _parse_date(value, pick):
    if not value:
        return None
    text = str(value).strip()
    if " - " in text:
        parts = [part.strip() for part in text.split(" - ") if part.strip()]
        if not parts:
            return None
        text = parts[0] if pick == "start" else parts[-1]
    if "T" in text:
        text = text.split("T")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _extract_date(fields, field_names, pick):
    field_names_lower = [name.lower() for name in field_names]
    for field in fields or []:
        name = (field.get("name") or "").lower()
        if any(key in name for key in field_names_lower):
            value = field.get("value")
            return _parse_date(value, pick)
    return None


def get_open_scholarships():
    scholarships, error = fetch_scholarships()
    if error:
        return [], error

    today = datetime.now(LOCAL_TZ).date()
    open_items = []
    for scholarship in scholarships:
        fields = scholarship.get("fields") or []
        open_date = _extract_date(fields, OPEN_FIELD_NAMES, "start")
        close_date = _extract_date(fields, CLOSE_FIELD_NAMES, "end")
        if not open_date or not close_date:
            continue
        if open_date <= today <= close_date:
            summary = _find_field_value(fields, ["תיאור", "תקציר", "summary", "פרטים"])
            open_items.append(
                {
                    "id": scholarship.get("id"),
                    "title": scholarship.get("title"),
                    "url": scholarship.get("url"),
                    "summary": summary,
                    "open_date": open_date,
                    "close_date": close_date,
                }
            )
    return open_items, None


def _find_field_value(fields, keywords):
    for field in fields or []:
        name = (field.get("name") or "").lower()
        if any(keyword in name for keyword in keywords):
            return field.get("value")
    return None


def _format_date(value):
    if not value:
        return "לא זמין"
    return value.strftime("%d/%m/%Y")


def build_digest_message(open_items, user=None, is_test=False):
    has_items = bool(open_items)
    subject = "עדכון יומי: מלגות פתוחות" if has_items else "עדכון יומי: אין מלגות פתוחות"
    if is_test:
        subject = f"[TEST] {subject}"

    greeting = ""
    if user and user.first_name:
        greeting = f"<p style=\"margin: 0 0 12px;\">היי {html.escape(user.first_name)},</p>"

    test_banner = ""
    if is_test:
        test_banner = (
            "<div style=\"background:#fee2e2;color:#991b1b;"
            "padding:8px 12px;border-radius:10px;font-size:12px;margin-bottom:12px;\">"
            "בדיקת מערכת</div>"
        )

    if has_items:
        cards = ""
        for item in open_items:
            cards += (
                "<div style=\"border:1px solid #e2e8f0;border-radius:14px;"
                "padding:16px;margin-bottom:12px;\">"
                f"<div style=\"font-size:16px;font-weight:700;color:#0f172a;\">"
                f"{html.escape(item.get('title') or 'מלגה')}</div>"
                f"<div style=\"color:#475569;margin:6px 0 10px;\">"
                f"{html.escape(item.get('summary') or 'אין תיאור זמין')}</div>"
                f"<div style=\"font-size:13px;color:#334155;\">נפתח ב: "
                f"{_format_date(item.get('open_date'))}</div>"
                f"<div style=\"font-size:13px;color:#334155;\">נסגר ב: "
                f"{_format_date(item.get('close_date'))}</div>"
                f"<a href=\"{html.escape(item.get('url') or '#')}\" "
                "style=\"display:inline-block;margin-top:12px;padding:10px 16px;"
                "background:#14b8a6;color:#ffffff;text-decoration:none;border-radius:999px;"
                "font-weight:600;\">להגשה עכשיו</a>"
                "</div>"
            )
        body_html = (
            "<h2 style=\"margin:0 0 8px;color:#0f172a;\">"
            "מצאנו עבורך מלגות פתוחות היום!</h2>"
            "<p style=\"margin:0 0 16px;color:#334155;\">"
            "אל תפספס/י — הזדמנות מעולה מחכה לך. כדאי להגיש עכשיו.</p>"
            f"{cards}"
        )
    else:
        body_html = (
            "<h2 style=\"margin:0 0 8px;color:#0f172a;\">"
            "אין מלגות פתוחות היום</h2>"
            "<p style=\"margin:0;color:#334155;\">"
            "נמשיך לבדוק עבורך ונעדכן מחר.</p>"
        )

    digest_html = (
        "<div style=\"font-family: Assistant, Arial, sans-serif; direction: rtl;"
        "background-color:#f8fafc;padding:24px;\">"
        "<div style=\"max-width:640px;margin:0 auto;background:#ffffff;"
        "border-radius:18px;padding:24px;border:1px solid #e2e8f0;\">"
        f"{test_banner}"
        f"{greeting}"
        f"{body_html}"
        "</div></div>"
    )
    return subject, digest_html


def _should_run_today(now_local):
    return now_local.time() >= DAILY_RUN_TIME


def run_daily_scholarships_digest(force=False, is_test=False):
    now_local = datetime.now(LOCAL_TZ)
    today = now_local.date()
    if not force and not _should_run_today(now_local):
        return {"skipped": True, "reason": "before_window"}

    job_run = DailyJobRun.query.filter_by(job_name=JOB_NAME).first()
    if job_run and job_run.last_run_date == today and not force:
        return {"skipped": True, "reason": "already_ran"}

    open_items, error = get_open_scholarships()
    if error:
        logger.error("Digest skipped: %s", error)
        return {"skipped": True, "reason": "data_error"}

    if not open_items:
        subject, digest_html = build_digest_message(open_items, None, is_test=is_test)
        if ADMIN_EMAIL:
            payload = build_make_payload(
                email=ADMIN_EMAIL,
                event_title="scholarships_daily_update",
                html=digest_html,
                subject=subject,
                is_test=is_test,
            )
            notify_make(payload)
        else:
            logger.warning("Skipping admin digest email because ADMIN_EMAIL is missing.")
    else:
        users = (
            User.query.join(UserScholarship, UserScholarship.user_id == User.id)
            .filter(UserScholarship.status.in_(INTERESTED_STATUSES))
            .distinct()
            .all()
        )
        if not users and not is_test:
            logger.info("Digest skipped: no interested users")
        elif is_test:
            if not ADMIN_EMAIL:
                logger.warning(
                    "Skipping test digest email because ADMIN_EMAIL is missing."
                )
            else:
                subject, digest_html = build_digest_message(
                    open_items, None, is_test=is_test
                )
                payload = build_make_payload(
                    email=ADMIN_EMAIL,
                    event_title="scholarships_daily_update",
                    html=digest_html,
                    subject=subject,
                    is_test=is_test,
                )
                notify_make(payload)
        else:
            for user in users:
                subject, digest_html = build_digest_message(
                    open_items, user, is_test=is_test
                )
                payload = build_make_payload(
                    email=user.email,
                    event_title="scholarships_daily_update",
                    html=digest_html,
                    subject=subject,
                    is_test=is_test,
                )
                notify_make(payload)

    if not is_test:
        if not job_run:
            job_run = DailyJobRun(job_name=JOB_NAME)
            db.session.add(job_run)
        job_run.last_run_date = today
        job_run.updated_at = datetime.utcnow()
        db.session.commit()
    return {"skipped": False, "open_count": len(open_items)}
