import json
from datetime import datetime

from models import UserScholarship, db
from notion_service import fetch_notion_pages_raw


KEYWORD_MAP = {
    "מכינה": ["מכינה"],
    "תואר ראשון": ["תואר ראשון", "בוגר", "undergraduate"],
    "תואר שני": ["תואר שני", "תואר מתקדם", "graduate", "master"],
    "הנדסאי": ["הנדסאי"],
    "הנדסה / מדעים מדויקים": ["הנדסה", "מדעים מדויקים", "הנדסי", "פיזיקה", "כימיה", "מתמטיקה"],
    "מדעי החברה / כלכלה / ניהול": ["מדעי החברה", "כלכלה", "ניהול", "מנהל עסקים"],
    "חינוך / מדעי הרוח": ["חינוך", "מדעי הרוח", "היסטוריה", "ספרות"],
    "רפואה / מקצועות הבריאות": ["רפואה", "סיעוד", "בריאות", "פרא רפואי"],
    "לפני שירות": ["לפני שירות"],
    "במהלך שירות": ["במהלך שירות", "חיילים", "בצה"],
    "חייל משוחרר": ["משוחרר", "חייל משוחרר"],
    "שירות לאומי / אזרחי": ["שירות לאומי", "אזרחי"],
    "תושב פריפריה": ["פריפריה"],
    "עולה חדש": ["עולה חדש"],
    "יוצא אתיופיה": ["אתיופ"],
    "חרדי": ["חרדי"],
    "ערבי / דרוזי": ["ערבי", "דרוזי"],
    "נכות מוכרת": ["נכות", "מוגבל"],
}


def _contains_any(blob, keywords):
    return any(keyword.lower() in blob for keyword in keywords)


def _score_scholarship(questionnaire, blob):
    score = 0
    reasons = []

    study_status = questionnaire.study_status
    study_field = questionnaire.study_field
    military_status = questionnaire.military_status
    duration_pref = questionnaire.scholarship_duration_preference

    if study_status in KEYWORD_MAP and _contains_any(blob, KEYWORD_MAP[study_status]):
        score += 2
        reasons.append("התאמה לסטטוס הלימודים שלך")

    if study_field in KEYWORD_MAP and _contains_any(blob, KEYWORD_MAP[study_field]):
        score += 2
        reasons.append("התאמה לתחום הלימודים שלך")

    if military_status in KEYWORD_MAP and _contains_any(blob, KEYWORD_MAP[military_status]):
        score += 2
        reasons.append("התאמה לסטטוס השירות שלך")

    populations = json.loads(questionnaire.populations)
    population_matches = 0
    for population in populations:
        keywords = KEYWORD_MAP.get(population, [])
        if keywords and _contains_any(blob, keywords):
            population_matches += 1
            score += 1
    if population_matches:
        reasons.append("מתאים לאוכלוסיות שסימנת")

    if questionnaire.volunteer_willingness == "לא" and "התנדבות" in blob:
        score -= 2
        reasons.append("דורש התנדבות בזמן שבחרת שלא להתנדב")

    if duration_pref == "חד-פעמית" and _contains_any(blob, ["חד פעמי", "חד-פעמי", "מענק", "one-time"]):
        score += 2
        reasons.append("מתאים להעדפת מלגה חד-פעמית")
    elif duration_pref == "שנתית" and _contains_any(blob, ["שנתי", "annual", "מתמשכת"]):
        score += 2
        reasons.append("מתאים להעדפת מלגה שנתית/מתמשכת")
    elif duration_pref == "רב-שנתית" and _contains_any(blob, ["רב שנתי", "רב-שנתי", "multi-year"]):
        score += 2
        reasons.append("מתאים להעדפת מלגה רב-שנתית")

    if not reasons:
        reasons.append("התאמה כללית לפי הנתונים שמילאת")

    return score, reasons


def compute_matches(questionnaire, limit=15, threshold=3):
    pages, error = fetch_notion_pages_raw()
    if error:
        return [], error

    scored = []
    for page in pages:
        blob = (page.get("blob") or "").lower()
        score, reasons = _score_scholarship(questionnaire, blob)
        scored.append(
            {
                "key": page.get("id"),
                "title": page.get("title"),
                "link": page.get("url"),
                "score": score,
                "reasons": reasons,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    filtered = [item for item in scored if item["score"] >= threshold]
    if len(filtered) < 5:
        filtered = scored[:limit]
    else:
        filtered = filtered[:limit]

    return filtered, None


def upsert_user_scholarships(user_id, matches):
    now = datetime.utcnow()
    for match in matches:
        existing = UserScholarship.query.filter_by(
            user_id=user_id, scholarship_key=match["key"]
        ).first()
        if existing:
            existing.match_score = match["score"]
            existing.match_reasons = json.dumps(match["reasons"], ensure_ascii=False)
            existing.scholarship_title = match["title"]
            existing.scholarship_link = match["link"]
            existing.updated_at = now
        else:
            db.session.add(
                UserScholarship(
                    user_id=user_id,
                    scholarship_key=match["key"],
                    scholarship_title=match["title"],
                    scholarship_link=match["link"],
                    match_score=match["score"],
                    match_reasons=json.dumps(match["reasons"], ensure_ascii=False),
                    status="מעוניין",
                    alerts_enabled=False,
                    created_at=now,
                    updated_at=now,
                )
            )
    db.session.commit()
