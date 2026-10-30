"""执行前的独立安全门；模型和记忆均不能扩大白名单。"""

from .contracts import validate
from .pipeline import diagnose


def check_action(action, observation, failed_actions=(), *, attempt_number=1, retry_limit=5):
    validate("recovery_action", action)
    validate("observation", observation)
    pair = (action["action"], action["target"])
    component = "api" if action["target"] == "web" and "api" in observation["services"] else action["target"]
    if (type(attempt_number) is not int or type(retry_limit) is not int
            or not 1 <= attempt_number <= retry_limit <= 5):
        reason = "retry_limit_exceeded"
    elif pair == ("no_action", None):
        reason = "no_action"
    elif pair not in {("restart_service", "postgres"), ("restart_service", "web")}:
        reason = "not_whitelisted"
    elif action["requires_approval"] or action["risk"] > 0.2 or action["parameters"]:
        reason = "policy_rejected"
    elif component not in observation["services"]:
        reason = "target_absent"
    elif any(action[key] != observation[key] for key in ("incident_id", "trace_id")):
        reason = "correlation_mismatch"
    elif observation.get("observation_conflicts"):
        reason = "observation_conflict"
    elif not diagnose(observation)["failure_detected"]:
        reason = "no_current_failure"
    elif observation["services"][component]["status"] not in {"unhealthy", "degraded"}:
        reason = "target_failure_evidence_missing"
    elif pair in failed_actions:
        reason = "previously_failed_action"
    else:
        reason = "allowed"
    return {"allowed": reason in {"allowed", "no_action"}, "reason": reason,
            "action": action["action"], "target": action["target"]}
