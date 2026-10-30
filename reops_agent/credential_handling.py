"""持久化前过滤已知环境凭据和敏感字段，不返回凭据清单。"""

import os
import re


def redact_persistent(value):
    sensitive_names = {"api_key", "access_token", "refresh_token", "password",
                       "authorization", "credential", "secret", "token"}
    secrets = [content for name, content in os.environ.items()
               if content and (name.endswith(("_API_KEY", "_TOKEN", "_PASSWORD", "_SECRET"))
                               or name in {"NEXENT_API_BASE", "NEXENT_MODEL_ID"})]
    def clean(item):
        if isinstance(item, dict):
            return {key: "[REDACTED]" if key.lower() in sensitive_names else clean(content)
                    for key, content in item.items()}
        if isinstance(item, list):
            return [clean(content) for content in item]
        if isinstance(item, str):
            for secret in sorted(secrets, key=len, reverse=True):
                item = item.replace(secret, "[REDACTED]")
            return re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,})\b",
                          "[REDACTED]", item)
        return item
    return clean(value)
