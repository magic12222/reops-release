"""直接读取 shared 契约，避免维护第二套 schema。"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=None)
def validator(name: str) -> Draft202012Validator:
    schema = json.loads(
        (PROJECT_ROOT / "shared" / f"{name}.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate(name: str, document: dict[str, Any]) -> None:
    # Python NaN可能绕过JSON Schema的minimum/maximum；JSON本身不允许它。
    # 同时检查扩展字段，避免隐藏数值在评分/序列化阶段才被发现。
    try:
        json.dumps(document,allow_nan=False)
    except (TypeError,ValueError):
        raise ValidationError('contract_document_not_finite_json') from None
    validator(name).validate(document)
