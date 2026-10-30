"""Observation 到 Verify 的最小恢复闭环编排。"""

from .b_clock import utc_now
from dataclasses import replace
from copy import deepcopy
from typing import Any
from uuid import uuid4

from jsonschema.exceptions import ValidationError

from .agent_event import build_agent_event
from .contracts import validate
from .executor import ExecutionOutcome, mock_execute, validate_outcome
from .memory import RecoveryMemory
from .pipeline import diagnose
from .planner import plan_recovery
from .rca import RCAAgent
from .verification import verify, post_observation_error
from .safety import check_action


def _recover_once(
    observation: dict[str, Any],
    *,
    execution_succeeds: bool = True,
    memory: RecoveryMemory | None = None,
    rca_agent: RCAAgent | None = None,
    failed_actions=None,
    attempt_evidence=None,
    executor=None,
    attempt_number=1,
    retry_limit=5,
    offline_strategy=None,
) -> dict[str, Any]:
    """诊断、查询历史、决策、安全执行、验证并沉淀统一事件。"""
    initial_diagnosis = diagnose(observation)
    history_evidence = (
        memory.retrieve(
            initial_diagnosis["failure_type"],
            initial_diagnosis["location"],
        )
        if memory is not None
        else []
    )
    known_events = {item["event_id"] for item in history_evidence}
    history_evidence += [item for item in (attempt_evidence or [])
                         if item["event_id"] not in known_events]
    rca_history = history_evidence
    if offline_strategy is not None:
        rca_history = deepcopy(history_evidence)
        for item in rca_history:
            item.get('observation', {}).pop('offline_effects', None)
    rca = (rca_agent.analyze(observation, initial_diagnosis, rca_history)
           if rca_agent is not None else None)
    if offline_strategy is not None:
        from .strategies import plan_candidates
        action = plan_candidates(initial_diagnosis, observation, history=history_evidence, rca=rca,
            mode=offline_strategy, failed_actions=failed_actions or (), attempt_number=attempt_number,
            retry_limit=retry_limit)
    else:
        action = plan_recovery(initial_diagnosis, history_evidence=history_evidence,
                           observation=observation,
                           rca_result=rca["result"] if rca is not None else None,
                           failed_actions=failed_actions)
    proposed_action = deepcopy(action)
    try:
        policy = check_action
        if offline_strategy is not None:
            from .strategies import check_offline_action
            policy = check_offline_action
        safety = policy(action, observation, failed_actions or (),
                              attempt_number=attempt_number, retry_limit=retry_limit)
    except ValidationError:
        if executor is None:
            raise
        # 实际路径把 schema 拒绝变为可审计事件；不持久化非法命令载荷。
        safety = {"allowed": False, "reason": "schema_rejected", "action": "invalid", "target": None}
        proposed_action = {"action": "invalid", "target": None, "reason": "schema_rejected"}
        action = {"schema_version": initial_diagnosis["schema_version"],
                  "action_id": f"action-{uuid4()}", "incident_id": observation["incident_id"],
                  "trace_id": observation["trace_id"], "diagnosis_id": initial_diagnosis["diagnosis_id"],
                  "timestamp": utc_now().isoformat(), "action": "no_action",
                  "target": None, "parameters": {}, "reason": "schema_rejected",
                  "expected_success": 0.0, "estimated_cost": 0.0, "risk": 0.0,
                  "requires_approval": False, "decision_basis": {"strategy": "schema_rejected"}}
    if not safety["allowed"]:
        action.update(action="no_action", target=None, parameters={}, requires_approval=False,
                      risk=0.0, reason="执行前安全门拒绝恢复建议：" + safety["reason"])
        if offline_strategy is not None:
            action['decision_basis']['selected_strategy'] = 'no_action'
        validate("recovery_action", action)
    if executor is None:
        if offline_strategy is not None:
            from .strategies import simulate_candidate
            outcome = simulate_candidate(action, observation, succeeds=execution_succeeds)
        else:
            outcome = mock_execute(action, observation, succeeds=execution_succeeds)
    elif not safety["allowed"] or action["action"] == "no_action":
        # 实际执行器在拒绝或无动作时完全不调用。
        outcome = ExecutionOutcome("skipped", None, None, None, 0.0, deepcopy(observation))
    else:
        outcome = executor(action, observation, succeeds=execution_succeeds)
    validate_outcome(outcome,action)
    post_error = (post_observation_error(observation,outcome.observation)
                  if action['action'] != 'no_action' else None)
    if post_error:
        # 无效载荷不进入关联Memory；原观测保留原ID，不伪装成新采样。
        outcome = replace(outcome,observation=deepcopy(observation))
    verification_diagnosis, verification, recovered = verify(outcome.observation)
    if post_error:
        recovered=False
        verification['status']='inconclusive'
        verification['evidence'].append(post_error)
    resource_verification = None
    if offline_strategy is not None:
        from .strategies import resource_recovery_check
        resource_verification = resource_recovery_check(observation, outcome.observation)
        if resource_verification['required'] and not resource_verification['passed']:
            recovered = False
            verification['status'] = 'not_recovered'
            verification['evidence'].append('offline resource pressure has not been independently cleared')
    if initial_diagnosis['failure_detected']:
        recovered = recovered and outcome.status == 'succeeded'
        if not recovered and verification['status'] == 'recovered':
            verification['status'] = 'inconclusive'

    result = {
        "schema_version": action["schema_version"],
        "result_id": f"result-{uuid4()}",
        "incident_id": action["incident_id"],
        "trace_id": action["trace_id"],
        "action_id": action["action_id"],
        "timestamp": utc_now().isoformat(),
        "execution_status": outcome.status,
        "exit_code": outcome.exit_code,
        "stdout": outcome.stdout,
        "stderr": outcome.stderr,
        "duration_ms": outcome.duration_ms,
        "post_observation_id": outcome.observation["observation_id"],
        "verification": verification,
        # shared 允许附加字段；便于调用方明确读取最终布尔结果。
        "recovered": recovered,
    }
    if outcome.execution is not None:
        result["executor"] = outcome.execution
    if "case_id" in action:
        result["case_id"] = action["case_id"]
    validate("recovery_result", result)

    agent_event = build_agent_event(
        observation,
        initial_diagnosis,
        action,
        result,
        verification,
        recovered,
    )
    if rca is not None:
        agent_event["data"]["rca"] = rca
        validate("agent_event", agent_event)
    decision_trace = [
        {"stage": "Observation", "data": deepcopy(observation)},
        {"stage": "Failure detected", "data": initial_diagnosis["failure_detected"]},
        {"stage": "Diagnosis", "data": initial_diagnosis},
        {"stage": "RCA evidence", "data": rca["result"]["evidence"] if rca else initial_diagnosis["evidence"]},
        {"stage": "Memory evidence", "data": history_evidence},
        {"stage": "Nexent recommendation", "data": rca},
        {"stage": "Safety decision", "data": {**safety, "planner": action["decision_basis"]}},
        {"stage": "Action", "data": action},
        {"stage": "Execution", "data": result},
        {"stage": "Verification", "data": verification},
        {"stage": "Final status", "data": "recovered" if recovered else "not_recovered"},
    ]
    if outcome.execution is not None:
        position = next(i for i, entry in enumerate(decision_trace) if entry["stage"] == "Execution")
        decision_trace[position:position] = [
            {"stage": "Executor started", "data": {
                "mode": outcome.execution["mode"], "at": outcome.execution["started_at"]}},
            {"stage": "Executor finished", "data": deepcopy(outcome.execution)},
        ]
    agent_event["data"]["decision_trace"] = decision_trace
    agent_event["data"]["safety"] = safety
    agent_event["data"]["post_observation_error"] = post_error
    agent_event["data"]["experience"] = {
        "incident_type": initial_diagnosis["failure_type"],
        "observation": deepcopy(observation), "diagnosis": initial_diagnosis,
        "root_cause": rca["result"]["suspected_root_cause"] if rca else initial_diagnosis["root_cause"],
        "proposed_action": proposed_action,
        "executed_action": action if (
            outcome.execution["executed"] if outcome.execution is not None
            else outcome.status != "skipped") else None,
        "verification": verification, "success": recovered,
        "timestamp": agent_event["timestamp"],
    }
    if offline_strategy is not None:
        agent_event['data'].update(phase='8',offline_only=True,real_model=False,real_observation=False,
            fixture_strategy_executed=outcome.status=='succeeded',
            fixture_recovery_verified=recovered and initial_diagnosis['failure_detected'],
            fixture_initially_healthy=recovered and not initial_diagnosis['failure_detected'])
        agent_event['data']['resource_verification'] = resource_verification
    validate("agent_event", agent_event)

    return {
        "chain": ["Detect", "Localize", "Diagnose", "Decide", "Execute", "Verify"],
        "diagnosis": initial_diagnosis,
        "recovery_action": action,
        "execution_result": result,
        "post_observation": outcome.observation,
        "post_observation_error": post_error,
        "verification_diagnosis": verification_diagnosis,
        "verification_result": verification,
        "recovered": recovered,
        "history_evidence": history_evidence,
        "agent_event": agent_event,
        "memory_written": memory is not None and initial_diagnosis["failure_detected"],
        "rca": rca,
        "safety": safety,
        "decision_trace": decision_trace,
    }


def recover(observation: dict[str, Any], *, execution_succeeds: bool = True,
            memory: RecoveryMemory | None = None, rca_agent: RCAAgent | None = None,
            max_recovery_attempts: int = 1, executor=None, offline_strategy=None) -> dict[str, Any]:
    """有界恢复；每次重新诊断/RCA，拒绝重复失败动作，默认兼容单次闭环。"""
    if (isinstance(max_recovery_attempts, bool) or not isinstance(max_recovery_attempts, int)
            or not 1 <= max_recovery_attempts <= 5):
        raise ValueError("max_recovery_attempts 必须为 1~5 的整数")
    if offline_strategy is not None:
        from .strategies import MODES
        if offline_strategy not in MODES or executor is not None:
            raise ValueError('offline_strategy requires a known mode and the builtin offline executor')
        if rca_agent is not None and getattr(rca_agent.provider, 'offline_only', False) is not True:
            raise ValueError('offline_strategy requires an explicitly offline RCA provider')
        if not isinstance(observation.get('offline_signals', {}), dict):
            raise ValueError('offline_signals must be an object')
    current = deepcopy(observation)
    attempts, evidence, failed_actions = [], [], set()
    parent_event_id = None
    for index in range(max_recovery_attempts):
        if index:
            current["trace_id"] = f"trace-{uuid4()}"
        attempt = _recover_once(current, execution_succeeds=execution_succeeds,
                                memory=memory, rca_agent=rca_agent,
                                failed_actions=failed_actions, attempt_evidence=evidence,
                                executor=executor, attempt_number=index + 1,
                                retry_limit=max_recovery_attempts, offline_strategy=offline_strategy)
        action, event = attempt["recovery_action"], attempt["agent_event"]
        if not attempt["safety"]["allowed"]:
            status = "safety_rejected"
        elif attempt["execution_result"].get("executor", {}).get("mode") == "dry_run":
            status = "dry_run"
        elif attempt["recovered"]:
            status = "recovered" if attempt["diagnosis"]["failure_detected"] else "healthy"
        elif action["action"] == "no_action":
            status = "no_safe_candidate"
        elif index + 1 == max_recovery_attempts:
            status = "max_attempts_reached"
        else:
            status = "retry_pending"
        event["parent_event_id"] = parent_event_id
        event["data"].update(attempt_number=index + 1, final_status=status)
        attempt["decision_trace"][-1]["data"] = status
        validate("agent_event", event)
        if memory is not None:
            memory.remember(event)
        attempts.append(attempt)
        parent_event_id = event["event_id"]
        if status != "retry_pending":
            break
        failed_actions.add((action["action"], action["target"]))
        # 即使未启用持久 Memory，也将本轮失败交给下一次 RCA。
        evidence.append({
            "event_id": event["event_id"], "timestamp": event["timestamp"],
            "failure_type": attempt["diagnosis"]["failure_type"],
            "location": attempt["diagnosis"]["location"],
            "diagnosis": attempt["diagnosis"], "root_cause": attempt["diagnosis"]["root_cause"],
            "action": action["action"], "target": action["target"],
            "execution_status": attempt["execution_result"]["execution_status"],
            "verification_status": attempt["verification_result"]["status"],
            "verification": attempt["verification_result"], "recovered": False,
        })
        current = deepcopy(attempt["post_observation"])
    if offline_strategy is not None:
        attempts[-1].update(offline_only=True, real_recovery_actions=0, strategy_mode=offline_strategy)
    return {**attempts[-1], "attempts": attempts, "attempt_count": len(attempts),
            "final_status": status, "max_recovery_attempts": max_recovery_attempts}
