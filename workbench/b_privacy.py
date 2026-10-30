"""B persistence boundary: structured input first, then credential redaction."""
import json
import os
import re

PRIVATE = re.compile(
    r"api[-_]?key|authorization|proxy[-_]?authorization|cookie|session|(?:^|_)token$|password|"
    r"credential|secret|owner_user_id|project_db_id|project_id|email|phone", re.I)


def redact(value):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if PRIVATE.search(key) else redact(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    text = value
    for name, secret in sorted(os.environ.items(), key=lambda pair: len(pair[1]), reverse=True):
        if secret and name.upper().endswith(("_API_KEY", "_TOKEN", "_PASSWORD", "_SECRET")):
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,})\b", "[REDACTED]", text)
    # Parse JSON before treating it as prose, including JSON embedded in messages.
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        return json.dumps(redact(parsed), ensure_ascii=False, allow_nan=False)
    text = re.sub(r"(?i)\bBearer\s+[^\s\"',;]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r'''(?ix)(["']?(?:api[_-]?key|authorization|cookie|session(?:[_-]?(?:id|token))?|password|access_token|refresh_token|secret|token)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}]+)''',
        r'\1"[REDACTED]"', text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", text)
    return text


def dumps(value):
    return json.dumps(redact(value), ensure_ascii=False, allow_nan=False)
