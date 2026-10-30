"""Observation 输入边界：校验并隔离调用方数据。"""

from copy import deepcopy
from typing import Any

from .contracts import validate


def observe(observation: dict[str, Any]) -> dict[str, Any]:
    validate("observation", observation)
    return deepcopy(observation)
