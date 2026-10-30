"""独立数据库场景：原Gate、固定postgres动作、业务双Verify与经验准入。"""
from copy import deepcopy
from datetime import datetime
import json
import re
import time
from uuid import uuid4

from .advisory import BoundedProvider, _contradictory_metric_evidence
from .authorization import AuthorizationError, digest
from .contracts import validate
from .docker_executor import now
from .pipeline import diagnose
from .planner import plan_recovery
from .rca import RCAAgent
from .safety import check_action
from .measurements import AttemptMeasurement, measurement_scope
from .recovery_smoke import _fresh, _wall_time, _SingleModelCall, _record_memory, _empty_report
from .researchloop_backend import healthy, stopped_database
from .trace_journal import TraceJournal

SCENARIO = "researchloop_stopped_postgres"


def success_evidence(report):
    """不以单一success字段接纳经验或C台账；验证动作、关联与双业务证据。"""
    try:
        obs, action = report["observation"], report["recovery_action"]
        validate("observation", obs)
        validate("recovery_action", action)
        validate("recovery_result", report["execution_result"])
        samples = report["verify_observations"]
        execution = report["execution_result"]
        if (report["scenario"] != SCENARIO or report["real_observation"] is not True
                or report["recovery_verified"] is not True or report["recovered"] is not True
                or report["recovery_authorized"] is not True or report["recovery_executed"] is not True
                or report["execution_outcome"] != "succeeded" or report["verification_status"] != "recovered"
                or execution["execution_status"] != "succeeded" or type(execution["exit_code"]) is not int
                or execution["exit_code"] != 0 or report.get("error") is not None
                or execution["executor"].get("executed") is not True
                or execution["executor"].get("success") is not True
                or (action["action"], action["target"]) != ("restart_service", "postgres")
                or len(samples) != 2 or not stopped_database(obs)):
            return False
        source, calls = report.get("diagnosis_source"), report.get("model_calls")
        if (type(calls) is not int or source not in {"provider", "memory/rule-supported"}
                or source == "provider" and (calls != 1 or report.get("real_model") is not True)
                or source == "memory/rule-supported" and (calls != 0 or report.get("real_model") is not False
                    or not report.get("memory_hit_event_ids")
                    or report.get("measurements", {}).get("provider_attempts") != 0)):
            return False
        ids = {obs["observation_id"]}
        previous = datetime.fromisoformat(execution["timestamp"]).timestamp()
        for document in (obs, action, execution, *samples):
            if any(document[key] != report[key] for key in ("incident_id", "trace_id")):
                return False
        if execution["action_id"] != action["action_id"]:
            return False
        for index, sample in enumerate(samples):
            validate("observation", sample)
            timestamp = datetime.fromisoformat(sample["timestamp"]).timestamp()
            if (not healthy(sample) or sample["observation_id"] in ids or timestamp <= previous
                    or any(sample["business"][key] != obs["business"][key]
                           for key in ("project_id", "project_db_id", "owner_user_id"))
                    or sample["business"].get("database_sql_valid") is not True
                    or sample["business"].get("probe_read_valid") is not True
                    or index == 0 and sample["business"].get("write_valid") is not True):
                return False
            ids.add(sample["observation_id"])
            previous = timestamp
        return report["scope_fingerprint"] == digest(report["scope"])
    except Exception:
        return False


def experience(memory, scope):
    if memory is None or not memory.path.exists():
        return []
    # RecoveryMemory负责严格schema、重复/冲突、结果关联；坏Memory整体拒绝。
    events = memory._read_events()
    matching = [event for event in events if event["data"].get("scenario") == SCENARIO
                and event["data"].get("scope_fingerprint") == digest(scope)]
    # 相同目标上存在失败/未知，保守回模型或人工；不能只挑一条成功掩盖失败。
    if any(not success_evidence(event["data"]) for event in matching):
        return []
    return [{"event_id": event["event_id"], "failure_type": "service_failure", "location": "postgres",
        "action": "restart_service", "target": "postgres", "recovered": True,
        "verification_status": "recovered", "execution_status": "succeeded"} for event in matching][-3:]


def database_safety(action, observation):
    base = check_action(action, observation, retry_limit=1)
    if not base["allowed"]:
        return base
    allowed = ((action["action"], action["target"]) == ("restart_service", "postgres")
               and stopped_database(observation))
    return {**base, "allowed": allowed, "reason": "allowed" if allowed else "database_scene_evidence_rejected"}


def _identity(context):
    return {"schema_version": "1.0", **{key: context[key] for key in ("incident_id", "trace_id")}}


def run_database(backend, provider, *, gate, journal, memory, model_identifier,
                 execute=False, fast_path=False, real=True, verify_timeout=45):
    """最多一次stop/模型/恢复，cleanup独立；所有真实批准仍由原终端挑战产生。"""
    if any(type(value) is not bool for value in (execute, fast_path, real)):
        raise ValueError("database_flags_invalid")
    if type(verify_timeout) not in (int, float) or not 0 < verify_timeout <= 60:
        raise ValueError("database_verify_budget_invalid")
    ctx = _identity(journal.context)
    report = _empty_report(ctx)
    report.update(phase="researchloop-db-v1", scenario=SCENARIO, real_observation=real,
        real_model=False, diagnosis_source=None, memory_hit_event_ids=[], verify_observations=[],
        cleanup_outcome="not_run", fault_injection_attempted=False, acceptance_passed=False,
        generation_measurements={"enabled": False, "model_calls": 0, "usage": None})
    measurement = AttemptMeasurement(ctx, source="real" if real else "offline_fixture")
    counted = _SingleModelCall(provider, measurement)
    injected, scope, seen = False, None, set()
    try:
        if not execute:
            raise AuthorizationError("database_execution_not_enabled")
        scope = backend.scope()
        report.update(scope=scope, scope_fingerprint=digest(scope))
        start = _wall_time()
        baseline = backend.observe(ctx)
        _fresh(baseline, baseline, not_before=start)
        report["baseline"] = baseline
        if not healthy(baseline) or not backend.sql_probe(scope):
            raise ValueError("database_baseline_not_healthy")
        history = experience(memory, scope)
        use_memory_candidate = fast_path and bool(history)
        model_binding = {**ctx, "scope": scope, "input": "bounded_structured_observation",
            "max_calls": 1, "max_output_tokens": 512, "model_identifier_sha256": digest(model_identifier)}
        model_grant = None
        binding = {**ctx, "scope": scope, "business": baseline["business"],
                   "fault": "stop_postgres_once", "cleanup": "at_most_one_fixed_postgres_restart_if_stopped"}
        grant = gate.request("experiment", binding)
        # 人工等待后重采样，状态/对象变了就拒绝注入。
        start = _wall_time()
        fresh = backend.observe(ctx)
        _fresh(fresh, baseline, seen={baseline["observation_id"]}, not_before=start)
        if not healthy(fresh) or backend.scope() != scope:
            raise ValueError("database_baseline_changed")
        authorization = gate.consume(grant, "experiment", binding, operation_id="experiment:" + ctx["trace_id"])
        journal.record("recovery_decision", "experiment_authorization", "success", authorization)
        if not use_memory_candidate:
            # 冷路径在停库前取得模型批准，避免停库后等待第二项批准。
            model_grant = gate.request("model", model_binding)
        start = _wall_time()
        ready = backend.observe(ctx)
        _fresh(ready, baseline, seen={baseline["observation_id"], fresh["observation_id"]}, not_before=start)
        if (not healthy(ready) or backend.scope() != scope or gate._now() >= grant.expires_at
                or model_grant is not None and gate._now() >= model_grant.expires_at):
            raise ValueError("database_authorization_expired_or_baseline_changed_before_injection")
        journal.record("recovery_execution", "fault_injection_started", "started", {"scope_fingerprint": digest(scope)})
        injected = report["fault_injection_attempted"] = True
        backend.mutate("stop", scope)
        start = _wall_time()
        obs = backend.observe(ctx)
        _fresh(obs, baseline, seen={baseline["observation_id"], fresh["observation_id"], ready["observation_id"]}, not_before=start)
        seen = {baseline["observation_id"], fresh["observation_id"], ready["observation_id"], obs["observation_id"]}
        report["observation"] = obs
        journal.record("observe", "observation", "success", {"observation": obs})
        if not stopped_database(obs):
            raise ValueError("database_fault_not_confirmed")
        report["incident_started"] = True
        diagnosis = diagnose(obs)
        report["diagnosis"] = diagnosis
        journal.record("failure_detection", "detection", "success", {"diagnosis": diagnosis})
        report["memory_hit_event_ids"] = [item["event_id"] for item in history]
        use_memory = use_memory_candidate and stopped_database(obs)
        if use_memory:
            rca = {"source": "memory/rule-supported", "fallback_reason": None,
                "result": {"suspected_root_cause": "postgres_service_down", "affected_component": "postgres",
                    "evidence": diagnosis["evidence"], "confidence": diagnosis["confidence"],
                    "suggested_action": {"action": "restart_service", "target": "postgres"}}}
        else:
            _fresh(obs, obs)
            if backend.scope() != scope:
                raise ValueError("database_model_scope_changed")
            auth = gate.consume(model_grant, "model", model_binding, operation_id="model:" + ctx["trace_id"])
            journal.record("recovery_decision", "model_authorization", "success", auth)
            report["real_model"] = real
            # 只发有界状态；业务账号/项目ID、路径、容器ID不发往模型。
            safe = {key: deepcopy(obs[key]) for key in (
                "schema_version", "incident_id", "trace_id", "observation_id", "timestamp", "system",
                "services", "metrics", "request", "logs")}
            rca = RCAAgent(BoundedProvider(counted), timeout_seconds=30).analyze(safe, diagnosis, history)
            result = rca["result"]
            if (rca["source"] != "provider" or rca["fallback_reason"] is not None
                    or result["affected_component"] != "postgres" or result["confidence"] < .7
                    or result["suspected_root_cause"] != "postgres_service_down"
                    or result["suggested_action"] != {"action": "restart_service", "target": "postgres"}
                    or _contradictory_metric_evidence(result["evidence"], obs)
                    or not any(re.search(r"postgres_up\s*(?:=|:)\s*0", text) for text in result["evidence"])):
                raise ValueError("database_model_diagnosis_rejected")
        report.update(rca=rca, diagnosis_source=rca["source"], diagnosis_validated=True)
        journal.record("root_cause_analysis", "rca", "success", {"rca": rca,
            "memory_hit_event_ids": report["memory_hit_event_ids"]})
        action = plan_recovery(diagnosis, observation=obs, history_evidence=history,
                               rca_result=None if use_memory else rca["result"])
        action["decision_basis"].update(diagnosis_source=rca["source"], experience_fast_path=use_memory,
            memory_hit_event_ids=report["memory_hit_event_ids"])
        report["recovery_action"] = action
        safety = database_safety(action, obs)
        journal.record("recovery_decision", "planner", "success", {"action": action})
        journal.record("recovery_decision", "safety", "success" if safety["allowed"] else "failed", safety)
        if not safety["allowed"]:
            raise ValueError("database_safety_rejected")
        action_binding = {**ctx, "scope": scope, "business": obs["business"],
            "observation_id": obs["observation_id"], "diagnosis_id": diagnosis["diagnosis_id"],
            "action": action}
        action_grant = gate.request("recovery", action_binding)
        start = _wall_time()
        current = backend.observe(ctx)
        _fresh(current, obs, seen=seen, not_before=start)
        seen.add(current["observation_id"])
        if backend.scope() != scope or not database_safety(action, current)["allowed"]:
            raise ValueError("database_pre_execution_changed")
        auth = gate.consume(action_grant, "recovery", action_binding, operation_id="recovery:" + ctx["trace_id"])
        report["recovery_authorized"] = True
        journal.record("recovery_decision", "authorization", "success", auth)
        journal.record("recovery_execution", "executor_started", "started", {"action": action})
        report.update(executor_called=True, execution_attempted=True, execution_outcome="unknown")
        execution_started, command_time = now(), time.monotonic()
        with measurement_scope(measurement):
            backend.mutate("restart", scope)
        report.update(recovery_executed=True, execution_outcome="succeeded")
        verification = {"status": "inconclusive", "checked_at": None, "health_check_passed": None,
            "fault_cleared": None, "business_request_passed": None, "evidence": []}
        execution = {**ctx, "result_id": "result-" + uuid4().hex, "action_id": action["action_id"],
            "timestamp": execution_started, "execution_status": "succeeded", "exit_code": 0,
            "stdout": None, "stderr": None, "duration_ms": (time.monotonic() - command_time) * 1000,
            "post_observation_id": None, "verification": verification,
            "executor": {"executed": True, "success": True, "mode": "real" if real else "offline_fixture",
                         "action": "restart_service", "target": "postgres", "docker_status": "restart_completed"}}
        report["execution_result"] = execution
        journal.record("recovery_execution", "executor_result", "success", {"result": execution})
        deadline = time.monotonic() + verify_timeout
        suffix = "verify-" + ctx["trace_id"].rsplit("-", 1)[-1][:12]
        while time.monotonic() < deadline:
            if backend.scope() != scope:
                raise ValueError("database_verify_scope_changed")
            start = _wall_time()
            sample = backend.observe(ctx)
            _fresh(sample, obs, seen=seen, not_before=start)
            seen.add(sample["observation_id"])
            if healthy(sample) and backend.sql_probe(scope):
                first = not report["verify_observations"]
                if first and not backend.business.write_probe(suffix):
                    raise ValueError("database_verify_write_failed_or_unknown")
                readback = backend.business.read_probe(suffix)
                if not readback:
                    raise ValueError("database_verify_readback_failed")
                sample["business"].update(database_sql_valid=True, probe_read_valid=readback,
                    write_valid=True if first else None)
                if time.monotonic() >= deadline:
                    raise ValueError("database_verify_deadline_exceeded")
                report["verify_observations"].append(sample)
                journal.record("verification", "fresh_business_verify", "success", {"observation": sample})
                if len(report["verify_observations"]) == 2:
                    report.update(recovery_verified=True, recovered=True, verification_status="recovered")
                    measurement.recovered(True, [item["observation_id"] for item in report["verify_observations"]])
                    verification.update(status="recovered", checked_at=now(), health_check_passed=True,
                        fault_cleared=True, business_request_passed=True,
                        evidence=["two fresh authenticated project reads, SQL, new write and readback"])
                    execution["post_observation_id"] = sample["observation_id"]
                    break
            elif report["verify_observations"]:
                raise ValueError("database_verify_not_consecutive")
            time.sleep(min(.5, max(0, deadline - time.monotonic())))
        report["verification_result"] = verification
        if not report["recovery_verified"]:
            raise ValueError("database_verify_timeout")
        journal.record("verification", "verify", "success", {"verification": verification,
            "recovery_verified": True, "verify_observation_ids": [x["observation_id"]
                for x in report["verify_observations"]]})
        report["model_calls"] = counted.calls
        report["measurements"] = measurement.close()
        if use_memory and counted.calls == 0 and measurement.attempts == 0 and not measurement.requests:
            report["repair_usage"] = {"input_tokens": 0, "output_tokens": 0, "source": "no_model_calls"}
        else:
            report["repair_usage"] = report["measurements"]["usage"]
        if not success_evidence(report):
            raise ValueError("database_success_evidence_invalid")
        _record_memory(report, journal, memory)
        if not report["memory_written"] or not any(event["event_id"] == report.get("event_id")
                for event in memory._read_events()):
            raise ValueError("database_memory_readback_failed")
    except (Exception, KeyboardInterrupt):
        # 不保存SDK/数据库异常原文；unknown不伪装失败，也不重放动作。
        report["error"] = "database_pipeline_rejected_or_incomplete"
    finally:
        report["model_calls"] = counted.calls
        report.setdefault("measurements", measurement.close())
        report.setdefault("repair_usage", report["measurements"]["usage"])
        if injected:
            cleanup_context = {**ctx, "trace_id": "trace-cleanup-researchloop-" + uuid4().hex}
            cleanup = TraceJournal(cleanup_context, journal.path)
            report["cleanup_trace_id"] = cleanup_context["trace_id"]
            try:
                # 即使主审计失败，也在已批准范围检查/善后；独立记录失败仍不算验收成功。
                audit_ok = True
                try:
                    cleanup.record("observe", "cleanup_started", "started", {})
                except Exception:
                    audit_ok = False
                if backend.scope() != scope:
                    raise ValueError("database_cleanup_scope_changed")
                _, state, _ = backend.container("postgres")
                report["cleanup_extra_restarts"] = 0
                if state.get("Status") == "exited" and state.get("Running") is False:
                    backend.mutate("restart", scope)
                    report["cleanup_extra_restarts"] = 1
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    start = _wall_time()
                    final = backend.observe(cleanup_context)
                    _fresh(final, final, not_before=start)
                    if healthy(final) and backend.sql_probe(scope):
                        report["final_observation"] = final
                        break
                    time.sleep(.5)
                if "final_observation" not in report:
                    raise ValueError("database_cleanup_health_unconfirmed")
                cleanup.record("verification", "cleanup_final", "success", {"observation": final})
                report["cleanup_outcome"] = "succeeded" if audit_ok else "unknown"
            except (Exception, KeyboardInterrupt):
                report["cleanup_outcome"] = "unknown"
        report["acceptance_passed"] = (success_evidence(report) and report["memory_written"] is True
            and report["cleanup_outcome"] == "succeeded")
    return report
