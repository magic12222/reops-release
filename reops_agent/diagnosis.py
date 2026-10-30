"""将检测结果转换成共享 Diagnosis，并保留关联 ID。"""

from .b_clock import utc_now
from typing import Any
from uuid import uuid4

from .contracts import validate
from .detector import Detection


def build_diagnosis(observation: dict[str, Any], detection: Detection) -> dict[str, Any]:
    result = {
        "schema_version": observation["schema_version"],
        "diagnosis_id": f"diag-{uuid4()}",
        "incident_id": observation["incident_id"],
        "trace_id": observation["trace_id"],
        "observation_id": observation["observation_id"],
        "timestamp": utc_now().isoformat(),
        "failure_detected": detection.failed,
        "failed_component": detection.component,
        "failed_step": detection.step,
        "failure_type": detection.failure_type,
        "root_cause": detection.root_cause,
        "evidence": list(detection.evidence),
        "confidence": detection.confidence,
        # 契约允许附加属性；别名只由 B 输出，不改 shared。
        "failed": detection.failed,
        "failure_step": detection.step,
        "location": detection.component,
    }
    if "case_id" in observation:
        result["case_id"] = observation["case_id"]
    validate("diagnosis", result)
    return result
