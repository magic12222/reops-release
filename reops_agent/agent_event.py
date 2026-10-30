"""把一次完整恢复闭环汇总为统一 AgentEvent。"""

from .b_clock import utc_now
from typing import Any
from uuid import uuid4

from .contracts import validate


def build_agent_event(
    observation: dict[str, Any],
    diagnosis: dict[str, Any],
    action: dict[str, Any],
    execution_result: dict[str, Any],
    verification_result: dict[str, Any],
    recovered: bool,
) -> dict[str, Any]:
    """生成可审计、可直接写入 Recovery Memory 的闭环事件。"""
    if diagnosis["failure_detected"]:
        status = "success" if recovered else "failed"
        message = "故障恢复闭环完成，系统已恢复" if recovered else "故障恢复闭环完成，系统仍未恢复"
    else:
        status = "skipped"
        message = "未检测到故障，恢复动作已跳过"

    event = {
        "schema_version": observation["schema_version"],
        "event_id": f"event-{uuid4()}",
        "incident_id": observation["incident_id"],
        "trace_id": observation["trace_id"],
        "parent_event_id": None,
        "timestamp": utc_now().isoformat(),
        "stage": "experience_update",
        "status": status,
        "component": diagnosis["failed_component"],
        "step": diagnosis["failed_step"],
        "message": message,
        "confidence": diagnosis["confidence"],
        "observation_id": observation["observation_id"],
        "diagnosis_id": diagnosis["diagnosis_id"],
        "action_id": action["action_id"],
        "result_id": execution_result["result_id"],
        "data": {
            "observation": observation,
            "diagnosis": diagnosis,
            "recovery_action": action,
            "execution_result": execution_result,
            "verification_result": verification_result,
            "recovered": recovered,
        },
    }
    if "case_id" in observation:
        event["case_id"] = observation["case_id"]
    validate("agent_event", event)
    return event
