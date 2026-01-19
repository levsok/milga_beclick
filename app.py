import os
import json
import logging
from pathlib import Path
from io import BytesIO

from env_utils import load_environment

load_environment()
logger = logging.getLogger(__name__)

if not os.getenv("NOTION_TOKEN") or not os.getenv("NOTION_DATABASE_ID"):
    logger.warning(
        "Missing NOTION_TOKEN or NOTION_DATABASE_ID; Notion integrations will be disabled."
    )

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_EMAIL_NORMALIZED = ADMIN_EMAIL.strip().lower() if ADMIN_EMAIL else None
if not ADMIN_EMAIL_NORMALIZED:
    logger.warning("ADMIN_EMAIL is not set; admin access will be disabled.")
from datetime import datetime, timedelta

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from urllib.parse import urlparse
from sqlalchemy import case, func
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from make_service import build_make_payload, notify_make
from digest_service import run_daily_scholarships_digest, LOCAL_TZ

from forms import (
    ContactForm,
    LoginForm,
    QuestionnaireForm,
    RegisterForm,
    ChangePasswordForm,
    ProfileImageForm,
    AdminMessageForm,
    MarkAllReadForm,
    RefreshMatchesForm,
    ScholarshipSubmissionForm,
    ScholarshipUpdateForm,
)
from matching_service import compute_matches, upsert_user_scholarships
from models import (
    Inquiry,
    LoginAttempt,
    ScholarshipSubmission,
    ScholarshipEvent,
    User,
    UserQuestionnaire,
    UserScholarship,
    Notification,
    db,
)
from notion_service import fetch_notion_pages_raw, fetch_scholarships


LOCKOUT_THRESHOLD = 8
LOCKOUT_WINDOW = timedelta(minutes=5)
EVENT_INTEREST = "interest_event"
EVENT_APPLICATION = "application_event"
EVENT_ACCEPTANCE = "acceptance_event"
EVENT_NOT_INTERESTED = "not_interested_event"
SCHOLARSHIP_IMAGE_DIR = Path("static/scholarship_images")
SCHOLARSHIP_IMAGE_FILES = sorted(
    [path.name for path in SCHOLARSHIP_IMAGE_DIR.glob("*") if path.is_file()]
)
SCHOLARSHIP_IMAGE_KEYWORDS = [
    ({"atidim", "עתידים"}, "01_atidim_scholarship.jpg"),
    ({"milgafo", "מלגפו"}, "02_milgafo.jpg"),
    ({"periphery", "פריפריה"}, "03_periphery_scholarship_keren_haim_meshulrarim.jpg"),
    ({"sapir", "peace", "שלום", "ספיר"}, "04_sapir_peace_leadership.jpg"),
    ({"lenovo", "לנובו"}, "05_lenovo_scholarship.jpg"),
    ({"memadim", "ממדים"}, "06_memadim_lelimudim.jpg"),
    ({"civic", "liberal", "אזרחי"}, "07_civic_liberal_scholarship.jpg"),
    ({"ministry", "education", "משרד החינוך", "milga go"}, "08_milga_go_ministry_of_education.jpg"),
    ({"noar", "latet", "נוער לתת"}, "09_noar_latet.jpg"),
    ({"gross", "foundation", "גרוס"}, "10_gross_foundation.jpg"),
]


def _resolve_database_uri():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgres://"):
            return database_url.replace("postgres://", "postgresql://", 1)
        return database_url
    sqlite_path = os.getenv("SQLITE_DB_PATH")
    render_disk = os.getenv("RENDER_DISK_PATH", "/var/data")
    if os.getenv("RENDER") == "true" and not sqlite_path:
        sqlite_path = str(Path(render_disk) / "scholarship_autopilot.db")
        logger.info("Using Render persistent SQLite database at %s", sqlite_path)
    if sqlite_path:
        resolved = Path(sqlite_path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{resolved}"
    logger.warning(
        "DATABASE_URL is not set; using local SQLite database (not suitable for production)."
    )
    return "sqlite:///scholarship_autopilot.db"


def is_admin_user(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if not ADMIN_EMAIL_NORMALIZED:
        return False
    if not user.email:
        return False
    return user.email.strip().lower() == ADMIN_EMAIL_NORMALIZED


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = _resolve_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    logger.info(
        "Make webhook configuration: url_configured=%s api_key_configured=%s",
        bool(os.getenv("MAKE_WEBHOOK_URL")),
        bool(os.getenv("MAKE_WEBHOOK_API_KEY")),
    )

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.template_filter("datetime")
    def format_datetime(value):
        if not value:
            return ""
        return value.strftime("%d/%m/%Y %H:%M")

    @app.context_processor
    def inject_admin_flag():
        unread_count = 0
        if current_user.is_authenticated:
            unread_count = (
                Notification.query.filter_by(recipient_user_id=current_user.id)
                .filter(Notification.read_at.is_(None))
                .count()
            )
        return {
            "is_admin": is_admin_user(current_user),
            "unread_notifications": unread_count,
        }

    def get_client_ip():
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.remote_addr or "unknown"

    def is_safe_next(url):
        if not url:
            return False
        test_url = urlparse(url)
        return test_url.scheme == "" and test_url.netloc == ""

    def user_served_military(status):
        return status in ("במהלך שירות", "חייל משוחרר", "שירות לאומי / אזרחי")

    def is_eligible(requirements, questionnaire):
        if not requirements or not questionnaire:
            return True
        if requirements.get("volunteering") is True and questionnaire.volunteer_willingness == "לא":
            return False
        if requirements.get("military") is True and not user_served_military(
            questionnaire.military_status
        ):
            return False
        return True

    def resolve_scholarship_image(title, index):
        title_lower = (title or "").lower()
        for keywords, filename in SCHOLARSHIP_IMAGE_KEYWORDS:
            if any(keyword in title_lower for keyword in keywords):
                return filename
        if SCHOLARSHIP_IMAGE_FILES:
            return SCHOLARSHIP_IMAGE_FILES[index % len(SCHOLARSHIP_IMAGE_FILES)]
        return None

    def _record_scholarship_event(user_id, scholarship_key, event_type):
        existing = ScholarshipEvent.query.filter_by(
            user_id=user_id,
            scholarship_key=scholarship_key,
            event_type=event_type,
        ).first()
        if not existing:
            db.session.add(
                ScholarshipEvent(
                    user_id=user_id,
                    scholarship_key=scholarship_key,
                    event_type=event_type,
                )
            )

    def record_status_events(user_id, scholarship_key, status):
        if status in ("מעוניין", "הגשתי", "התקבלתי"):
            _record_scholarship_event(user_id, scholarship_key, EVENT_INTEREST)
        if status in ("הגשתי", "התקבלתי"):
            _record_scholarship_event(user_id, scholarship_key, EVENT_APPLICATION)
        if status == "התקבלתי":
            _record_scholarship_event(user_id, scholarship_key, EVENT_ACCEPTANCE)
        if status == "לא מעוניין":
            _record_scholarship_event(user_id, scholarship_key, EVENT_NOT_INTERESTED)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/health")
    def health_check():
        return jsonify(
            make_configured=bool(os.getenv("MAKE_WEBHOOK_URL"))
            and bool(os.getenv("MAKE_WEBHOOK_API_KEY")),
            notion_configured=bool(os.getenv("NOTION_TOKEN"))
            and bool(os.getenv("NOTION_DATABASE_ID")),
            admin_email_configured=bool(ADMIN_EMAIL_NORMALIZED),
        )

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        form = RegisterForm()
        if form.validate_on_submit():
            user = User(
                first_name=form.first_name.data.strip(),
                last_name=form.last_name.data.strip(),
                phone=form.phone.data,
                email=form.email.data,
                password_hash=generate_password_hash(form.password.data),
            )
            db.session.add(user)
            db.session.commit()
            signup_html = render_template(
                "email_user_registered.html",
                user=user,
            )
            payload = build_make_payload(
                email=user.email,
                event_title="user_registered",
                html=signup_html,
                subject="נרשמת בהצלחה למערכת המלגות",
                is_test=False,
            )
            notify_make(payload)
            flash("ההרשמה הצליחה. אפשר להתחבר כעת.", "success")
            return redirect(url_for("login"))
        return render_template("register.html", form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        form = LoginForm()
        if form.validate_on_submit():
            email = form.email.data.lower().strip()
            ip = get_client_ip()
            # Track login attempts per email+IP to apply a 5-minute lockout after 8 failures.
            attempt = LoginAttempt.query.filter_by(email=email, ip=ip).first()
            now = datetime.utcnow()
            if attempt and attempt.locked_until and attempt.locked_until > now:
                remaining = int((attempt.locked_until - now).total_seconds() // 60) + 1
                flash(
                    f"החשבון ננעל זמנית בעקבות ניסיונות כושלים. נסה שוב בעוד {remaining} דקות.",
                    "danger",
                )
                return render_template("login.html", form=form)

            user = User.query.filter_by(email=email).first()
            if user and check_password_hash(user.password_hash, form.password.data):
                if attempt:
                    attempt.attempts = 0
                    attempt.locked_until = None
                    attempt.last_failed_at = None
                    db.session.commit()
                login_user(user)
                next_url = request.args.get("next")
                if is_safe_next(next_url):
                    return redirect(next_url)
                return redirect(url_for("dashboard"))

            if not attempt:
                attempt = LoginAttempt(email=email, ip=ip, attempts=0)
                db.session.add(attempt)
            attempt.attempts = (attempt.attempts or 0) + 1
            attempt.last_failed_at = now
            if attempt.attempts >= LOCKOUT_THRESHOLD:
                attempt.locked_until = now + LOCKOUT_WINDOW
            db.session.commit()
            flash("אימייל או סיסמה שגויים", "danger")
        return render_template("login.html", form=form)

    @app.route("/dashboard")
    @login_required
    def dashboard():
        status_priority = case(
            (UserScholarship.status == "התקבלתי", 1),
            (UserScholarship.status == "הגשתי", 2),
            (UserScholarship.status == "מעוניין", 3),
            (UserScholarship.status == "לא מעוניין", 5),
            else_=4,
        )
        scholarships = (
            UserScholarship.query.filter_by(user_id=current_user.id)
            .filter(UserScholarship.match_score > 0)
            .order_by(
                status_priority.asc(),
                UserScholarship.match_score.desc(),
                UserScholarship.updated_at.desc(),
            )
            .limit(10)
            .all()
        )
        notifications = (
            Notification.query.filter_by(recipient_user_id=current_user.id)
            .order_by(Notification.created_at.desc())
            .limit(3)
            .all()
        )
        return render_template(
            "dashboard.html",
            scholarships=scholarships,
            notifications=notifications,
        )

    @app.route("/contact", methods=["GET", "POST"])
    @login_required
    def contact():
        form = ContactForm()
        if form.validate_on_submit():
            inquiry = Inquiry(
                user_id=current_user.id,
                full_name=form.full_name.data,
                email=form.email.data,
                phone=form.phone.data,
                subject=form.subject.data.strip(),
                message=form.message.data.strip(),
                ip=get_client_ip(),
            )
            db.session.add(inquiry)
            db.session.commit()
            flash("תודה! ההודעה נקלטה במערכת.", "success")
            return redirect(url_for("contact"))
        return render_template("contact.html", form=form)

    @app.route("/send", methods=["GET", "POST"])
    @login_required
    def send():
        form = ScholarshipSubmissionForm()
        if form.validate_on_submit():
            submission = ScholarshipSubmission(
                user_id=current_user.id,
                scholarship_name=form.scholarship_name.data.strip(),
                interest_area=form.interest_area.data.strip(),
                has_submitted=form.has_submitted.data,
                notes=(form.notes.data or "").strip() or None,
                ip=get_client_ip(),
            )
            db.session.add(submission)
            db.session.commit()
            flash("המידע נשמר בהצלחה.", "success")
            return redirect(url_for("send"))
        return render_template("send.html", form=form)

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("התנתקת בהצלחה", "info")
        return redirect(url_for("index"))

    def unfinished_route():
        if not current_user.is_authenticated:
            return redirect(url_for("login", next=request.path))
        return render_template("403.html"), 403

    @app.route("/about")
    def about():
        return unfinished_route()

    @app.route("/questionnaire", methods=["GET", "POST"])
    @login_required
    def questionnaire():
        existing = UserQuestionnaire.query.filter_by(user_id=current_user.id).first()
        form = QuestionnaireForm()
        if existing and request.method == "GET":
            form.study_status.data = existing.study_status
            form.study_field.data = existing.study_field
            form.institution.data = existing.institution
            form.military_status.data = existing.military_status
            form.populations.data = json.loads(existing.populations)
            form.work_status.data = existing.work_status
            form.volunteer_willingness.data = existing.volunteer_willingness
            form.scholarship_duration_preference.data = (
                existing.scholarship_duration_preference
            )
        if form.validate_on_submit():
            payload = {
                "study_status": form.study_status.data,
                "study_field": form.study_field.data,
                "institution": form.institution.data.strip(),
                "military_status": form.military_status.data,
                "populations": json.dumps(form.populations.data, ensure_ascii=False),
                "work_status": form.work_status.data,
                "volunteer_willingness": form.volunteer_willingness.data,
                "scholarship_duration_preference": form.scholarship_duration_preference.data,
            }
            if existing:
                for key, value in payload.items():
                    setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
                existing.submitted_at = existing.submitted_at or datetime.utcnow()
            else:
                db.session.add(
                    UserQuestionnaire(
                        user_id=current_user.id,
                        submitted_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                        **payload,
                    )
                )
            db.session.commit()

            matches, error = compute_matches(
                UserQuestionnaire.query.filter_by(user_id=current_user.id).first()
            )
            if error:
                flash(error, "info")
            else:
                upsert_user_scholarships(current_user.id, matches)
            return redirect(url_for("my_scholarships", refreshed=1))
        return render_template(
            "questionnaire.html",
            form=form,
            has_existing=bool(existing),
        )

    @app.route("/profile")
    @login_required
    def profile():
        password_form = ChangePasswordForm(prefix="pwd")
        image_form = ProfileImageForm(prefix="img")

        if password_form.validate_on_submit() and password_form.submit.data:
            if not check_password_hash(current_user.password_hash, password_form.current_password.data):
                flash("הסיסמה הנוכחית שגויה", "danger")
            else:
                current_user.password_hash = generate_password_hash(password_form.new_password.data)
                db.session.commit()
                flash("הסיסמה עודכנה בהצלחה", "success")
            return redirect(url_for("profile"))

        if image_form.validate_on_submit() and image_form.submit.data:
            file = image_form.image.data
            if file and file.filename:
                uploads_dir = Path("static/uploads/profile")
                uploads_dir.mkdir(parents=True, exist_ok=True)
                filename = secure_filename(file.filename)
                stored_name = f"user_{current_user.id}_{int(datetime.utcnow().timestamp())}_{filename}"
                file.save(uploads_dir / stored_name)
                current_user.profile_image = f"uploads/profile/{stored_name}"
                db.session.commit()
                flash("תמונת הפרופיל עודכנה", "success")
            else:
                flash("נא לבחור קובץ תמונה", "info")
            return redirect(url_for("profile"))

        return render_template(
            "profile.html",
            password_form=password_form,
            image_form=image_form,
        )

    @app.route("/scholarships")
    @login_required
    def scholarships():
        scholarships, error = fetch_scholarships()
        questionnaire = UserQuestionnaire.query.filter_by(user_id=current_user.id).first()
        if questionnaire:
            scholarships = [
                item
                for item in scholarships
                if is_eligible(item.get("requirements"), questionnaire)
            ]
        for index, item in enumerate(scholarships):
            image_name = resolve_scholarship_image(item.get("title"), index)
            if image_name:
                item["image"] = f"scholarship_images/{image_name}"
        return render_template(
            "scholarships.html",
            scholarships=scholarships,
            error=error,
        )

    @app.route("/my-scholarships", methods=["GET", "POST"])
    @login_required
    def my_scholarships():
        update_form = ScholarshipUpdateForm()
        refresh_form = RefreshMatchesForm()
        if request.method == "POST" and request.form.get("scholarship_id"):
            if not update_form.validate_on_submit():
                flash("לא ניתן לעדכן את המלגה. נסה שוב.", "danger")
                return redirect(url_for("my_scholarships"))
            record = UserScholarship.query.filter_by(
                id=update_form.scholarship_id.data, user_id=current_user.id
            ).first()
            if record:
                previous_status = record.status
                record.status = update_form.status.data
                record.alerts_enabled = "alerts_enabled" in request.form
                record.updated_at = datetime.utcnow()
                if previous_status != record.status:
                    record_status_events(
                        current_user.id,
                        record.scholarship_key,
                        record.status,
                    )
                db.session.commit()
                flash("העדכון נשמר.", "success")
            return redirect(url_for("my_scholarships"))

        records = (
            UserScholarship.query.filter_by(user_id=current_user.id)
            .order_by(UserScholarship.match_score.desc(), UserScholarship.updated_at.desc())
            .all()
        )
        questionnaire = UserQuestionnaire.query.filter_by(user_id=current_user.id).first()
        requirements_map = {}
        if questionnaire:
            pages, error = fetch_notion_pages_raw()
            if not error:
                requirements_map = {
                    page["id"]: page.get("requirements") for page in pages
                }
        items = []
        for record in records:
            if record.match_score == 0:
                continue
            requirements = requirements_map.get(record.scholarship_key)
            if not is_eligible(requirements, questionnaire):
                continue
            if record.match_score >= 6:
                level = "high"
            elif record.match_score >= 3:
                level = "medium"
            else:
                level = "low"
            reasons = json.loads(record.match_reasons)
            items.append(
                {
                    "id": record.id,
                    "title": record.scholarship_title,
                    "link": record.scholarship_link,
                    "score": record.match_score,
                    "level": level,
                    "reasons": reasons,
                    "status": record.status,
                    "alerts_enabled": record.alerts_enabled,
                }
            )
        return render_template(
            "my_scholarships.html",
            scholarships=items,
            update_form=update_form,
            refresh_form=refresh_form,
            refreshed=request.args.get("refreshed") == "1",
        )

    @app.route("/my-scholarships/refresh", methods=["POST"])
    @login_required
    def refresh_my_scholarships():
        refresh_form = RefreshMatchesForm()
        if not refresh_form.validate_on_submit():
            return redirect(url_for("my_scholarships"))
        questionnaire = UserQuestionnaire.query.filter_by(user_id=current_user.id).first()
        if not questionnaire:
            flash("יש למלא שאלון לפני רענון התאמות.", "info")
            return redirect(url_for("questionnaire"))
        matches, error = compute_matches(questionnaire)
        if error:
            flash(error, "info")
        else:
            upsert_user_scholarships(current_user.id, matches)
            flash("ההתאמות עודכנו.", "success")
        return redirect(url_for("my_scholarships", refreshed=1))

    @app.route("/api/alerts-feed")
    def alerts_feed():
        token = os.getenv("ALERTS_FEED_TOKEN")
        auth_header = request.headers.get("Authorization", "")
        provided = auth_header.replace("Bearer ", "", 1).strip()
        if not token or provided != token:
            return {"error": "unauthorized"}, 401
        rows = (
            db.session.query(UserScholarship, User)
            .join(User, User.id == UserScholarship.user_id)
            .filter(UserScholarship.alerts_enabled.is_(True))
            .filter(UserScholarship.status != "לא מעוניין")
            .all()
        )
        payload = []
        for record, user in rows:
            payload.append(
                {
                    "user_email": user.email,
                    "user_phone": user.phone,
                    "scholarship_title": record.scholarship_title,
                    "scholarship_link": record.scholarship_link,
                    "status": record.status,
                }
            )
        return {"data": payload}

    @app.route("/updates")
    @login_required
    def updates():
        open_id = request.args.get("open")
        mark_all_form = MarkAllReadForm()
        if open_id:
            notification = Notification.query.filter_by(
                id=open_id, recipient_user_id=current_user.id
            ).first()
            if notification and not notification.read_at:
                notification.read_at = datetime.utcnow()
                db.session.commit()
        notifications = (
            Notification.query.filter_by(recipient_user_id=current_user.id)
            .order_by(Notification.created_at.desc())
            .all()
        )
        return render_template(
            "updates.html",
            notifications=notifications,
            open_id=str(open_id) if open_id else None,
            mark_all_form=mark_all_form,
        )

    @app.route("/updates/mark-all", methods=["POST"])
    @login_required
    def mark_all_updates():
        form = MarkAllReadForm()
        if form.validate_on_submit():
            Notification.query.filter_by(recipient_user_id=current_user.id).filter(
                Notification.read_at.is_(None)
            ).update({"read_at": datetime.utcnow()})
            db.session.commit()
            flash("כל ההודעות סומנו כנקראות.", "success")
        return redirect(url_for("updates"))

    @app.route("/admin")
    @login_required
    def admin():
        if not is_admin_user(current_user):
            abort(403)
        users = User.query.order_by(User.created_at.desc()).all()
        inquiries = Inquiry.query.order_by(Inquiry.created_at.desc()).all()
        submissions = ScholarshipSubmission.query.order_by(
            ScholarshipSubmission.created_at.desc()
        ).all()
        scholarships_catalog, scholarships_error = fetch_scholarships()
        return render_template(
            "admin.html",
            users=users,
            inquiries=inquiries,
            submissions=submissions,
            scholarships_catalog=scholarships_catalog,
            scholarships_error=scholarships_error,
        )

    @app.route("/admin/test-make", methods=["POST"])
    @login_required
    def admin_test_make():
        if not is_admin_user(current_user):
            abort(403)
        make_configured = bool(os.getenv("MAKE_WEBHOOK_URL")) and bool(
            os.getenv("MAKE_WEBHOOK_API_KEY")
        )
        print("[MAKE] test endpoint called")
        print("[MAKE] make_configured:", make_configured)
        test_html = render_template(
            "email_user_registered.html",
            user=current_user,
            is_test=True,
        )
        payload = build_make_payload(
            email=current_user.email,
            event_title="user_registered",
            html=test_html,
            subject="[TEST] בדיקת הרשמה - Make",
            is_test=True,
        )
        notify_make(payload)
        flash("נשלחה בדיקת webhook ל-Make.", "success")
        return redirect(url_for("admin"))

    @app.route("/admin/run-digest", methods=["POST"])
    @login_required
    def admin_run_digest():
        if not is_admin_user(current_user):
            abort(403)
        result = run_daily_scholarships_digest(force=True, is_test=True)
        if result.get("skipped"):
            flash("לא נשלחה הודעה - אין נתונים זמינים.", "info")
        else:
            flash("נשלח עדכון מלגות יומי.", "success")
        return redirect(url_for("admin"))

    @app.route("/admin/scholarships/<scholarship_id>/analytics")
    @login_required
    def admin_scholarship_analytics(scholarship_id):
        if not is_admin_user(current_user):
            abort(403)
        days = request.args.get("days", "all")
        counts = {
            "interested": 0,
            "applied": 0,
            "accepted": 0,
            "not_interested": 0,
        }
        source = "status"
        if days in ("7", "30", "90"):
            source = "events"
            start_date = datetime.utcnow() - timedelta(days=int(days))
            rows = (
                ScholarshipEvent.query.filter_by(scholarship_key=scholarship_id)
                .filter(ScholarshipEvent.created_at >= start_date)
                .with_entities(
                    ScholarshipEvent.event_type,
                    func.count(func.distinct(ScholarshipEvent.user_id)),
                )
                .group_by(ScholarshipEvent.event_type)
                .all()
            )
            for event_type, total in rows:
                if event_type == EVENT_INTEREST:
                    counts["interested"] = total
                elif event_type == EVENT_APPLICATION:
                    counts["applied"] = total
                elif event_type == EVENT_ACCEPTANCE:
                    counts["accepted"] = total
                elif event_type == EVENT_NOT_INTERESTED:
                    counts["not_interested"] = total
        else:
            base_query = UserScholarship.query.filter_by(scholarship_key=scholarship_id)
            counts["interested"] = base_query.filter(
                UserScholarship.status.in_(["מעוניין", "הגשתי", "התקבלתי"])
            ).count()
            counts["applied"] = base_query.filter(
                UserScholarship.status.in_(["הגשתי", "התקבלתי"])
            ).count()
            counts["accepted"] = base_query.filter(
                UserScholarship.status == "התקבלתי"
            ).count()
            counts["not_interested"] = base_query.filter(
                UserScholarship.status == "לא מעוניין"
            ).count()

        applied_rate = (
            round((counts["applied"] / counts["interested"]) * 100)
            if counts["interested"]
            else 0
        )
        accepted_rate = (
            round((counts["accepted"] / counts["applied"]) * 100)
            if counts["applied"]
            else 0
        )
        return jsonify(
            {
                "scholarship_id": scholarship_id,
                "counts": counts,
                "rates": {
                    "applied_rate": applied_rate,
                    "accepted_rate": accepted_rate,
                },
                "window": days,
                "source": source,
            }
        )

    @app.route("/admin/users/<int:user_id>", methods=["GET", "POST"])
    @login_required
    def admin_user_profile(user_id):
        if not is_admin_user(current_user):
            abort(403)
        user = User.query.get_or_404(user_id)
        message_form = AdminMessageForm()
        if message_form.validate_on_submit():
            db.session.add(
                Notification(
                    recipient_user_id=user.id,
                    sender_type="admin",
                    sender_label="מנהל",
                    title=message_form.title.data.strip(),
                    body=message_form.body.data.strip(),
                )
            )
            db.session.commit()
            flash("ההודעה נשלחה למשתמש.", "success")
            return redirect(url_for("admin_user_profile", user_id=user.id))

        scholarships = (
            UserScholarship.query.filter_by(user_id=user.id)
            .filter(UserScholarship.match_score > 0)
            .order_by(UserScholarship.updated_at.desc())
            .all()
        )
        all_pages, pages_error = fetch_notion_pages_raw()
        all_scholarships = []
        if not pages_error:
            user_map = {
                item.scholarship_key: item
                for item in UserScholarship.query.filter_by(user_id=user.id).all()
            }
            for page in all_pages:
                match = user_map.get(page.get("id"))
                all_scholarships.append(
                    {
                        "id": page.get("id"),
                        "title": page.get("title"),
                        "url": page.get("url"),
                        "status": match.status if match else "לא סומן",
                        "alerts_enabled": match.alerts_enabled if match else None,
                        "updated_at": match.updated_at if match else None,
                    }
                )
        submissions = (
            ScholarshipSubmission.query.filter_by(user_id=user.id)
            .order_by(ScholarshipSubmission.created_at.desc())
            .all()
        )
        notifications = (
            Notification.query.filter_by(recipient_user_id=user.id)
            .order_by(Notification.created_at.desc())
            .all()
        )
        return render_template(
            "admin_user.html",
            user=user,
            scholarships=scholarships,
            all_scholarships=all_scholarships,
            submissions=submissions,
            notifications=notifications,
            message_form=message_form,
        )

    @app.route("/admin/export/users")
    @login_required
    def admin_export_users():
        if not is_admin_user(current_user):
            abort(403)
        from openpyxl import Workbook
        users = User.query.order_by(User.id).all()
        wb = Workbook()
        ws = wb.active
        ws.title = "Users"
        ws.append(["id", "first_name", "last_name", "phone", "email", "created_at"])
        for user in users:
            ws.append(
                [
                    user.id,
                    user.first_name,
                    user.last_name,
                    user.phone,
                    user.email,
                    user.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return send_file(
            buffer,
            as_attachment=True,
            download_name="users.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("404.html"), 404

    with app.app_context():
        db.create_all()

    def start_scheduler():
        if os.getenv("DISABLE_SCHEDULER") == "1":
            return
        scheduler = BackgroundScheduler(timezone=LOCAL_TZ)

        def job():
            with app.app_context():
                run_daily_scholarships_digest()

        scheduler.add_job(
            job,
            CronTrigger(hour=16, minute=0),
            id="daily_scholarships_digest",
            replace_existing=True,
        )
        scheduler.start()
        with app.app_context():
            run_daily_scholarships_digest()

    if not app.debug or os.getenv("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler()

    return app


app = create_app()
