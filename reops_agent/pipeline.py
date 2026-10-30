"""B 的单一公开入口。"""

from typing import Any

from .diagnosis import build_diagnosis
from .detector import detect
from .observer import observe


def diagnose(observation: dict[str, Any]) -> dict[str, Any]:
    snapshot = observe(observation)
    detection = detect(snapshot)
    return build_diagnosis(snapshot, detection)
