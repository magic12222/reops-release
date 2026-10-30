"""Phase 7D：独立授权后仅一次 Web 恢复；默认只读、零模型/注入/执行。"""

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time
from uuid import uuid4

from .advisory import diagnose_advisory, structured_observation
from .authorization import AuthorizationError, AuthorizationGate, digest
from .contracts import PROJECT_ROOT, validate
from .credential_handling import redact_persistent
from .docker_executor import DockerBoundaryError, DockerRecoveryExecutor, LocalDocker, now
from .executor import ExecutionOutcome
from .memory import RecoveryMemory
from .nexent_provider import NexentConfig, NexentRCAProvider
from .pipeline import diagnose
from .safety import check_action
from .trace_journal import TraceJournal
from .verification import verify
from .measurements import AttemptMeasurement, measurement_scope

RUNTIME = PROJECT_ROOT / "runtime"


def context():
    return {"schema_version": "1.0", "incident_id": f"incident-7d-{uuid4()}",
            "trace_id": f"trace-7d-{uuid4()}"}


def _timestamp(observation):
    value = datetime.fromisoformat(observation["timestamp"].replace("Z", "+00:00"))
    if value.utcoffset() is None:
        raise ValueError("observation_timezone_required")
    return value.timestamp()


def _wall_time():
    # Use the same Windows clock API/precision as docker_executor.now().
    from .b_clock import wall_time
    return wall_time()


def _fresh(observation, original, *, seen=(), not_before=None):
    validate("observation", observation)
    if observation.get("observation_conflicts"):
        raise ValueError("observation_conflict_reobserve_required")
    age = _wall_time() - _timestamp(observation)
    if (any(observation[key] != original[key] for key in ("incident_id", "trace_id"))
            or not 0 <= age <= 120 or observation["observation_id"] in seen
            or observation["observation_id"].startswith("obs-unavailable-")
            or (not_before is not None and _timestamp(observation) < not_before)):
        raise ValueError("observation_stale_synthetic_or_uncorrelated")


def _healthy(observation):
    return (not observation.get("observation_conflicts")
            and set(observation["services"]) >= {"api", "postgres", "redis"}
            and all(observation["services"][name]["status"] == "healthy"
                    and _up(observation, name, 1)
                    for name in ("api", "postgres", "redis"))
            and observation["request"].get("method") == "GET"
            and observation["request"].get("endpoint") == "/users"
            and observation["request"].get("status_code") == 200 and verify(observation)[2])


def _up(observation, name, expected):
    value = observation["metrics"].get(name + "_up")
    return type(value) in (int, float) and value == expected


def _web_stopped(observation):
    return (diagnose(observation)["root_cause"] == "api_service_down"
            and observation["services"].get("api", {}).get("status") == "unhealthy"
            and observation["services"]["api"].get("message") == "stopped"
            and _up(observation, "api", 0)
            and observation["request"].get("method") == "GET"
            and observation["request"].get("endpoint") == "/users"
            and observation["request"].get("status_code") is None
            and all(observation["services"].get(name, {}).get("status") == "healthy"
                    and _up(observation, name, 1) for name in ("postgres", "redis")))


def _scope(backend):
    scope = backend.recovery_scope()
    if (scope.get("project") != "reops-lab"
            or scope.get("compose_file") != str(PROJECT_ROOT / "docker-compose.yml")
            or scope.get("compose_sha256") != hashlib.sha256((PROJECT_ROOT / "docker-compose.yml").read_bytes()).hexdigest()
            or scope.get("business_url") != "http://127.0.0.1:18000/users"
            or not scope.get("docker_endpoint", "").startswith(("npipe://", "unix://"))
            or set(scope.get("containers", {})) != {"api", "postgres", "redis"}
            or any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in scope["containers"].values())):
        raise DockerBoundaryError("phase7d_scope_rejected")
    return deepcopy(scope)


class _ScopedBackend:
    """恢复目标再次收窄为 web，并绑定授权时的完整容器 ID。"""
    def __init__(self, backend, scope):
        self.backend, self.scope = backend, deepcopy(scope)

    def _check(self):
        if _scope(self.backend) != self.scope:
            raise DockerBoundaryError("authorized_environment_changed")

    def container(self, service):
        self._check()
        if service != "api":
            raise DockerBoundaryError("phase7d_only_web_restart")
        return self.backend.container(service)

    def restart(self, target):
        self._check()
        if target != "web":
            raise DockerBoundaryError("phase7d_only_web_restart")
        self.backend.restart(target, expected_container_id=self.scope["containers"]["api"])

    def observe(self, previous):
        self._check()
        return self.backend.observe(previous)


def model_binding(observation, scope, model_identifier):
    return {key: observation[key] for key in ("incident_id", "trace_id")} | {
        "scope": scope, "model_identifier_sha256": hashlib.sha256(model_identifier.encode()).hexdigest(),
        "max_calls": 1, "max_output_tokens": 512, "input": "bounded_structured_observation"}


def _empty_report(observation):
    return {"phase": "7D", **{key: observation[key] for key in ("incident_id", "trace_id")},
            "diagnosis_validated": False, "recovery_authorized": False,
            "recovery_executed": False, "recovery_verified": False, "recovered": False,
            "executor_called": False, "execution_attempted": False, "execution_outcome": "not_run",
            "model_calls": 0, "verification_status": "not_run", "memory_written": False,
            "incident_started": False,
            "execution_result": {"execution_status": "skipped", "executor": {"executed": False}},
            "verification_result": {"status": "not_run"}}


def _contains_command(value):
    if isinstance(value, dict):
        return any(key.lower() in {"command", "shell", "script"} or _contains_command(item)
                   for key, item in value.items())
    return isinstance(value, list) and any(_contains_command(item) for item in value)


def _web_evidence(rca):
    evidence = " ".join(rca["result"]["evidence"]).lower()
    return bool(re.search(r"\bapi_up\s*(?:=|:)\s*0\b", evidence)
                or "api" in evidence and "stopped" in evidence)


class _SingleModelCall:
    def __init__(self, provider, measurement=None):
        self.provider, self.calls = provider, 0
        self.measurement = measurement

    def _measurement_finished(self, result):
        if self.measurement is not None:
            self.measurement.close_model(result)

    def complete(self, request, *, timeout_seconds):
        if self.calls:
            raise ValueError("single_model_call_budget_exhausted")
        if self.measurement is not None and not self.measurement.begin_model(timeout_seconds):
            raise ValueError("measurement_closed")
        self.calls += 1
        if self.measurement is None:
            return self.provider.complete(request, timeout_seconds=timeout_seconds)
        with measurement_scope(self.measurement):
            text = self.provider.complete(request, timeout_seconds=timeout_seconds)
        self.measurement.text_returned(text)
        return text


def _record_memory(report, journal, memory):
    if memory is None or not report.get("diagnosis", {}).get("failure_detected"):
        return
    event = redact_persistent({"schema_version": "1.0", "event_id": f"event-{uuid4()}",
        "incident_id": report["incident_id"], "trace_id": report["trace_id"], "timestamp": now(),
        "parent_event_id": journal.events[-1]["event_id"] if journal.events else None,
        "stage": "experience_update", "status": "success" if report["recovery_verified"] else
            "failed" if report["executor_called"] else "skipped",
        "message": f"Phase {report['phase']} recovery outcome; cleanup is recorded separately",
        "data": {**deepcopy(report), "trajectory": deepcopy(journal.events)}})
    event["data"].pop("memory_written", None)
    validate("agent_event", event)
    try:
        memory.remember(event)
        report["memory_written"] = True
        report["event_id"] = event["event_id"]
        journal.record("experience_update", "memory", "success", {"event_id": event["event_id"]})
    except Exception:
        report["error"] = "memory_or_final_audit_write_failed"


def _validate_run_settings(backend, provider, *, execute_recovery, real_model,
                           real_observation, verify_timeout, poll_interval):
    """所有实验入口在授权/故障注入前校验预算与已知真实能力来源。"""
    if any(type(flag) is not bool for flag in (execute_recovery, real_model, real_observation)):
        raise ValueError('execution_and_source_flags_must_be_boolean')
    if (type(verify_timeout) not in (int, float) or not 0 <= verify_timeout <= 60
            or type(poll_interval) not in (int, float) or not 0 <= poll_interval <= 1):
        raise ValueError('verification_budget_invalid')
    if isinstance(backend, LocalDocker) and not real_observation:
        raise ValueError('real_backend_source_mismatch')
    if isinstance(provider, NexentRCAProvider) and not real_model:
        raise ValueError('real_provider_source_mismatch')
    if real_observation and verify_timeout == 0:
        raise ValueError('real_verification_requires_positive_budget')
    return {'max_model_calls': 1, 'max_recovery_actions': 1,
            'verify_window_seconds': verify_timeout, 'poll_interval_seconds': poll_interval,
            'whole_pipeline_hard_deadline': False}


def run_recovery(observation, provider, *, backend, gate, journal, memory=None,
                 execute_recovery=False, model_grant=None, model_identifier="offline-test",
                 real_model=False, real_observation=False, executor_factory=None,
                 verify_timeout=30, poll_interval=0.5, phase8_online=False, phase8b=False, incident_started=False):
    """模型和恢复分别消费人类授权；默认不会构造或调用 Recovery Executor。"""
    report = _empty_report(observation)
    report.update(real_observation=real_observation, real_model=real_model)
    measurement = AttemptMeasurement(observation, source="real" if real_model and real_observation
        else "mixed" if real_model or real_observation else "offline_fixture")
    counted = _SingleModelCall(provider, measurement)
    try:
        if type(incident_started) is not bool:
            raise ValueError("incident_started_must_be_boolean")
        report["incident_started"] = incident_started
        if type(phase8b) is not bool or phase8b and not phase8_online:
            raise ValueError('phase8b_requires_phase8_online')
        if type(phase8_online) is not bool:
            raise ValueError('phase8_flag_must_be_boolean')
        if phase8_online:
            from .phase8_online import rank_online, check_online_action, ScopedStartBackend, StartExecutor
            report['phase'] = '8'
        if phase8b:
            from .phase8b_online import rank_online as rank_online, check_online_action as check_online_action, ScopedWebBackend as ScopedStartBackend, WebExecutor as StartExecutor
            report['phase'] = '8B'
        report['budgets'] = _validate_run_settings(backend, provider,
            execute_recovery=execute_recovery, real_model=real_model, real_observation=real_observation,
            verify_timeout=verify_timeout, poll_interval=poll_interval)
        if {key: journal.context[key] for key in ("incident_id", "trace_id")} != {
                key: observation[key] for key in ("incident_id", "trace_id")}:
            raise ValueError("journal_correlation_mismatch")
        if "case_id" in journal.context and journal.context["case_id"] != observation.get("case_id"):
            raise ValueError("journal_correlation_mismatch")
        _fresh(observation, observation)
        scope = _scope(backend)
        report["observation"] = structured_observation(observation)
        journal.record("observe", "pre_recovery_observation", "success", {"observation": report["observation"]})
        binding = model_binding(observation, scope, model_identifier)
        grant = model_grant or gate.request("model", binding)
        report["model_authorization"] = gate.consume(grant, "model", binding,
            operation_id="model:" + observation["trace_id"])
        journal.record("root_cause_analysis", "model_authorization", "success", report["model_authorization"])
        core = diagnose_advisory(observation, counted, memory=memory)
        measurement.close_model(core["rca"])
        if phase8_online:
            core = rank_online(core, memory)
        report.update({key: core[key] for key in ("observation", "diagnosis", "rca", "model_input",
            "model_calls", "recovery_action", "safety", "diagnosis_validated", "rejection_reason")})
        journal.record("root_cause_analysis", "rca", "success" if core["diagnosis_validated"] else "failed",
                       {"diagnosis": core["diagnosis"], "rca": core["rca"]})
        journal.record("recovery_decision", "planner", "success" if core["would_execute"] else "skipped",
                       {"action": core["recovery_action"]})
        journal.record("recovery_decision", "safety", "success" if core["safety"]["allowed"] else "failed",
                       core["safety"])
        action = deepcopy(core["recovery_action"])
        expected_action = action['action'] if phase8b else ('start_service' if phase8_online else 'restart_service')
        completed_status = 'start_completed' if expected_action == 'start_service' else 'restart_completed'
        report["execution"] = "WOULD_EXECUTE" if core["would_execute"] else "NO_ACTION"
        if not execute_recovery:
            report["execution_skipped_reason"] = "execute_recovery_flag_required"
            return report
        if (not core["would_execute"] or not _web_stopped(observation) or not _web_evidence(core["rca"])
                or (action["action"], action["target"]) != (expected_action, "web")
                or _contains_command(action)):
            report["execution_skipped_reason"] = "diagnosis_planner_or_phase7d_scope_rejected"
            return report
        recovery_binding = {"scope": scope, "action_digest": digest(action),
            "proposed_action": deepcopy(action),
            "action_id": action["action_id"], "diagnosis_id": action["diagnosis_id"],
            **{key: observation[key] for key in ("incident_id", "trace_id")},
            "pre_observation_id": observation["observation_id"], "action": expected_action, "target": "web"}
        grant = gate.request("recovery", recovery_binding)
        # Recheck all identities and current fault after the human has reviewed the plan.
        if _scope(backend) != scope:
            raise AuthorizationError("authorized_environment_changed")
        current_started = _wall_time()
        current = backend.observe(observation)
        _fresh(current, observation, seen={observation["observation_id"]}, not_before=current_started)
        journal.record("observe", "pre_execution_observation", "success", {"observation": current})
        safety_check = check_online_action if phase8_online else check_action
        if not _web_stopped(current) or not safety_check(action, current)["allowed"]:
            report["execution_skipped_reason"] = "current_fault_changed_or_cleared"
            return report
        report["authorization"] = gate.consume(grant, "recovery", recovery_binding,
                                                operation_id="recovery:" + action["action_id"])
        report["recovery_authorized"] = True
        journal.record("recovery_decision", "authorization", "success", report["authorization"])
        scoped = ScopedStartBackend(backend, scope) if phase8_online else _ScopedBackend(backend, scope)
        factory = executor_factory or (StartExecutor if phase8_online else
                                      lambda checked: DockerRecoveryExecutor(dry_run=False, backend=checked))
        journal.record("recovery_execution", "executor_started", "started", {"action_id": action["action_id"]})
        executor = factory(scoped)
        execution_started = _wall_time()
        recovery_started_monotonic = time.monotonic()
        report["executor_called"] = report["execution_attempted"] = True
        report["execution_result"] = {"schema_version": "1.0", "result_id": f"result-{uuid4()}",
            "incident_id": observation["incident_id"], "trace_id": observation["trace_id"],
            "action_id": action["action_id"], "timestamp": now(), "execution_status": "failed",
            "exit_code": None, "stdout": None, "stderr": None, "duration_ms": 0,
            "post_observation_id": None,
            "verification": {"status": "not_run", "checked_at": None, "health_check_passed": None,
                "fault_cleared": None, "business_request_passed": None, "evidence": []},
            "executor": {"executed": False, "mutation_attempted": True, "docker_status": "unknown"}}
        try:
            with measurement_scope(measurement):
                outcome = executor(deepcopy(action), deepcopy(observation))
            if not isinstance(outcome, ExecutionOutcome) or not isinstance(outcome.execution, dict):
                raise ValueError("invalid_executor_outcome")
            if (outcome.status not in {"succeeded", "failed", "rejected", "skipped"}
                    or outcome.execution.get("action") != action["action"]
                    or outcome.execution.get("target") != action["target"]
                    or outcome.execution.get("mode") != "real"
                    or type(outcome.execution.get("executed")) is not bool
                    or type(outcome.execution.get("success")) is not bool
                    or outcome.execution.get("docker_status") not in {completed_status, "unknown", "command_failed", None}):
                raise ValueError("executor_metadata_invalid_or_uncorrelated")
            if (type(outcome.duration_ms) not in (int, float) or not math.isfinite(outcome.duration_ms)
                    or outcome.duration_ms < 0 or outcome.exit_code is not None and type(outcome.exit_code) is not int):
                raise ValueError("invalid_executor_result_values")
            confirmed = (outcome.status == "succeeded" and type(outcome.exit_code) is int and outcome.exit_code == 0
                         and outcome.execution.get("executed") is True
                         and outcome.execution.get("success") is True
                         and outcome.execution.get("mode") == "real"
                         and outcome.execution.get("docker_status") == completed_status
                         and outcome.execution.get("action") == action["action"]
                         and outcome.execution.get("target") == action["target"])
            report["recovery_executed"] = confirmed
            if phase8_online:
                report['operation_proof'] = deepcopy(outcome.execution.get('operation_proof'))
            report["execution_attempted"] = outcome.execution.get("executed") is True
            report["execution_outcome"] = "succeeded" if confirmed else (
                "unknown" if outcome.execution.get("docker_status") == "unknown"
                or outcome.status == "succeeded" else "failed")
            report["execution_result"] = {"schema_version": "1.0", "result_id": f"result-{uuid4()}",
                "incident_id": observation["incident_id"], "trace_id": observation["trace_id"],
                "action_id": action["action_id"], "timestamp": now(),
                "execution_status": "succeeded" if confirmed else "failed",
                "exit_code": outcome.exit_code, "stdout": None, "stderr": None,
                "duration_ms": outcome.duration_ms, "post_observation_id": None,
                "verification": {"status": "not_run", "checked_at": None, "health_check_passed": None,
                    "fault_cleared": None, "business_request_passed": None, "evidence": []},
                "executor": {key: outcome.execution.get(key) for key in
                    ("action", "target", "mode", "success", "docker_status")} | {"executed": confirmed,
                             "mutation_attempted": report["execution_attempted"]}}
            try:
                _fresh(outcome.observation, observation,
                       seen={observation["observation_id"], current["observation_id"]},
                       not_before=execution_started)
                report["executor_post_observation"] = outcome.observation
            except Exception:
                report["error"] = "executor_post_observation_invalid"
        except (Exception, KeyboardInterrupt):
            report["execution_outcome"] = "unknown"
            report["recovery_executed"] = False
            report["error"] = "executor_failed_or_state_uncertain"
        journal.record("recovery_execution", "executor_result",
                       "success" if report["recovery_executed"] else "failed",
                       {"execution_outcome": report["execution_outcome"], "result": report["execution_result"]})
        # Independent measurements, not executor flags or cleanup, determine Verify.
        seen = {observation["observation_id"], current["observation_id"]}
        if report.get("executor_post_observation"):
            seen.add(report["executor_post_observation"]["observation_id"])
        deadline, consecutive = time.monotonic() + verify_timeout, 0
        verification = {"status": "inconclusive", "checked_at": now(), "health_check_passed": None,
                        "fault_cleared": None, "business_request_passed": None, "evidence": []}
        verified_ids = []
        try:
            while True:
                if verify_timeout > 0 and time.monotonic() >= deadline:
                    verification['status'] = 'inconclusive'
                    verification['evidence'].append('independent verification deadline exceeded')
                    break
                if _scope(backend) != scope:
                    raise DockerBoundaryError("post_environment_changed")
                sample_started = _wall_time()
                post = backend.observe(observation)
                _fresh(post, observation, seen=seen, not_before=max(execution_started,sample_started))
                seen.add(post["observation_id"])
                report["post_observation"] = post
                if phase8_online:
                    report.setdefault('verify_observations', []).append(deepcopy(post))
                journal.record("observe", "post_recovery_observation", "success", {"observation": post})
                _, verification, healthy = verify(post)
                healthy = healthy and _healthy(post)
                if verify_timeout > 0 and time.monotonic() > deadline:
                    verification['status'] = 'inconclusive'
                    verification['evidence'].append('independent verification deadline exceeded')
                    break
                consecutive = consecutive + 1 if healthy else 0
                verified_ids = (verified_ids + [post["observation_id"]])[-2:] if healthy else []
                if consecutive >= 2:
                    report["system_observed_healthy"] = True
                    report["recovery_verified"] = (report["recovery_executed"]
                        and report["execution_outcome"] == "succeeded" and not report.get("error"))
                    measurement.recovered(report["recovery_verified"], verified_ids)
                    break
                if not healthy and time.monotonic() >= deadline:
                    verification["status"] = "not_recovered"
                    break
                remaining = max(0, deadline - time.monotonic()) if verify_timeout > 0 else poll_interval
                time.sleep(min(poll_interval, remaining))
            if not report["recovery_executed"] or report.get("error"):
                verification["status"] = "inconclusive"
        except (Exception, KeyboardInterrupt):
            verification = {"status": "inconclusive", "checked_at": now(), "health_check_passed": None,
                            "fault_cleared": None, "business_request_passed": None,
                            "evidence": ["fresh independent verification unavailable"]}
            report["error"] = "post_observation_or_verify_failed"
        report.update(verification_result=verification, verification_status=verification["status"],
                      recovered=report["recovery_verified"])
        if report["execution_result"].get("result_id"):
            report["execution_result"].update(verification=verification,
                post_observation_id=report.get("post_observation", {}).get("observation_id"))
            validate("recovery_result", report["execution_result"])
        journal.record("verification", "verify", "success" if report["recovery_verified"] else "failed",
                       {"verification": verification, "recovery_verified": report["recovery_verified"]})
        if phase8b:
            report['online_latency'] = {'source': 'local_monotonic_executor_to_verify',
                'duration_ms': (time.monotonic() - recovery_started_monotonic) * 1000,
                'target_ms': 5000, 'execution_started_at': execution_started,
                'verify_observation_ids': [sample['observation_id'] for sample in report.get('verify_observations', [])]}
    except AuthorizationError as error:
        report["execution_skipped_reason"] = str(error)
        report["error"] = "authorization_required_or_invalid"
        try:
            journal.record("recovery_decision", "authorization", "waiting_human", {"reason": str(error)})
        except Exception:
            report["error"] = "audit_write_failed"
    except (Exception, KeyboardInterrupt):
        report["error"] = "recovery_pipeline_failed"
    finally:
        report["model_calls"] = counted.calls
        report["measurements"] = measurement.close()
        _record_memory(report, journal, memory)
    return redact_persistent(report)


def fault_recovery(backend, provider, *, gate, journal, memory, model_identifier,
                   execute_recovery=False, real_model=False, executor_factory=None,
                   real_observation=False, verify_timeout=30, poll_interval=0.5, phase8_online=False, phase8b=False):
    """实验 stop/cleanup 单独授权；失败/清理健康不会覆盖恢复结论。"""
    report = _empty_report(journal.context)
    report.update(real_observation=real_observation, real_model=real_model)
    injected, scope = False, None
    try:
        if type(phase8b) is not bool or phase8b and not phase8_online:
            raise ValueError('phase8b_requires_phase8_online')
        if type(phase8_online) is not bool:
            raise ValueError('phase8_flag_must_be_boolean')
        if phase8_online:
            report['phase'] = '8'
        report['budgets'] = _validate_run_settings(backend, provider,
            execute_recovery=execute_recovery, real_model=real_model, real_observation=real_observation,
            verify_timeout=verify_timeout, poll_interval=poll_interval)
        if execute_recovery is not True:
            raise AuthorizationError("fault_experiment_requires_execution_flag")
        baseline = backend.observe({"schema_version": "1.0", **journal.context})
        _fresh(baseline, baseline)
        if not _healthy(baseline):
            raise DockerBoundaryError("baseline_not_healthy")
        scope = _scope(backend)
        # Phase 8 的模型 Grant 靠近注入签发，避免在等待实验批准时耗尽 TTL。
        model_grant = None if phase8_online else gate.request(
            "model", model_binding(baseline, scope, model_identifier))
        binding = {**journal.context, "scope": scope, "fault": "stop_api_once",
                   "cleanup": "at_most_one_web_restart_if_unhealthy", "max_injections": 1}
        grant = gate.request("experiment", binding)
        authorization = gate.consume(grant, "experiment", binding,
                                     operation_id="experiment:" + baseline["trace_id"])
        journal.record("recovery_decision", "experiment_authorization", "success", authorization)
        if _scope(backend) != scope:
            raise DockerBoundaryError("experiment_environment_changed")
        current = backend.observe(baseline)
        _fresh(current, baseline, seen={baseline["observation_id"]})
        if not _healthy(current):
            raise DockerBoundaryError("experiment_baseline_changed")
        if phase8_online:
            model_grant = gate.request('model', model_binding(current, scope, model_identifier))
        journal.record("recovery_execution", "fixture_fault_injection", "started",
                       {"experiment_authorization": authorization["authorization_id"], "target": "api"})
        if phase8_online and gate._now() >= min(grant.expires_at, model_grant.expires_at):
            raise AuthorizationError('authorization_expired_before_fault_injection')
        # Even a stop timeout may have changed state and must be reconciled.
        injected = True
        report["incident_started"] = None  # 尚无 fresh 故障确认，不能推断已启动有效 incident。
        backend.inject_web_failure_test_only(expected_container_id=scope["containers"]["api"])
        fault = backend.observe(baseline)
        _fresh(fault, baseline, seen={baseline["observation_id"]})
        if not _web_stopped(fault):
            raise DockerBoundaryError("fault_not_observed")
        report = run_recovery(fault, provider, backend=backend, gate=gate, journal=journal,
            memory=memory, execute_recovery=True, model_grant=model_grant,
            model_identifier=model_identifier, real_model=real_model, executor_factory=executor_factory,
            real_observation=real_observation, verify_timeout=verify_timeout, poll_interval=poll_interval,
            phase8_online=phase8_online, phase8b=phase8b, incident_started=True)
        if phase8_online:
            report['baseline_observation'] = baseline
            report['scenario'] = {'fault': 'stopped_api_with_healthy_dependencies',
                                  'new_online_action': 'start_service', 'target': 'web',
                                  'restart_counterfactual_executed': False}
            if phase8b:
                report['scenario'].pop('restart_counterfactual_executed')
                report['scenario'].update(new_online_action='start_service_and_restart_service',
                    scoring_policy='phase8b-v1', memory_source='isolated_empty_then_actual_verify_events',
                    counterfactuals_scoring_only=True)
    except (Exception, KeyboardInterrupt):
        report["error"] = "fault_experiment_precondition_or_injection_failed"
        try:
            journal.record("recovery_execution", "fault_experiment_failed", "failed",
                           {"fault_injection_attempted": injected})
        except Exception:
            report["audit_error"] = "fault_failure_audit_unavailable"
    finally:
        report["fault_injection_attempted"] = injected
        report["cleanup_outcome"] = "not_run"
        if injected:
            cleanup_context = {**journal.context, "trace_id": f"trace-cleanup-{uuid4()}"}
            cleanup = TraceJournal(cleanup_context, journal.path)
            try:
                if _scope(backend) != scope:
                    raise DockerBoundaryError("cleanup_environment_changed")
                post = backend.observe({"schema_version": "1.0", **cleanup_context})
                _fresh(post, cleanup_context)
                seen = {post["observation_id"]}
                cleanup.record("observe", "cleanup_pre_observation", "success", {"observation": post})
                if not _healthy(post):
                    cleanup.record("recovery_execution", "authorized_fixture_cleanup", "started",
                                   {"acceptance_trace_id": journal.context["trace_id"]})
                    backend.restart("web", expected_container_id=scope["containers"]["api"])
                deadline = time.monotonic() + 30
                while not _healthy(post):
                    post = backend.observe({"schema_version": "1.0", **cleanup_context})
                    _fresh(post, cleanup_context, seen=seen)
                    seen.add(post["observation_id"])
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.5)
                report["cleanup_outcome"] = "succeeded" if _healthy(post) else "failed"
                report["final_observation"] = post
                cleanup.record("verification", "cleanup_final_state",
                    "success" if report["cleanup_outcome"] == "succeeded" else "failed", {"observation": post})
            except (Exception, KeyboardInterrupt):
                report["cleanup_outcome"] = "unknown"
                report["cleanup_error"] = "cleanup_failed_inspect_test_environment"
        report["acceptance_passed"] = (report["recovery_verified"] and report["memory_written"]
            and report["cleanup_outcome"] == "succeeded" and not report.get("error"))
    return redact_persistent(report)


def main(argv=None, *, backend=None, gate=None, provider=None, executor_factory=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--diagnose", action="store_true", help="单独授权一次真实模型诊断")
    modes.add_argument("--fault-smoke", action="store_true", help="单独授权测试注入、一次恢复及善后")
    parser.add_argument("--execute-recovery", action="store_true", help="仅执行意图，不能替代人类授权")
    args = parser.parse_args(argv)
    ctx = context()
    report = _empty_report(ctx)
    try:
        if args.execute_recovery and not (args.diagnose or args.fault_smoke):
            raise AuthorizationError("execution_requires_explicit_mode_and_user_authorization")
        if args.fault_smoke and not args.execute_recovery:
            raise AuthorizationError("fault_experiment_requires_execution_flag")
        backend = backend or LocalDocker()
        if not (args.diagnose or args.fault_smoke):
            observation = backend.observe(ctx)
            report.update(mode="read-only", observation=structured_observation(observation),
                          baseline_healthy=_healthy(observation))
            code = 0
        else:
            config = replace(NexentConfig.from_env(), max_output_tokens=512)
            config.require_real_model()
            # Phase 7D accepts only the already validated DLUT configuration.
            if config.api_base.rstrip("/") != "http://aigw.dlut.edu.cn/v1" or config.model_id != "DeepSeek-V3.1-W8A8":
                raise ValueError("phase7d_model_scope_rejected")
            gate = gate or AuthorizationGate(RUNTIME / "phase7d-authorizations.sqlite3")
            journal = TraceJournal(ctx, RUNTIME / "phase7d-audit.jsonl")
            # Provider construction is lazy; actual SDK creation happens after the model grant.
            real_model = provider is None
            provider = provider or NexentRCAProvider(config)
            memory = RecoveryMemory(RUNTIME / "phase7d-memory.jsonl")
            if args.fault_smoke:
                report = fault_recovery(backend, provider, gate=gate, journal=journal, memory=memory,
                    model_identifier=config.model_id, real_model=real_model, execute_recovery=True,
                    real_observation=isinstance(backend, LocalDocker),
                    executor_factory=executor_factory)
                code = 0 if report["acceptance_passed"] else 1
            else:
                report = run_recovery(backend.observe(ctx), provider, backend=backend, gate=gate,
                    journal=journal, memory=memory, execute_recovery=args.execute_recovery,
                    model_identifier=config.model_id, real_model=real_model,
                    real_observation=isinstance(backend, LocalDocker), executor_factory=executor_factory)
                code = 0 if (report["recovery_verified"] if args.execute_recovery
                             else report["diagnosis_validated"]) and not report.get("error") else 1
    except (Exception, KeyboardInterrupt):
        report["error"], code = "precondition_or_authorization_failed", 2
    print(json.dumps(redact_persistent(report), ensure_ascii=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
