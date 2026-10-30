"""Phase 7D 的真实路径全部使用状态化本地替身；禁止网络/真实 Docker。"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from reops_agent.authorization import AuthorizationError, AuthorizationGate, interactive_confirm
from reops_agent.contracts import PROJECT_ROOT, validate
from reops_agent.docker_executor import DockerBoundaryError, DockerRecoveryExecutor, LocalDocker, now
from reops_agent.executor import ExecutionOutcome
from reops_agent.memory import RecoveryMemory
from reops_agent.nexent_provider import NexentConfig
from reops_agent.recovery_smoke import fault_recovery, main, run_recovery
from reops_agent.trace_journal import TraceJournal


def observation(healthy=False, previous=None):
    value = json.loads((PROJECT_ROOT / "shared/examples/healthy_observation.example.json").read_text(encoding="utf-8"))
    value.update(observation_id=f"obs-test-{uuid4()}", timestamp=now())
    if previous:
        value.update({key: previous[key] for key in ("incident_id", "trace_id")})
    value["services"] = {name: {"status": "healthy", "message": "health probe healthy"}
                         for name in ("api", "postgres", "redis")}
    value["metrics"] = {name + "_up": 1 for name in value["services"]}
    value["request"] = {"method": "GET", "endpoint": "/users", "status_code": 200, "latency_ms": 1}
    value["logs"] = []
    if not healthy:
        value["services"]["api"].update(status="unhealthy", message="stopped")
        value["metrics"]["api_up"] = 0
        value["request"]["status_code"] = None
    return value


def provider(**changes):
    value = {"suspected_root_cause": "api_service_down", "affected_component": "api",
        "evidence": ["api_up=0 and api unhealthy, message stopped"], "confidence": .97,
        "reasoning_summary": "API stopped, dependencies healthy",
        "suggested_action": {"action": "restart_service", "target": "web"}}
    value.update(changes)
    return Mock(complete=Mock(return_value=json.dumps(value)))


class Backend:
    def __init__(self, healthy=False):
        self.healthy, self.restarts, self.injections = healthy, [], 0
        self.post_changes = {}
        self.overrides = []
        self.scope = {"project": "reops-lab", "compose_file": str(PROJECT_ROOT / "docker-compose.yml"),
            "compose_sha256": hashlib.sha256((PROJECT_ROOT / "docker-compose.yml").read_bytes()).hexdigest(),
            "docker_endpoint": "npipe://test-local-engine", "containers":
                {name: char * 64 for name, char in (("api", "a"), ("postgres", "b"), ("redis", "c"))},
            "business_url": "http://127.0.0.1:18000/users"}

    def recovery_scope(self):
        return deepcopy(self.scope)

    def container(self, service):
        return self.scope["containers"][service], {"Running": self.healthy}

    def observe(self, previous):
        value = observation(self.healthy, previous)
        if self.overrides:
            override = self.overrides.pop(0)
            return override(value)
        if self.restarts:
            value.update(deepcopy(self.post_changes))
        return value

    def restart(self, target, *, expected_container_id=None):
        assert target == "web"
        if expected_container_id and expected_container_id != self.scope["containers"]["api"]:
            raise DockerBoundaryError("authorized_container_changed")
        self.restarts.append(target)
        self.healthy = True

    def inject_web_failure_test_only(self, *, expected_container_id=None):
        assert expected_container_id == self.scope["containers"]["api"]
        self.injections += 1
        self.healthy = False


@pytest.fixture
def cli_runtime(tmp_path, monkeypatch):
    """覆盖 CLI 所有默认落盘位置；不改正式 CLI 的生产路径。"""
    from reops_agent import recovery_smoke
    monkeypatch.setattr(recovery_smoke, "RUNTIME", tmp_path / "cli-runtime")
    return recovery_smoke.RUNTIME


@pytest.fixture
def rig(tmp_path):
    pre = observation()
    backend = Backend()
    gate = AuthorizationGate(tmp_path / "grants.sqlite3", confirm=lambda request, challenge: challenge)
    journal = TraceJournal(pre, tmp_path / "audit.jsonl")
    memory = RecoveryMemory(tmp_path / "memory.jsonl")
    factory = Mock(side_effect=lambda scoped: DockerRecoveryExecutor(backend=scoped, dry_run=False, verify_timeout=0))
    return pre, backend, gate, journal, memory, factory


def run(rig, model=None, **kwargs):
    pre, backend, gate, journal, memory, factory = rig
    return run_recovery(pre, model or provider(), backend=backend, gate=gate, journal=journal,
        memory=memory, executor_factory=factory, verify_timeout=0, poll_interval=0, **kwargs)


def test_journal_case_conflict_rejected_before_model_or_executor(rig):
    pre, backend, gate, journal, memory, factory = rig
    journal.context["case_id"] = "case-conflict"
    model = provider()
    report = run(rig, model=model, execute_recovery=True)
    assert report["error"] == "recovery_pipeline_failed"
    assert model.complete.call_count == factory.call_count == 0
    assert not backend.restarts and not memory.path.exists() and not journal.events


def test_conflicting_observation_cannot_enter_model_or_real_recovery(rig):
    rig[0]["observation_conflicts"] = ["api:probe_samples_disagree"]
    model = provider()
    report = run(rig, model=model, execute_recovery=True)
    assert report["error"] == "recovery_pipeline_failed"
    assert model.complete.call_count == rig[5].call_count == 0
    assert not rig[1].restarts


@pytest.mark.parametrize("scenario", ("password", "unreachable", "unknown_dependencies"))
def test_actual_a_probe_failure_does_not_authorize_b_real_entry(rig, scenario):
    from test_ab_scenario_contract import observe, FixtureTools
    changes = ({"dependencies": {"postgres": "degraded", "redis": "healthy"}, "users": 503}
               if scenario == "password" else {"fail": "all", "tools": FixtureTools(running={})}
               if scenario == "unreachable" else {"dependencies": {}, "users": 503})
    pre = observe(**changes)
    updated = (pre, rig[1], rig[2], TraceJournal(pre, rig[3].path), rig[4], rig[5])
    report = run(updated, execute_recovery=True)
    assert report["executor_called"] is False and report["recovery_executed"] is False
    assert rig[5].call_count == 0 and not rig[1].restarts


def test_success_is_once_and_all_evidence_is_correlated(rig):
    report = run(rig, execute_recovery=True)
    pre, backend, gate, journal, memory, factory = rig
    assert all(report[key] for key in ("diagnosis_validated", "recovery_authorized", "recovery_executed", "recovery_verified"))
    assert report["model_calls"] == 1 and report["execution_outcome"] == "succeeded"
    assert backend.restarts == ["web"] and factory.call_count == 1
    assert report["post_observation"]["observation_id"] != pre["observation_id"]
    validate("recovery_result", report["execution_result"])
    for index, event in enumerate(journal.events):
        validate("agent_event", event)
        assert event["incident_id"] == pre["incident_id"] and event["trace_id"] == pre["trace_id"]
        assert event["parent_event_id"] == (journal.events[index - 1]["event_id"] if index else None)
    steps = [event["data"]["step"] for event in journal.events]
    assert all(step in steps for step in ("pre_recovery_observation", "rca", "planner", "safety", "authorization",
                                          "executor_result", "post_recovery_observation", "verify", "memory"))
    event = json.loads(memory.path.read_text(encoding="utf-8"))
    assert event["data"]["recovered"] is True
    assert event["data"]["real_model"] is False and event["data"]["real_observation"] is False
    assert memory.retrieve("service_failure", "api")[0]["executed_action"]["target"] == "web"


@pytest.mark.parametrize("execute,approve", [(False, False), (False, True), (True, False)])
def test_flag_and_independent_approval_truth_table_never_calls_executor(rig, execute, approve):
    rig[2].confirm = lambda request, challenge: challenge if request["purpose"] == "model" or approve else "no"
    report = run(rig, execute_recovery=execute)
    assert not report["recovery_executed"] and not report["executor_called"]
    rig[5].assert_not_called()
    assert rig[1].restarts == [] and rig[1].injections == 0


def test_no_model_consent_means_no_provider_or_executor(rig):
    rig[2].confirm = lambda *args: None
    model = provider()
    report = run(rig, model, execute_recovery=True)
    model.complete.assert_not_called()
    rig[5].assert_not_called()
    assert report["model_calls"] == 0


@pytest.mark.parametrize("changes", [
    {"confidence": .69}, {"evidence": ["bad"]}, {"evidence": ["invented evidence unrelated to live metrics"]},
    {"suggested_action": {"action": "shell", "target": "web"}},
    {"suggested_action": {"action": "restart_service", "target": "postgres"}},
    {"affected_component": "redis"}, {"suggested_action": {"action": "no_action", "target": None}},
])
def test_model_rejections_are_fail_closed(rig, changes):
    report = run(rig, provider(**changes), execute_recovery=True)
    assert not report["executor_called"] and not report["recovery_verified"]
    rig[5].assert_not_called()


@pytest.mark.parametrize("raw", ["", "{}", "broken", "null"])
def test_bad_rca_has_no_rule_fallback_execution(rig, raw):
    model = Mock(complete=Mock(return_value=raw))
    report = run(rig, model, execute_recovery=True)
    assert report["recovery_action"]["action"] == "no_action"
    rig[5].assert_not_called()


def test_safety_rejection_is_independent_of_model(rig):
    with patch("reops_agent.advisory.check_action", return_value={"allowed": False, "reason": "denied"}):
        report = run(rig, execute_recovery=True)
    assert not report["diagnosis_validated"]
    rig[5].assert_not_called()


@pytest.mark.parametrize("change", ["container", "compose", "remote", "project", "self_healed", "new_fault", "trace"])
def test_environment_and_observation_changes_after_approval_refuse_execution(rig, change):
    backend = rig[1]
    def confirm(request, challenge):
        if request["purpose"] == "recovery":
            if change == "container": backend.scope["containers"]["api"] = "d" * 64
            elif change == "compose": backend.scope["compose_sha256"] = "e" * 64
            elif change == "remote": backend.scope["docker_endpoint"] = "tcp://remote:2375"
            elif change == "project": backend.scope["project"] = "other"
            elif change == "self_healed": backend.healthy = True
            elif change == "new_fault": backend.overrides.append(lambda value: value | {"services": {}})
            elif change == "trace": backend.overrides.append(lambda value: value | {"trace_id": "different"})
        return challenge
    rig[2].confirm = confirm
    report = run(rig, execute_recovery=True)
    assert not report["executor_called"] and backend.restarts == []
    rig[5].assert_not_called()


@pytest.mark.parametrize("changes", [
    {"request": {"method": "GET", "endpoint": "/users", "status_code": 503, "latency_ms": 1}},
    {"request": {"method": "GET", "endpoint": "/users", "status_code": 302, "latency_ms": 1}},
    {"services": {"api": {"status": "healthy"}}},
    {"services": {name: {"status": "unknown"} for name in ("api", "postgres", "redis")}},
    {"metrics": {"api_up": 1, "postgres_up": None, "redis_up": 1}},
    {"observation_id": "obs-unavailable-invalid"}, {"trace_id": "different"},
    {"timestamp": "2020-01-01T00:00:00Z"},
])
def test_fresh_verify_requires_real_complete_health_and_business_evidence(rig, changes):
    rig[1].post_changes = changes
    report = run(rig, execute_recovery=True)
    assert report["executor_called"] and not report["recovery_verified"]
    assert not json.loads(rig[4].path.read_text(encoding="utf-8"))["data"]["recovered"]


@pytest.mark.parametrize("failure", [TimeoutError(), RuntimeError("private-provider-data"), KeyboardInterrupt()])
def test_executor_exception_is_unknown_and_never_retried(rig, failure):
    rig[5].side_effect = lambda _: Mock(side_effect=failure)
    report = run(rig, execute_recovery=True)
    assert report["execution_outcome"] == "unknown" and not report["recovery_executed"]
    assert report["executor_called"] and not report["recovery_verified"]
    assert rig[5].call_count == 1
    validate("recovery_result", report["execution_result"])
    assert "private-provider-data" not in json.dumps(report)


def test_timeout_that_mutates_and_becomes_healthy_is_not_success(rig):
    def restart(target, **kwargs):
        rig[1].healthy = True
        rig[1].restarts.append(target)
        raise DockerBoundaryError("docker_timeout_state_uncertain", mutation_attempted=True)
    rig[1].restart = restart
    report = run(rig, execute_recovery=True)
    assert report["execution_attempted"] and report.get("system_observed_healthy"), report
    assert report["execution_outcome"] == "unknown" and not report["recovery_executed"]
    assert report["verification_status"] == "inconclusive" and not report["recovery_verified"]


def test_verify_exception_cannot_fallback_to_executor_health(rig):
    with patch("reops_agent.recovery_smoke.verify", side_effect=RuntimeError("private")):
        report = run(rig, execute_recovery=True)
    assert report["recovery_executed"] and not report["recovery_verified"]
    assert report["verification_status"] == "inconclusive"


def test_stale_executor_post_is_not_repaired_into_success_by_later_observation(rig):
    pre = rig[0]
    details = {"action": "restart_service", "target": "web", "mode": "real", "executed": True,
               "success": True, "docker_status": "restart_completed"}
    def execute(*args):
        rig[1].healthy = True
        return ExecutionOutcome("succeeded", 0, None, None, 1, deepcopy(pre), details)
    rig[5].side_effect = lambda _: execute
    report = run(rig, execute_recovery=True)
    assert report["system_observed_healthy"] and not report["recovery_verified"]


def test_memory_write_failure_preserves_execution_but_fails_delivery(rig):
    with patch.object(rig[4], "remember", side_effect=OSError("private")):
        report = run(rig, execute_recovery=True)
    assert report["recovery_verified"] and not report["memory_written"] and report["error"], report


def test_audit_failure_before_executor_is_fail_closed(rig):
    original = rig[3].record
    def record(stage, step, *args):
        if step == "executor_started": raise OSError("private")
        return original(stage, step, *args)
    rig[3].record = record
    report = run(rig, execute_recovery=True)
    assert not report["executor_called"] and rig[1].restarts == []


def test_sensitive_fields_never_enter_model_or_audit(rig, monkeypatch):
    secret = "offline-sensitive-model-password"
    monkeypatch.setenv("OTHER_SECRET", secret)
    rig[0]["logs"] = [{"source": "api", "message": secret}]
    model = provider(reasoning_summary="API stopped " + secret)
    report = run(rig, model, execute_recovery=True)
    sent = json.dumps(model.complete.call_args.args[0])
    assert secret not in sent and "containers" not in sent and "compose_file" not in sent
    assert secret not in json.dumps(report)
    assert secret not in rig[3].path.read_text(encoding="utf-8") and secret not in rig[4].path.read_text(encoding="utf-8")


@pytest.mark.parametrize("scenario", ["success", "denied", "executor_failure", "cleanup_failure"])
def test_experiment_cleanup_is_separate_and_cannot_rewrite_recovery(rig, scenario):
    pre, backend, gate, journal, memory, factory = rig
    backend.healthy = True
    if scenario == "denied":
        gate.confirm = lambda request, challenge: "no" if request["purpose"] == "recovery" else challenge
    if scenario in {"executor_failure", "cleanup_failure"}:
        factory.side_effect = lambda _: Mock(side_effect=TimeoutError())
    if scenario == "cleanup_failure": backend.restart = Mock(side_effect=TimeoutError())
    report = fault_recovery(backend, provider(), gate=gate, journal=journal, memory=memory,
        model_identifier="offline-test", execute_recovery=True, executor_factory=factory,
        verify_timeout=0, poll_interval=0)
    assert backend.injections == 1
    if scenario == "success":
        assert report["acceptance_passed"] and backend.restarts == ["web"]
    else:
        assert not report["acceptance_passed"] and not report["recovery_verified"]
        assert not json.loads(memory.path.read_text(encoding="utf-8"))["data"]["recovered"]
        assert report["cleanup_outcome"] == ("unknown" if scenario == "cleanup_failure" else "succeeded")
    if scenario == "denied": factory.assert_not_called()


@pytest.mark.parametrize("purpose", ["model", "experiment"])
def test_experiment_requires_model_and_fixture_consent_before_stop(rig, purpose):
    rig[1].healthy = True
    rig[2].confirm = lambda request, challenge: None if request["purpose"] == purpose else challenge
    model = provider()
    report = fault_recovery(rig[1], model, gate=rig[2], journal=rig[3], memory=rig[4],
        model_identifier="offline-test", execute_recovery=True, executor_factory=rig[5])
    assert rig[1].injections == 0 and rig[1].restarts == []
    model.complete.assert_not_called()


@pytest.mark.parametrize("args", [[], ["--execute-recovery"], ["--fault-smoke"]])
def test_cli_without_explicit_mode_never_calls_model_or_mutation(args, capsys, cli_runtime):
    backend, model, factory = Backend(True), provider(), Mock()
    with patch("reops_agent.recovery_smoke.NexentRCAProvider", side_effect=AssertionError("real model factory")):
        main(args, backend=backend, provider=model, executor_factory=factory)
    report = json.loads(capsys.readouterr().out)
    assert not report["executor_called"] and report["model_calls"] == 0
    assert backend.injections == 0 and backend.restarts == []
    model.complete.assert_not_called()
    factory.assert_not_called()
    assert not cli_runtime.exists()


def test_cli_environment_gate_is_not_human_authorization(rig, capsys, cli_runtime):
    config = NexentConfig("http://aigw.dlut.edu.cn/v1", "DeepSeek-V3.1-W8A8", "offline-key",
                          enable_real_model=True, allow_dlut_http=True)
    rig[2].confirm = lambda *args: None
    model = provider()
    with patch("reops_agent.recovery_smoke.NexentConfig.from_env", return_value=config):
        assert main(["--diagnose", "--execute-recovery"], backend=rig[1], gate=rig[2], provider=model,
                    executor_factory=rig[5]) == 1
    report = json.loads(capsys.readouterr().out)
    model.complete.assert_not_called()
    assert report["model_calls"] == 0 and rig[1].restarts == []
    assert (cli_runtime / "phase7d-audit.jsonl").is_file()
    assert not (cli_runtime / "phase7d-memory.jsonl").exists()


def test_cli_default_ledger_journal_and_memory_are_isolated(capsys, cli_runtime):
    config = NexentConfig("http://aigw.dlut.edu.cn/v1", "DeepSeek-V3.1-W8A8", "offline-key",
                          enable_real_model=True, allow_dlut_http=True)
    model, factory = provider(), Mock()
    # 正式 Gate + 离线批准替身，覆盖默认三种输出；没有真实 provider/执行器。
    with patch("reops_agent.recovery_smoke.NexentConfig.from_env", return_value=config), \
         patch("reops_agent.authorization.interactive_confirm", side_effect=lambda request, challenge: challenge):
        assert main(["--diagnose"], backend=Backend(), provider=model,
                    executor_factory=factory) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["model_calls"] == 1 and not report["executor_called"]
    assert not report["real_model"] and not report["real_observation"]
    model.complete.assert_called_once()
    factory.assert_not_called()
    assert (cli_runtime / "phase7d-authorizations.sqlite3").is_file()
    assert (cli_runtime / "phase7d-audit.jsonl").is_file()
    assert (cli_runtime / "phase7d-memory.jsonl").is_file()


@pytest.mark.parametrize("change", ["copied", "expired", "binding", "wrong_purpose", "different_gate"])
def test_grant_cannot_be_forged_expired_rebound_or_replayed(tmp_path, change):
    clock = [10]
    gate = AuthorizationGate(tmp_path / "ledger.db", confirm=lambda r, c: c, clock=lambda: clock[0])
    binding = {"action": "restart_service", "trace_id": "this-trace"}
    grant = gate.request("recovery", binding)
    purpose = "recovery"
    if change == "copied": grant = replace(grant)
    if change == "expired": clock[0] = 130
    if change == "binding": binding["trace_id"] = "other"
    if change == "wrong_purpose": purpose = "model"
    if change == "different_gate": gate = AuthorizationGate(tmp_path / "ledger.db", confirm=lambda r, c: c)
    with pytest.raises(AuthorizationError): gate.consume(grant, purpose, binding, operation_id="same-action")


def test_concurrent_consumption_and_process_restart_cannot_repeat_operation(tmp_path):
    ledger = tmp_path / "ledger.db"
    gate = AuthorizationGate(ledger, confirm=lambda r, c: c)
    binding = {"action_id": "action-once"}
    grant = gate.request("recovery", binding)
    def consume(_):
        try:
            gate.consume(grant, "recovery", binding, operation_id="action-once")
            return True
        except AuthorizationError: return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(consume, range(4))) == 1
    later = AuthorizationGate(ledger, confirm=lambda r, c: c)
    new = later.request("recovery", binding)
    with pytest.raises(AuthorizationError): later.consume(new, "recovery", binding, operation_id="action-once")


def test_noninteractive_confirmation_cannot_be_piped_or_assumed():
    with patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as read:
        assert interactive_confirm({}, "challenge") is None
    read.assert_not_called()


@pytest.mark.parametrize("args", [["--run"], ["--cleanup"]])
def test_legacy_smoke_cannot_bypass_new_recovery_authorization(args, capsys):
    from reops_agent.smoke import docker_recovery
    backend = Mock()
    assert docker_recovery.main(args, backend=backend) == 2
    backend.restart.assert_not_called()
    backend.inject_web_failure_test_only.assert_not_called()
    backend.observe.assert_not_called()


def test_bare_live_executor_requires_phase7d_authorized_adapter(rig):
    from reops_agent.planner import plan_recovery
    from reops_agent.pipeline import diagnose
    backend = LocalDocker()
    with patch.object(backend, "restart") as restart, patch.object(backend, "container") as container:
        result = DockerRecoveryExecutor(dry_run=False, backend=backend)(plan_recovery(diagnose(rig[0])), rig[0])
    assert result.status == "rejected" and result.execution["executed"] is False
    restart.assert_not_called()
    container.assert_not_called()


@pytest.mark.parametrize("operation", ["restart", "inject"])
def test_bound_container_replacement_is_rejected_at_command_boundary(operation):
    backend = LocalDocker()
    with patch.object(backend, "container", return_value=("b" * 64, {})), patch.object(backend, "_run") as command:
        with pytest.raises(DockerBoundaryError):
            if operation == "restart":
                backend.restart("web", expected_container_id="a" * 64)
            else:
                backend.inject_web_failure_test_only(expected_container_id="a" * 64)
    command.assert_not_called()


@pytest.mark.parametrize("outcome", [None, {"status": "success"}, "bad"])
def test_invalid_executor_output_is_unknown_without_success_memory(rig, outcome):
    rig[5].side_effect = lambda _: Mock(return_value=outcome)
    report = run(rig, execute_recovery=True)
    assert report["execution_outcome"] == "unknown" and not report["recovery_verified"]
    assert not json.loads(rig[4].path.read_text(encoding="utf-8"))["data"]["recovered"]


def test_failed_command_followed_by_healthy_system_does_not_credit_recovery(rig):
    details = {"action": "restart_service", "target": "web", "mode": "real", "executed": True,
               "success": False, "docker_status": "command_failed"}
    def execute(action, previous):
        rig[1].healthy = True
        return ExecutionOutcome("failed", 1, None, None, 1, observation(True, previous), details)
    rig[5].side_effect = lambda _: execute
    report = run(rig, execute_recovery=True)
    assert report["execution_outcome"] == "failed" and report["system_observed_healthy"]
    assert not report["recovery_verified"] and report["verification_status"] == "inconclusive"


def test_two_fresh_successive_measurements_are_required(rig):
    def restart(target, **kwargs):
        rig[1].restarts.append(target)
        rig[1].healthy = True
        # Executor sees health; first independent sample does too, next fails.
        rig[1].overrides = [lambda value: value, lambda value: value,
                           lambda value: observation(False, value)]
    rig[1].restart = restart
    report = run(rig, execute_recovery=True)
    assert report["recovery_executed"] and not report["recovery_verified"]


def test_same_trace_reentry_cannot_call_model_or_executor_again(rig):
    assert run(rig, execute_recovery=True)["recovery_verified"]
    model = provider()
    report = run(rig, model, execute_recovery=True)
    assert not report["executor_called"]
    model.complete.assert_not_called()
    assert rig[1].restarts == ["web"]


def test_expired_recovery_consent_does_not_call_executor(rig):
    clock = [10]
    rig[2].clock = lambda: clock[0]
    def confirm(request, challenge):
        if request["purpose"] == "recovery":
            original = rig[1].observe
            def observe(previous):
                value = original(previous)
                clock[0] += 121
                return value
            rig[1].observe = observe
        return challenge
    rig[2].confirm = confirm
    report = run(rig, execute_recovery=True)
    assert not report["executor_called"] and rig[1].restarts == []


def test_ledger_failure_is_fail_closed_before_model_and_recovery(rig):
    rig[2].ledger.mkdir()
    model = provider()
    report = run(rig, model, execute_recovery=True)
    assert report["error"] and not report["executor_called"]
    model.complete.assert_not_called()


def test_nested_command_payload_never_reaches_executor(rig):
    from reops_agent.advisory import diagnose_advisory
    core = diagnose_advisory(rig[0], provider())
    core["recovery_action"]["extension"] = {"nested": {"shell": "forbidden"}}
    with patch("reops_agent.recovery_smoke.diagnose_advisory", return_value=core):
        report = run(rig, execute_recovery=True)
    assert not report["executor_called"]
    rig[5].assert_not_called()


@pytest.mark.parametrize("field", ["action", "target", "incident_id", "trace_id", "action_id"])
def test_authorization_each_action_identity_field_is_bound(tmp_path, field):
    gate = AuthorizationGate(tmp_path / "ledger.db", confirm=lambda r, c: c)
    binding = {"action": "restart_service", "target": "web", "incident_id": "incident-a",
               "trace_id": "trace-a", "action_id": "action-a"}
    grant = gate.request("recovery", binding)
    binding[field] = "different"
    with pytest.raises(AuthorizationError):
        gate.consume(grant, "recovery", binding, operation_id="action-a")


def test_expiry_rechecked_after_ledger_lock(tmp_path):
    times = iter([0, 0, 121])
    gate = AuthorizationGate(tmp_path / "ledger.db", confirm=lambda r, c: c,
                             clock=lambda: next(times))
    grant = gate.request("recovery", {})
    with pytest.raises(AuthorizationError, match="expired_before_reservation"):
        gate.consume(grant, "recovery", {}, operation_id="action-a")
    with sqlite3.connect(gate.ledger) as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0


def test_executor_cannot_reuse_pre_execution_observation(rig):
    latest = []
    original = rig[1].observe
    def observe(previous):
        value = original(previous)
        latest.append(value)
        return value
    rig[1].observe = observe
    def execute(action, previous):
        rig[1].healthy = True
        return ExecutionOutcome("succeeded", 0, None, None, 1, latest[-1],
            {"action": "restart_service", "target": "web", "mode": "real", "executed": True,
             "success": True, "docker_status": "restart_completed"})
    rig[5].side_effect = lambda _: execute
    report = run(rig, execute_recovery=True)
    assert not report["recovery_verified"]
    assert report["error"] == "executor_post_observation_invalid"


def test_phase7c_live_fault_entry_cannot_bypass_experiment_authorization(capsys):
    from reops_agent.real_smoke import fault_smoke, main as old_main
    backend = LocalDocker()
    with patch.object(backend, "observe") as observe, patch.object(backend, "restart") as restart, \
            patch.object(backend, "inject_web_failure_test_only") as inject:
        with pytest.raises(DockerBoundaryError, match="authorized_entry_required"):
            fault_smoke(backend, provider(), memory=None)
        assert old_main(["--fault-smoke"], backend=backend) == 2
    observe.assert_not_called()
    restart.assert_not_called()
    inject.assert_not_called()


@pytest.mark.parametrize("evidence", [["api_up=1 contradicts stopped api"],
                                     ["api_up=0 api stopped; postgres_up=0"],
                                     ["api_up=0 api stopped; redis_up:0"]])
def test_explicit_metric_evidence_cannot_contradict_observation(rig, evidence):
    report = run(rig, provider(evidence=evidence), execute_recovery=True)
    assert report["rejection_reason"] == "evidence_contradicts_observation"
    assert not report["diagnosis_validated"] and not report["executor_called"]
    rig[5].assert_not_called()


def test_healthy_samples_after_positive_verify_deadline_cannot_pass(rig):
    from reops_agent.recovery_smoke import run_recovery
    clock=[10]
    def execute(action, previous):
        rig[1].healthy=True
        return ExecutionOutcome('succeeded',0,None,None,1,observation(True,previous),
            {'action':'restart_service','target':'web','mode':'real','executed':True,
             'success':True,'docker_status':'restart_completed'})
    rig[5].side_effect=lambda _:execute
    original=rig[1].observe
    def observe(previous):
        result=original(previous)
        if rig[1].healthy:clock[0]+=2
        return result
    rig[1].observe=observe
    with patch('reops_agent.recovery_smoke.time.monotonic',side_effect=lambda:clock[0]):
        report=run_recovery(rig[0],provider(),backend=rig[1],gate=rig[2],journal=rig[3],memory=rig[4],
            executor_factory=rig[5],execute_recovery=True,verify_timeout=1,poll_interval=0)
    assert report['recovery_executed'] and not report['recovery_verified']
    assert report['verification_status']=='inconclusive'


def test_real_source_cannot_use_zero_verification_budget(rig):
    report=run(rig,execute_recovery=True,real_observation=True)
    assert report['model_calls']==0 and not report['executor_called']


@pytest.mark.parametrize('settings', [
    {'verify_timeout':-1}, {'verify_timeout':float('nan')}, {'verify_timeout':True},
    {'poll_interval':2}, {'poll_interval':False}, {'real_observation':True,'verify_timeout':0},
    {'real_observation':'false'}, {'real_model':1},
])
def test_invalid_experiment_settings_are_rejected_before_approval_or_injection(rig,settings):
    backend=rig[1];backend.healthy=True
    backend.observe=Mock(wraps=backend.observe)
    rig[2].request=Mock(wraps=rig[2].request)
    model=provider()
    report=fault_recovery(backend,model,gate=rig[2],journal=rig[3],memory=rig[4],
        model_identifier='offline-test',execute_recovery=True,executor_factory=rig[5],**settings)
    assert not report['fault_injection_attempted'] and backend.injections==0
    assert report['cleanup_outcome']=='not_run'
    backend.observe.assert_not_called()
    rig[2].request.assert_not_called()
    model.complete.assert_not_called()
    rig[5].assert_not_called()


@pytest.mark.parametrize('entry',['run','fault'])
def test_live_backend_cannot_claim_offline_observation_source(rig,entry):
    backend=LocalDocker();model=provider()
    with patch.object(backend,'observe') as observe, patch.object(backend,'recovery_scope') as scope:
        if entry=='run':
            report=run_recovery(rig[0],model,backend=backend,gate=rig[2],journal=rig[3],
                memory=rig[4],execute_recovery=True)
        else:
            report=fault_recovery(backend,model,gate=rig[2],journal=rig[3],memory=rig[4],
                model_identifier='offline-test',execute_recovery=True)
    observe.assert_not_called();scope.assert_not_called();model.complete.assert_not_called()
    assert report['model_calls']==0 and not report['executor_called']


def test_live_provider_cannot_claim_offline_model_source(rig):
    from reops_agent.nexent_provider import NexentRCAProvider
    # Do not construct SDK/config or touch credentials for this source test.
    model=object.__new__(NexentRCAProvider)
    with patch.object(NexentRCAProvider,'complete') as complete:
        report=run(rig,model,execute_recovery=True)
    complete.assert_not_called()
    assert report['model_calls']==0 and not report['executor_called']


@pytest.mark.parametrize('budget',[True,False,float('nan'),float('inf'),-1,61])
def test_executor_timeout_rejects_non_numeric_or_out_of_bounds_values(budget):
    with pytest.raises(ValueError):DockerRecoveryExecutor(backend=Backend(),verify_timeout=budget)


def test_positive_verify_window_does_not_start_another_observation_after_expiry(rig):
    clock=[0]
    original=rig[1].observe
    post_calls=[]
    def observe(previous):
        result=original(previous)
        if rig[1].restarts:post_calls.append(result['observation_id'])
        return result
    rig[1].observe=observe
    # First independent healthy sample arrives in time; waiting exhausts the window.
    with patch('reops_agent.recovery_smoke.time.monotonic',side_effect=lambda:clock[0]), \
            patch('reops_agent.recovery_smoke.time.sleep',side_effect=lambda _:clock.__setitem__(0,2)):
        report=run_recovery(rig[0],provider(),backend=rig[1],gate=rig[2],journal=rig[3],memory=rig[4],
            executor_factory=rig[5],execute_recovery=True,verify_timeout=1,poll_interval=1)
    # Includes executor snapshot plus exactly one independent sample.
    assert len(post_calls)==2
    assert not report['recovery_verified'] and report['verification_status']=='inconclusive'
    assert report['budgets']['whole_pipeline_hard_deadline'] is False


def test_corrupt_history_cannot_trigger_provider_or_executor(rig):
    rig[4].path.write_text('{invalid',encoding='utf-8')
    model=provider()
    report=run(rig,model,execute_recovery=True)
    model.complete.assert_not_called();rig[5].assert_not_called()
    assert report['model_calls']==0 and rig[1].restarts==[]
    assert report['error']=='recovery_pipeline_failed' and not report['memory_written']
