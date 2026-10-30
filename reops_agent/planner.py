"""基于 Diagnosis 生成受 shared 契约约束的最小恢复决策。"""

from .b_clock import utc_now
from typing import Any
from uuid import uuid4

from .contracts import validate
from .rca import validate_rca_result


def plan_recovery(
    diagnosis: dict[str, Any],
    *,
    observation: dict[str, Any] | None = None,
    history_evidence: list[dict[str, Any]] | None = None,
    rca_result: dict[str, Any] | None = None,
    failed_actions: set[tuple[str, str | None]] | None = None,
) -> dict[str, Any]:
    """用白名单规则生成 RecoveryAction，并把历史作为附加决策证据。"""
    validate("diagnosis", diagnosis)
    history_evidence = list(history_evidence or [])
    failed_actions = set(failed_actions or ())
    failed = diagnosis["failure_detected"]
    component = diagnosis["failed_component"]
    failure_type = diagnosis["failure_type"]

    conflicted = (diagnosis["root_cause"] == "observation_conflict_reobserve_required"
                  or observation is not None and bool(observation.get("observation_conflicts")))
    if conflicted:
        action, target = "no_action", None
        reason = "观测证据矛盾，需重新观测，不据此生成恢复动作"
        expected_success, estimated_cost, risk = 0.0, 0.0, 0.0
    elif not failed:
        action = "no_action"
        target = None
        reason = "未检测到当前运行故障，无需执行恢复动作"
        expected_success, estimated_cost, risk = 1.0, 0.0, 0.0
    elif component == "postgres" and diagnosis["root_cause"] == "postgres_service_down":
        action = "restart_service"
        target = "postgres"
        reason = "PostgreSQL 服务已停止，按白名单规则重启 postgres"
        expected_success, estimated_cost, risk = 0.9, 0.2, 0.2
    elif component in {"api", "web"} and (failure_type == "health_check_failure"
            or diagnosis["root_cause"] in {"api_service_down", "web_service_down"}):
        action = "restart_service"
        target = "web"
        reason = "Web 已停止或健康检查失败，按白名单规则重启 web"
        expected_success, estimated_cost, risk = 0.8, 0.2, 0.2
    else:
        action = "no_action"
        target = None
        reason = "当前诊断不匹配已批准的最小恢复规则，不自动执行"
        expected_success, estimated_cost, risk = 0.0, 0.0, 0.0

    result = {
        "schema_version": diagnosis["schema_version"],
        "action_id": f"action-{uuid4()}",
        "incident_id": diagnosis["incident_id"],
        "trace_id": diagnosis["trace_id"],
        "diagnosis_id": diagnosis["diagnosis_id"],
        "timestamp": utc_now().isoformat(),
        "action": action,
        "target": target,
        "reason": reason,
        "expected_success": expected_success,
        "estimated_cost": estimated_cost,
        "risk": risk,
        "requires_approval": False,
        "parameters": {},
        # RecoveryAction 只由 planner 创建；RCA 建议在下方重新校验后参与决策。
        "decision_basis": {
            "strategy": "rule_based_with_recovery_memory",
            "history_match": {
                "failure_type": failure_type,
                "location": component,
                "total": len(history_evidence),
                "succeeded": sum(item["recovered"] is True for item in history_evidence),
                "failed": sum(item["recovered"] is False for item in history_evidence),
                "evidence": history_evidence,
            },
        },
    }
    if "case_id" in diagnosis:
        result["case_id"] = diagnosis["case_id"]
    # 只有当前故障的精确成功案例可改变决策，相似案例仅供 RCA 参考。
    for item in history_evidence:
        target_component = "api" if item.get("target") == "web" else item.get("target")
        pair = (item.get("action"), item.get("target"))
        if (failed and item.get("recovered") is True
                and item.get("verification_status") == "recovered"
                and item.get("execution_status") == "succeeded"
                and item.get("failure_type") == failure_type
                and item.get("location") == component
                and target_component in {component, "api" if component == "web" else component}
                and pair in {("restart_service", "postgres"), ("restart_service", "web")}
                and pair not in failed_actions and action != "no_action"):
            result.update(action=pair[0], target=pair[1], reason="复用当前故障匹配且验证成功的白名单历史动作")
            result["decision_basis"]["strategy"] = "successful_recovery_memory"
            result["decision_basis"]["reused_event_id"] = item["event_id"]
            break
    if rca_result is not None:
        validate_rca_result(rca_result)
        suggestion = rca_result["suggested_action"]
        allowed = (
            suggestion["action"] == "no_action" and suggestion["target"] is None
        ) or (
            suggestion["action"] == "restart_service"
            and suggestion["target"] in {"postgres", "web"}
        )
        rule_decision = {"action": action, "target": target}
        affected_target = (
            "web" if rca_result["affected_component"] == "api"
            else rca_result["affected_component"]
        )
        applied = (
            failed and not conflicted and allowed and suggestion["action"] == "restart_service"
            and suggestion["target"] == affected_target
            and rca_result["suspected_root_cause"] is not None
            and (suggestion["action"], suggestion["target"]) not in failed_actions
            and _supported_component(diagnosis, observation, affected_target)
        )
        if applied:
            result.update(
                action=suggestion["action"], target=suggestion["target"],
                reason="planner 校验 RCA 根因与目标一致，采用白名单恢复建议",
                expected_success=min(0.9, rca_result["confidence"]),
                estimated_cost=0.2, risk=0.2,
            )
            result["decision_basis"]["strategy"] = "rca_assisted_with_recovery_memory"
        result["decision_basis"]["rca"] = {
            "result": rca_result,
            "suggestion_status": "allowed_advice" if allowed else "rejected_not_whitelisted",
            "matches_rule_decision": suggestion == {"action": action, "target": target},
            "rule_decision": rule_decision,
            "applied": applied,
            "observation_supported": _supported_component(diagnosis, observation, affected_target),
            "policy": "planner_validated_root_cause_and_whitelist",
        }
    if (result["action"], result["target"]) in failed_actions:
        # RCA 重复失败建议时，可退回尚未尝试过的确定性规则动作。
        if action != "no_action" and (action, target) not in failed_actions:
            result.update(action=action, target=target, reason="RCA 动作已失败，选择尚未尝试的规则候选")
        else:
            result.update(action="no_action", target=None,
                          reason="没有新的安全恢复候选，停止重复失败动作",
                          expected_success=0.0, estimated_cost=0.0, risk=0.0)
    result["decision_basis"]["failed_actions"] = [
        {"action": action_name, "target": target_name}
        for action_name, target_name in sorted(failed_actions)
    ]
    validate("recovery_action", result)
    return result


def _supported_component(diagnosis, observation, target):
    component = "api" if target == "web" else target
    diagnosed = diagnosis["failed_component"]
    if component in {diagnosed, "api" if diagnosed == "web" else diagnosed}:
        return True
    # 支持 Web 故障指向数据库依赖的既有场景，但拒绝无观测依据的跨组件建议。
    evidence = list(diagnosis["evidence"])
    if observation is not None:
        service = observation["services"].get(component, {})
        if service.get("status") in {"stopped", "unhealthy"}:
            return True
        evidence += [item["message"] for item in observation["logs"]]
    return component == "postgres" and any(
        "postgres" in item.lower() and "connection refused" in item.lower()
        for item in evidence)
