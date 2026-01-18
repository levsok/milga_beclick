from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(30), nullable=False)
    last_name = db.Column(db.String(30), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    profile_image = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    inquiries = db.relationship("Inquiry", backref="user", lazy=True)


class Inquiry(db.Model):
    __tablename__ = "inquiries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    full_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    subject = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    ip = db.Column(db.String(45), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ScholarshipSubmission(db.Model):
    __tablename__ = "scholarship_submissions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    scholarship_name = db.Column(db.String(120), nullable=False)
    interest_area = db.Column(db.String(120), nullable=False)
    has_submitted = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    ip = db.Column(db.String(45), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="scholarship_submissions")


class UserQuestionnaire(db.Model):
    __tablename__ = "user_questionnaire"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    study_status = db.Column(db.String(60), nullable=False)
    study_field = db.Column(db.String(80), nullable=False)
    institution = db.Column(db.String(120), nullable=False)
    military_status = db.Column(db.String(80), nullable=False)
    populations = db.Column(db.Text, nullable=False)
    work_status = db.Column(db.String(80), nullable=False)
    volunteer_willingness = db.Column(db.String(80), nullable=False)
    scholarship_duration_preference = db.Column(db.String(40), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="questionnaire", uselist=False)


class UserScholarship(db.Model):
    __tablename__ = "user_scholarships"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    scholarship_key = db.Column(db.String(64), nullable=False, index=True)
    scholarship_title = db.Column(db.String(200), nullable=False)
    scholarship_link = db.Column(db.String(500), nullable=True)
    match_score = db.Column(db.Integer, default=0, nullable=False)
    match_reasons = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="מעוניין")
    alerts_enabled = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="matched_scholarships")

    __table_args__ = (
        db.UniqueConstraint("user_id", "scholarship_key", name="uq_user_scholarship"),
    )


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    sender_type = db.Column(db.String(20), nullable=False, default="system")
    sender_label = db.Column(db.String(50), nullable=False, default="מערכת")
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)

    recipient = db.relationship("User", backref="notifications")


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    ip = db.Column(db.String(45), nullable=False, index=True)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    last_failed_at = db.Column(db.DateTime, nullable=True)
    locked_until = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("email", "ip", name="uq_login_attempts_email_ip"),
    )


class ScholarshipEvent(db.Model):
    __tablename__ = "scholarship_events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    scholarship_key = db.Column(db.String(64), nullable=False, index=True)
    event_type = db.Column(db.String(40), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "scholarship_key",
            "event_type",
            name="uq_scholarship_events_user_scholarship_type",
        ),
    )


class DailyJobRun(db.Model):
    __tablename__ = "daily_job_runs"

    id = db.Column(db.Integer, primary_key=True)
    job_name = db.Column(db.String(64), unique=True, nullable=False)
    last_run_date = db.Column(db.Date, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
