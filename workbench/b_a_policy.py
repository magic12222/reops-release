"""Explicit A workbench start profile; default restart Safety remains unchanged."""
from copy import deepcopy

from reops_agent.contracts import validate
from reops_agent.strategies import _action, _commands, _matching_history, _stopped

TARGET = "reops-lab-api"


def check_a_start(action, observation):
    validate("recovery_action", action)
    validate("observation", observation)
    reason = "allowed_a_workbench_stopped_start"
    if (action["action"], action["target"]) != ("start_service", "web"):
        reason = "a_start_only"
    elif _commands(action) or action["parameters"] or action["requires_approval"] or action["risk"] > .2:
        reason = "a_start_policy_rejected"
    elif any(action[key] != observation[key] for key in ("incident_id", "trace_id")):
        reason = "correlation_mismatch"
    elif (observation["system"].get("target_id") != TARGET
            or observation["system"].get("name") != "reops-lab"
            or observation["system"].get("environment") != "docker-local"):
        reason = "a_target_binding_missing"
    elif (observation.get("observation_conflicts") or observation.get("sampling_error")
            or not _stopped("api", observation)
            or observation.get("target_health") != "unhealthy"
            or observation["request"].get("method") != "GET"
            or observation["request"].get("endpoint") != "/users"
            or observation["request"].get("status_code") is not None
            or observation["request"].get("business_passed") is not None):
        reason = "a_start_requires_current_stopped_evidence"
    # Dependencies are not supplied by A. They are never fabricated or marked healthy.
    # A's explicitly bound stopped-container policy is the authority for this profile.
    return {"allowed": reason == "allowed_a_workbench_stopped_start", "reason": reason,
            "action": action["action"], "target": action["target"]}


def plan_a_start(diagnosis, observation, history=(), *, model_suggestion=None):
    action = _action(diagnosis, "start_service", "web", {}, .85, "a_stopped_web_start")
    adopted = [item["event_id"] for item in history if item.get("recovered") is True
        and _matching_history(item, diagnosis, {}, ("start_service", "web", {}))]
    action.update(reason="A fixed stopped-container candidate; only start_service(web) is executable")
    action["decision_basis"].update(strategy="a_workbench_scoped_start", offline_only=False,
        target_id=TARGET, history_event_ids=adopted, model_suggested_action=deepcopy(model_suggestion),
        model_action_applied=False,
        selection_reason="explicit_A_start_scope_and_current_stopped_evidence")
    validate("recovery_action", action)
    return action


def verify_a_business(observation):
    from reops_agent.verification import verify
    diagnosis, result, healthy = verify(observation)
    healthy = (healthy and observation["system"].get("target_id") == TARGET
        and observation.get("sampling_error") is None and observation.get("target_health") == "healthy"
        and observation["services"].get("business", {}).get("status") == "healthy"
        and observation["request"].get("business_passed") is True
        and observation["request"].get("status_code") == 200
        and type(observation["metrics"].get("api_up")) is int and observation["metrics"]["api_up"] == 1)
    result["status"] = "recovered" if healthy else "not_recovered"
    result["business_request_passed"] = observation["request"].get("business_passed") is True
    result["evidence"].append("A /users payload check=" + str(observation["request"].get("business_passed")))
    return diagnosis, result, healthy
