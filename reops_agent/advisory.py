"""共享的有界 RCA → Planner → Safety 诊断流程；无执行和持久化副作用。"""

from copy import deepcopy
import json
import math
import re

from .contracts import validate
from .credential_handling import redact_persistent
from .pipeline import diagnose
from .planner import plan_recovery
from .rca import RCAAgent
from .safety import check_action

PAIRS = {("restart_service", "web"), ("restart_service", "postgres")}


def _contradictory_metric_evidence(evidence, observation):
    for text in evidence:
        for name, value in re.findall(r"\b(api|postgres|redis)_up\s*(?:=|:)\s*([01])\b", text):
            if int(value) != observation["metrics"].get(name + "_up"):
                return True
    return False


def structured_observation(observation):
    """正向字段选择：无自由日志、headers、用户路径、Docker 元数据或环境。"""
    validate("observation", observation)
    value = {key: deepcopy(observation[key]) for key in (
        "schema_version", "observation_id", "incident_id", "trace_id", "timestamp")}
    if "case_id" in observation:
        value["case_id"] = deepcopy(observation["case_id"])
    if observation.get("observation_conflicts"):
        # 冲突原件留在本机；有界状态继续阻断模型建议/恢复与 Verify。
        value["observation_conflicts"] = ["conflicting_observation_reobserve_required"]
    value.update(system={"name": "reops-lab", "environment": "docker-local-test"},
                 services={}, metrics={}, logs=[])
    messages = {"stopped", "health probe healthy", "health probe unhealthy",
                "health probe starting", "health probe None"}
    for name in ("api", "postgres", "redis"):
        if name in observation["services"]:
            service = observation["services"][name]
            value["services"][name] = {"status": service["status"],
                "message": service.get("message") if service.get("message") in messages else None}
        up = observation["metrics"].get(name + "_up")
        if type(up) in (int, float) and up in (0, 1):
            value["metrics"][name + "_up"] = up
    request = observation["request"]
    latency = request.get("latency_ms")
    value["request"] = {
        "method": "GET" if request.get("method") == "GET" else None,
        "endpoint": "/users" if request.get("endpoint") == "/users" else None,
        "status_code": request.get("status_code"),
        "latency_ms": latency if type(latency) in (int, float) and math.isfinite(latency) else None}
    validate("observation", value)
    return value


class BoundedProvider:
    """只交付有界且去敏的结构化状态；历史自由文本不离开本机。"""

    def __init__(self, provider):
        self.provider = provider
        self.calls = 0
        self.last_input = None

    def _measurement_finished(self, result):
        callback = getattr(type(self.provider), "_measurement_finished", None)
        if callable(callback):
            callback(self.provider, result)

    def complete(self, request, *, timeout_seconds):
        # RCAAgent 的输入源是上方经过白名单的正式 Observation。
        diagnosis = request["rule_based_diagnosis"]
        data = {key: request[key] for key in ("service_status", "metrics", "health_check")}
        data["relevant_logs"] = []
        data["rule_based_diagnosis"] = {key: diagnosis[key] for key in (
            "failure_detected", "failed_component", "failure_type", "root_cause", "evidence", "confidence")}
        data["recovery_evidence"] = []
        for item in request["recovery_evidence"][:3]:
            pair = (item.get("action"), item.get("target"))
            if pair in PAIRS:
                data["recovery_evidence"].append({"action": pair[0], "target": pair[1],
                    "recovery_executed": item.get("executed_action") is not None,
                    "recovered": item.get("recovered") is True})
        data = redact_persistent(data)
        if len(json.dumps(data, ensure_ascii=False)) > 6000:
            raise ValueError("model_input_too_large")
        self.last_input = deepcopy(data)
        self.calls += 1
        raw = self.provider.complete(data, timeout_seconds=timeout_seconds)
        if not isinstance(raw, str) or len(raw) > 16000:
            raise ValueError("model_output_too_large")
        return redact_persistent(raw)


def diagnose_advisory(observation, provider, *, memory=None, timeout=30):
    observation = structured_observation(observation)
    diagnosis = diagnose(observation)
    history = memory.retrieve(diagnosis["failure_type"], diagnosis["failed_component"], limit=3) if memory else []
    bounded = BoundedProvider(provider)
    rca = RCAAgent(bounded, timeout_seconds=timeout).analyze(observation, diagnosis, history)
    reason = rca["fallback_reason"]
    result = rca["result"]
    suggestion = result["suggested_action"]
    pair = (suggestion["action"], suggestion["target"])
    component = "api" if result["affected_component"] == "web" else result["affected_component"]
    target_component = "api" if pair[1] == "web" else pair[1]
    if reason is None:
        if pair not in PAIRS | {("no_action", None)}:
            reason = "suggestion_not_whitelisted"
        elif any(len(text) > 300 for text in result["evidence"]) or len(result["evidence"]) > 8:
            reason = "evidence_not_bounded"
        elif pair in PAIRS and (result["confidence"] < 0.7 or not result["suspected_root_cause"]
                or not any(len(text.strip()) >= 8 for text in result["evidence"])):
            reason = "insufficient_confidence_or_evidence"
        elif pair in PAIRS and (not diagnosis["failure_detected"] or component != target_component
                or observation["services"].get(component, {}).get("status") not in {"unhealthy", "degraded"}):
            reason = "recommendation_not_supported_by_observation"
        elif pair in PAIRS and _contradictory_metric_evidence(result["evidence"], observation):
            reason = "evidence_contradicts_observation"
    action = plan_recovery(diagnosis, observation=observation,
        rca_result=result if reason is None else None,
        failed_actions=PAIRS if reason is not None or pair == ("no_action", None) else set())
    planner_rca = action["decision_basis"].get("rca", {})
    if reason is None and pair in PAIRS and not planner_rca.get("applied"):
        reason = "planner_rejected_suggestion"
        action = plan_recovery(diagnosis, observation=observation, failed_actions=PAIRS)
    safety = check_action(action, observation)
    would_execute = reason is None and safety["allowed"] and action["action"] != "no_action"
    return {"observation": observation, "diagnosis": diagnosis, "rca": rca,
            "model_input": bounded.last_input, "model_calls": bounded.calls,
            "recovery_action": action, "safety": safety, "rejection_reason": reason,
            "would_execute": would_execute,
            "diagnosis_validated": reason is None and safety["allowed"]}
