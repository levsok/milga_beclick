import os

import requests

from env_utils import load_environment


NOTION_VERSION = "2022-06-28"

REQUIREMENT_FIELD_NAMES = {
    "volunteering": {
        "RequiresVolunteering",
        "VolunteeringRequired",
        "Requires Volunteering",
        "התנדבות נדרשת",
    },
    "military": {
        "RequiresMilitaryService",
        "MilitaryServiceRequired",
        "Requires Military Service",
        "שירות צבאי נדרש",
    },
}


def _join_plain_text(items):
    return "".join(item.get("plain_text", "") for item in items or [])


def _extract_property_value(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type == "title":
        return _join_plain_text(prop.get("title"))
    if prop_type == "rich_text":
        return _join_plain_text(prop.get("rich_text"))
    if prop_type == "select":
        select = prop.get("select") or {}
        return select.get("name", "")
    if prop_type == "multi_select":
        return [item.get("name", "") for item in prop.get("multi_select") or []]
    if prop_type == "date":
        date = prop.get("date") or {}
        start = date.get("start")
        end = date.get("end")
        if start and end:
            return f"{start} - {end}"
        return start or ""
    if prop_type == "url":
        return prop.get("url") or ""
    if prop_type == "email":
        return prop.get("email") or ""
    if prop_type == "phone_number":
        return prop.get("phone_number") or ""
    if prop_type == "number":
        value = prop.get("number")
        return "" if value is None else str(value)
    if prop_type == "checkbox":
        return "כן" if prop.get("checkbox") else "לא"
    if prop_type == "people":
        return ", ".join(person.get("name", "") for person in prop.get("people") or [])
    if prop_type == "files":
        files = []
        for file_item in prop.get("files") or []:
            name = file_item.get("name")
            file_info = file_item.get("file") or file_item.get("external") or {}
            url = file_info.get("url")
            files.append(name or url or "")
        return ", ".join(item for item in files if item)
    if prop_type == "relation":
        relations = prop.get("relation") or []
        return f"{len(relations)} פריטים"
    if prop_type == "formula":
        formula = prop.get("formula") or {}
        return str(formula.get(formula.get("type"), "")) if formula else ""
    if prop_type == "rollup":
        rollup = prop.get("rollup") or {}
        rollup_type = rollup.get("type")
        if rollup_type == "array":
            return str(len(rollup.get("array") or []))
        return str(rollup.get(rollup_type, "")) if rollup_type else ""
    return "לא זמין"


def _property_to_text(prop):
    value = _extract_property_value(prop)
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    return str(value) if value is not None else ""


def _extract_requirement(props, field_names):
    for name in field_names:
        if name not in props:
            continue
        prop = props[name]
        prop_type = prop.get("type")
        if prop_type == "checkbox":
            return prop.get("checkbox")
        if prop_type == "select":
            select = prop.get("select") or {}
            value = select.get("name")
            if value in ("כן", "נדרש", "חובה"):
                return True
            if value in ("לא", "אופציונלי"):
                return False
        if prop_type == "multi_select":
            values = [item.get("name") for item in prop.get("multi_select") or []]
            if any(value in ("כן", "נדרש", "חובה") for value in values):
                return True
            if any(value in ("לא", "אופציונלי") for value in values):
                return False
        return None
    return None


def _extract_requirements(props):
    return {
        "volunteering": _extract_requirement(props, REQUIREMENT_FIELD_NAMES["volunteering"]),
        "military": _extract_requirement(props, REQUIREMENT_FIELD_NAMES["military"]),
    }


def _find_best_url(props):
    for prop in props.values():
        if prop.get("type") == "url":
            url_value = prop.get("url") or ""
            if url_value:
                return url_value
        if prop.get("type") == "files":
            for file_item in prop.get("files") or []:
                file_info = file_item.get("file") or file_item.get("external") or {}
                url_value = file_info.get("url")
                if url_value:
                    return url_value
    return ""


def fetch_notion_pages_raw():
    load_environment()
    token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    print(
        f"[debug] NOTION_TOKEN loaded: {bool(token)}, "
        f"NOTION_DATABASE_ID present: {bool(database_id)}"
    )
    if not token or not database_id:
        return [], "חסרים פרטי חיבור למערכת המלגות."

    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "page_size": 100,
    }
    pages = []
    next_cursor = None
    while True:
        if next_cursor:
            payload["start_cursor"] = next_cursor
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
        except requests.RequestException as exc:
            print(f"[debug] Notion request error: {exc}")
            return [], "לא הצלחנו לטעון את המלגות כרגע."
        print(f"[debug] Notion response status: {response.status_code}")
        if response.status_code != 200:
            body_preview = response.text[:200]
            print(f"[debug] Notion response body (first 200 chars): {body_preview}")
            return [], "לא הצלחנו לטעון את המלגות כרגע."
        data = response.json()
        for row in data.get("results", []):
            props = row.get("properties", {})
            text_parts = []
            title_value = ""
            for prop in props.values():
                if prop.get("type") == "title" and not title_value:
                    title_value = _property_to_text(prop)
                text_parts.append(_property_to_text(prop))
            pages.append(
                {
                    "id": row.get("id"),
                    "title": title_value or "מלגה ללא כותרת",
                    "url": _find_best_url(props),
                    "blob": " ".join(part for part in text_parts if part),
                    "requirements": _extract_requirements(props),
                }
            )
        if not data.get("has_more"):
            break
        next_cursor = data.get("next_cursor")
    return pages, None


def fetch_scholarships():
    load_environment()
    token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    print(
        f"[debug] NOTION_TOKEN loaded: {bool(token)}, "
        f"NOTION_DATABASE_ID present: {bool(database_id)}"
    )
    if not token or not database_id:
        return [], "חסרים פרטי חיבור למערכת המלגות."

    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    scholarships = []
    payload = {
        "page_size": 100,
    }

    next_cursor = None
    while True:
        if next_cursor:
            payload["start_cursor"] = next_cursor
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
        except requests.RequestException as exc:
            print(f"[debug] Notion request error: {exc}")
            return [], "לא הצלחנו לטעון את המלגות כרגע."
        print(f"[debug] Notion response status: {response.status_code}")
        if response.status_code != 200:
            body_preview = response.text[:200]
            print(f"[debug] Notion response body (first 200 chars): {body_preview}")
            return [], "לא הצלחנו לטעון את המלגות כרגע."
        data = response.json()
        for row in data.get("results", []):
            props = row.get("properties", {})
            title_value = ""
            url_value = ""
            fields = []
            tags = []
            for name, prop in props.items():
                prop_type = prop.get("type")
                value = _extract_property_value(prop)
                if not title_value and prop_type == "title":
                    title_value = value
                    continue
                if prop_type == "url" and value and not url_value:
                    url_value = value
                if prop_type == "multi_select":
                    if isinstance(value, list):
                        tags.extend([tag for tag in value if tag])
                    continue
                if value in ("", None):
                    continue
                fields.append({"name": name, "value": value})

            scholarships.append(
                {
                    "id": row.get("id"),
                    "title": title_value or "מלגה ללא כותרת",
                    "url": url_value,
                    "tags": tags,
                    "fields": fields,
                    "requirements": _extract_requirements(props),
                }
            )
        if not data.get("has_more"):
            break
        next_cursor = data.get("next_cursor")
    return scholarships, None
