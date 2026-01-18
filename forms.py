import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, PasswordField, SelectField, SelectMultipleField, StringField, SubmitField, TextAreaField
from flask_wtf.file import FileField
from wtforms.validators import DataRequired, Email, Length, ValidationError

from models import User


NAME_REGEX = re.compile(r"^[A-Za-z\u0590-\u05FF ]+$")
PHONE_LOCAL_REGEX = re.compile(r"^05\d{8}$")
PHONE_INTL_REGEX = re.compile(r"^\+9725\d{8}$")

PASSWORD_DENYLIST = {
    "password",
    "1234567890",
    "qwerty12345",
    "iloveyou123",
    "admin12345",
    "letmein123",
}


def normalize_phone(value):
    if PHONE_LOCAL_REGEX.match(value):
        return "+972" + value[1:]
    if PHONE_INTL_REGEX.match(value):
        return value
    return None


class RegisterForm(FlaskForm):
    first_name = StringField(
        "שם פרטי",
        validators=[
            DataRequired(message="נא להזין שם פרטי"),
            Length(min=2, max=30, message="שם פרטי חייב להיות בין 2 ל-30 תווים"),
        ],
    )
    last_name = StringField(
        "שם משפחה",
        validators=[
            DataRequired(message="נא להזין שם משפחה"),
            Length(min=2, max=30, message="שם משפחה חייב להיות בין 2 ל-30 תווים"),
        ],
    )
    phone = StringField("טלפון", validators=[DataRequired(message="נא להזין טלפון")])
    email = StringField(
        "אימייל",
        validators=[
            DataRequired(message="נא להזין אימייל"),
            Email(message="אימייל לא תקין"),
        ],
    )
    password = PasswordField("סיסמה", validators=[DataRequired(message="נא להזין סיסמה")])
    confirm_password = PasswordField(
        "אימות סיסמה",
        validators=[DataRequired(message="נא להזין אימות סיסמה")],
    )
    submit = SubmitField("הרשמה")

    def validate_first_name(self, field):
        if not NAME_REGEX.match(field.data.strip()):
            raise ValidationError("שם פרטי יכול להכיל רק אותיות ורווחים")

    def validate_last_name(self, field):
        if not NAME_REGEX.match(field.data.strip()):
            raise ValidationError("שם משפחה יכול להכיל רק אותיות ורווחים")

    def validate_phone(self, field):
        normalized = normalize_phone(field.data.strip())
        if not normalized:
            raise ValidationError("מספר טלפון ישראלי לא תקין")
        field.data = normalized

    def validate_email(self, field):
        existing = User.query.filter_by(email=field.data.lower().strip()).first()
        if existing:
            raise ValidationError("האימייל כבר רשום במערכת")
        field.data = field.data.lower().strip()

    def validate_password(self, field):
        value = field.data or ""
        errors = []
        if len(value) < 10:
            errors.append("הסיסמה חייבת להכיל לפחות 10 תווים")
        if not re.search(r"[A-Z]", value):
            errors.append("הסיסמה חייבת להכיל אות גדולה")
        if not re.search(r"[a-z]", value):
            errors.append("הסיסמה חייבת להכיל אות קטנה")
        if not re.search(r"\d", value):
            errors.append("הסיסמה חייבת להכיל ספרה")
        if not re.search(r"[^A-Za-z0-9]", value):
            errors.append("הסיסמה חייבת להכיל תו מיוחד")
        if value.lower() in PASSWORD_DENYLIST:
            errors.append("הסיסמה שנבחרה נפוצה מדי")
        if errors:
            raise ValidationError("; ".join(errors))

    def validate_confirm_password(self, field):
        if field.data != self.password.data:
            raise ValidationError("אימות הסיסמה אינו תואם")


class LoginForm(FlaskForm):
    email = StringField(
        "אימייל",
        validators=[
            DataRequired(message="נא להזין אימייל"),
            Email(message="אימייל לא תקין"),
        ],
    )
    password = PasswordField("סיסמה", validators=[DataRequired(message="נא להזין סיסמה")])
    submit = SubmitField("כניסה")


class ContactForm(FlaskForm):
    full_name = StringField(
        "שם מלא",
        validators=[
            DataRequired(message="נא להזין שם מלא"),
            Length(min=2, max=80, message="שם מלא חייב להיות בין 2 ל-80 תווים"),
        ],
    )
    email = StringField(
        "אימייל",
        validators=[
            DataRequired(message="נא להזין אימייל"),
            Email(message="אימייל לא תקין"),
        ],
    )
    phone = StringField("טלפון", validators=[DataRequired(message="נא להזין טלפון")])
    subject = StringField(
        "נושא",
        validators=[
            DataRequired(message="נא להזין נושא"),
            Length(min=2, max=120, message="נושא חייב להיות בין 2 ל-120 תווים"),
        ],
    )
    message = TextAreaField(
        "הודעה",
        validators=[
            DataRequired(message="נא להזין הודעה"),
            Length(min=10, max=2000, message="הודעה חייבת להיות בין 10 ל-2000 תווים"),
        ],
    )
    submit = SubmitField("שליחה")

    def validate_phone(self, field):
        normalized = normalize_phone(field.data.strip())
        if not normalized:
            raise ValidationError("מספר טלפון ישראלי לא תקין")
        field.data = normalized

    def validate_full_name(self, field):
        if not NAME_REGEX.match(field.data.strip()):
            raise ValidationError("שם מלא יכול להכיל רק אותיות ורווחים")
        field.data = field.data.strip()

    def validate_email(self, field):
        field.data = field.data.lower().strip()


class ScholarshipSubmissionForm(FlaskForm):
    scholarship_name = StringField(
        "שם המלגה",
        validators=[
            DataRequired(message="נא להזין את שם המלגה"),
            Length(min=2, max=120, message="שם המלגה חייב להיות בין 2 ל-120 תווים"),
        ],
    )
    interest_area = StringField(
        "תחום עניין",
        validators=[
            DataRequired(message="נא להזין תחום עניין"),
            Length(min=2, max=120, message="תחום עניין חייב להיות בין 2 ל-120 תווים"),
        ],
    )
    has_submitted = BooleanField("כבר שלחתי את הבקשה למלגה")
    notes = TextAreaField(
        "הערות נוספות",
        validators=[Length(max=1000, message="הערות יכולות להכיל עד 1000 תווים")],
    )
    submit = SubmitField("שליחה")


class QuestionnaireForm(FlaskForm):
    study_status = SelectField(
        "סטטוס לימודים",
        choices=[
            ("מכינה", "מכינה"),
            ("תואר ראשון", "תואר ראשון"),
            ("תואר שני", "תואר שני"),
            ("הנדסאי", "הנדסאי"),
        ],
        validators=[DataRequired(message="נא לבחור סטטוס לימודים")],
    )
    study_field = SelectField(
        "תחום לימודים",
        choices=[
            ("הנדסה / מדעים מדויקים", "הנדסה / מדעים מדויקים"),
            ("מדעי החברה / כלכלה / ניהול", "מדעי החברה / כלכלה / ניהול"),
            ("חינוך / מדעי הרוח", "חינוך / מדעי הרוח"),
            ("רפואה / מקצועות הבריאות", "רפואה / מקצועות הבריאות"),
            ("אחר", "אחר"),
        ],
        validators=[DataRequired(message="נא לבחור תחום לימודים")],
    )
    institution = StringField(
        "מוסד לימודים",
        validators=[DataRequired(message="נא להזין מוסד לימודים"), Length(min=2, max=120)],
    )
    military_status = SelectField(
        "סטטוס צבאי/שירות",
        choices=[
            ("לפני שירות", "לפני שירות"),
            ("במהלך שירות", "במהלך שירות"),
            ("חייל משוחרר", "חייל משוחרר"),
            ("שירות לאומי / אזרחי", "שירות לאומי / אזרחי"),
            ("לא רלוונטי", "לא רלוונטי"),
        ],
        validators=[DataRequired(message="נא לבחור סטטוס שירות")],
    )
    populations = SelectMultipleField(
        "אוכלוסיות",
        choices=[
            ("תושב פריפריה", "תושב פריפריה"),
            ("עולה חדש", "עולה חדש"),
            ("יוצא אתיופיה", "יוצא אתיופיה"),
            ("חרדי", "חרדי"),
            ("ערבי / דרוזי", "ערבי / דרוזי"),
            ("נכות מוכרת", "נכות מוכרת"),
            ("לא משתייך", "לא משתייך"),
        ],
        validators=[DataRequired(message="נא לבחור לפחות אפשרות אחת")],
    )
    work_status = SelectField(
        "סטטוס תעסוקתי",
        choices=[
            ("לא עובד", "לא עובד"),
            ("עובד עד חצי משרה", "עובד עד חצי משרה"),
            ("עובד יותר מחצי משרה", "עובד יותר מחצי משרה"),
        ],
        validators=[DataRequired(message="נא לבחור סטטוס תעסוקתי")],
    )
    volunteer_willingness = SelectField(
        "נכונות להתנדבות",
        choices=[
            ("לא", "לא"),
            ("כן, עד 50 שעות בשנה", "כן, עד 50 שעות בשנה"),
            ("כן, עד 100 שעות בשנה", "כן, עד 100 שעות בשנה"),
            ("כן, גם יותר", "כן, גם יותר"),
        ],
        validators=[DataRequired(message="נא לבחור נכונות להתנדבות")],
    )
    scholarship_duration_preference = SelectField(
        "העדפת משך מלגה",
        choices=[
            ("חד-פעמית", "חד-פעמית"),
            ("שנתית", "שנתית"),
            ("רב-שנתית", "רב-שנתית"),
            ("לא משנה", "לא משנה"),
        ],
        validators=[DataRequired(message="נא לבחור העדפה")],
    )
    submit = SubmitField("שמור שאלון")


class ScholarshipUpdateForm(FlaskForm):
    scholarship_id = HiddenField(validators=[DataRequired()])
    status = SelectField(
        "סטטוס",
        choices=[
            ("הגשתי", "הגשתי"),
            ("מעוניין", "מעוניין"),
            ("לא מעוניין", "לא מעוניין"),
            ("התקבלתי", "התקבלתי"),
        ],
        validators=[DataRequired()],
    )
    alerts_enabled = BooleanField("אשמח לקבל התראות על מלגה זו")
    submit = SubmitField("עדכון")


class RefreshMatchesForm(FlaskForm):
    submit = SubmitField("רענן התאמות")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("סיסמה נוכחית", validators=[DataRequired(message="נא להזין סיסמה נוכחית")])
    new_password = PasswordField("סיסמה חדשה", validators=[DataRequired(message="נא להזין סיסמה חדשה")])
    confirm_new_password = PasswordField(
        "אימות סיסמה חדשה", validators=[DataRequired(message="נא להזין אימות סיסמה")]
    )
    submit = SubmitField("עדכון סיסמה")

    def validate_new_password(self, field):
        value = field.data or ""
        errors = []
        if len(value) < 10:
            errors.append("הסיסמה חייבת להכיל לפחות 10 תווים")
        if not re.search(r"[A-Z]", value):
            errors.append("הסיסמה חייבת להכיל אות גדולה")
        if not re.search(r"[a-z]", value):
            errors.append("הסיסמה חייבת להכיל אות קטנה")
        if not re.search(r"\\d", value):
            errors.append("הסיסמה חייבת להכיל ספרה")
        if not re.search(r"[^A-Za-z0-9]", value):
            errors.append("הסיסמה חייבת להכיל תו מיוחד")
        if value.lower() in PASSWORD_DENYLIST:
            errors.append("הסיסמה שנבחרה נפוצה מדי")
        if errors:
            raise ValidationError("; ".join(errors))

    def validate_confirm_new_password(self, field):
        if field.data != self.new_password.data:
            raise ValidationError("אימות הסיסמה אינו תואם")


class ProfileImageForm(FlaskForm):
    image = FileField("תמונת פרופיל")
    submit = SubmitField("שמור תמונה")


class AdminMessageForm(FlaskForm):
    title = StringField(
        "כותרת",
        validators=[DataRequired(message="נא להזין כותרת"), Length(min=2, max=120)],
    )
    body = TextAreaField(
        "תוכן ההודעה",
        validators=[DataRequired(message="נא להזין הודעה"), Length(min=5, max=2000)],
    )
    submit = SubmitField("שליחת הודעה")


class MarkAllReadForm(FlaskForm):
    submit = SubmitField("סמן הכל כנקרא")
