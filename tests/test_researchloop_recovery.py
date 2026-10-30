"""数据库场景离线状态机：替身/临时库，不访问Docker、模型或真实业务。"""
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from reops_agent.authorization import AuthorizationGate
from reops_agent.docker_executor import now
from reops_agent.memory import RecoveryMemory
from reops_agent.researchloop_backend import healthy, stopped_database
from reops_agent.researchloop_recovery import run_database, success_evidence, experience
from reops_agent.trace_journal import TraceJournal


class Backend:
    def __init__(self):
        self.running = True
        self.operations = []
        self.business = SimpleNamespace(project_id="fixture-project", project_db_id=1, owner=1,
            write_probe=lambda suffix: True, read_probe=lambda suffix: True)
        self.fail_restart = False
        self.fail_verify = False

    def scope(self):
        return {"project": "reops-researchloop-demo", "containers": {"api": "a"*64, "postgres": "b"*64},
                "deployment_sha256": "fixture-version", "required_services": ["api", "postgres"]}

    def observe(self, ctx):
        stopped = not self.running
        return {"schema_version": "1.0", **ctx, "observation_id": "obs-fixture-" + uuid4().hex,
            "timestamp": now(), "system": {"name": "fixture", "environment": "offline"},
            "services": {"api": {"status": "healthy", "message": "health probe healthy"},
                "postgres": {"status": "unhealthy" if stopped else "healthy",
                             "message": "stopped" if stopped else "health probe healthy"}},
            "metrics": {"api_up": 1, "postgres_up": int(not stopped)}, "logs": [],
            "request": {"method": "GET", "endpoint": "/api/projects/{project_id}", "status_code": 503 if stopped else 200},
            "business": {"project_id": self.business.project_id, "project_db_id": 1, "owner_user_id": 1,
                "api_alive": True, "read_valid": not stopped and not (self.fail_verify and self.operations)}}

    def sql_probe(self, scope):
        return self.running

    def container(self, name):
        return "b"*64, {"Status": "running" if self.running else "exited", "Running": self.running}, "image"

    def mutate(self, operation, scope):
        self.operations.append(operation)
        if operation == "restart" and self.fail_restart and self.operations.count("restart") == 1:
            raise RuntimeError("fixture unknown mutation")
        self.running = operation == "restart"


class Provider:
    def __init__(self):
        self.calls = 0
        self.history = None

    def complete(self, request, *, timeout_seconds):
        self.calls += 1
        self.history = request["recovery_evidence"]
        assert "business" not in request and "fixture-project" not in json.dumps(request)
        return json.dumps({"suspected_root_cause": "postgres_service_down", "affected_component": "postgres",
            "confidence": .97, "evidence": ["postgres_up=0; postgres stopped"],
            "reasoning_summary": "fixture database stopped", "suggested_action": {
                "action": "restart_service", "target": "postgres"}})


def run(tmp_path, *, backend=None, provider=None, confirm=None, memory=None, fast=False):
    ctx = {"incident_id": "incident-fixture-" + uuid4().hex, "trace_id": "trace-fixture-" + uuid4().hex}
    backend, provider = backend or Backend(), provider or Provider()
    purposes = []
    def approval(request, challenge):
        purposes.append(request["purpose"])
        return confirm(request, challenge) if confirm else challenge
    gate = AuthorizationGate(tmp_path / "grants.sqlite3", confirm=approval)
    journal = TraceJournal(ctx, tmp_path / "audit.jsonl")
    memory = memory or RecoveryMemory(tmp_path / "memory.jsonl")
    report = run_database(backend, provider, gate=gate, journal=journal, memory=memory,
                          model_identifier="fixture-model", execute=True, fast_path=fast, verify_timeout=1.5)
    return report, backend, provider, purposes, memory


def test_cold_real_path_contract_with_offline_fixtures(tmp_path):
    report, backend, provider, purposes, memory = run(tmp_path)
    assert report["acceptance_passed"] and success_evidence(report)
    assert backend.operations == ["stop", "restart"]
    assert provider.calls == report["model_calls"] == 1
    assert purposes == ["experiment", "model", "recovery"]
    assert report["repair_usage"] is None and report["cleanup_extra_restarts"] == 0
    assert len(memory._read_events()) == 1
    assert memory._read_events()[0]["data"]["model_calls"] == 1
    assert set(report["observation"]["services"]) == {"api", "postgres"}


def test_second_incident_memory_fast_path_keeps_fresh_authorization(tmp_path):
    first, _, _, _, memory = run(tmp_path)
    second, backend, provider, purposes, _ = run(tmp_path, memory=memory, fast=True)
    assert second["acceptance_passed"]
    assert second["incident_id"] != first["incident_id"]
    assert second["diagnosis_source"] == "memory/rule-supported"
    assert second["memory_hit_event_ids"] == [first["event_id"]]
    assert second["recovery_action"]["decision_basis"]["experience_fast_path"] is True
    assert purposes == ["experiment", "recovery"]
    assert backend.operations == ["stop", "restart"] and provider.calls == second["model_calls"] == 0
    assert second["repair_usage"] == {"input_tokens": 0, "output_tokens": 0, "source": "no_model_calls"}
    assert {x["observation_id"] for x in first["verify_observations"]}.isdisjoint(
        x["observation_id"] for x in second["verify_observations"])


def test_memory_assisted_planner_still_calls_model_without_fast_flag(tmp_path):
    first, _, _, _, memory = run(tmp_path)
    second, _, provider, purposes, _ = run(tmp_path, memory=memory)
    assert second["acceptance_passed"] and provider.calls == 1
    assert provider.history and second["memory_hit_event_ids"] == [first["event_id"]]
    assert "model" in purposes


@pytest.mark.parametrize("purpose", ["experiment", "model", "recovery"])
def test_rejection_no_unauthorized_recovery_and_independent_cleanup(tmp_path, purpose):
    def confirm(request, challenge):
        return None if request["purpose"] == purpose else challenge
    report, backend, provider, _, _ = run(tmp_path, confirm=confirm)
    assert not report["acceptance_passed"] and backend.running
    if purpose in {"experiment", "model"}:
        assert backend.operations == [] and provider.calls == 0
    else:
        assert backend.operations == ["stop", "restart"]
        assert report["cleanup_extra_restarts"] == 1 and not report["recovery_verified"]
        assert provider.calls == (1 if purpose == "recovery" else 0)


@pytest.mark.parametrize("field", ["version", "api_down", "healthy_db", "missing_business", "redis", "bad_memory"])
def test_fast_path_admission_rejects_changed_or_missing_evidence(tmp_path, field):
    first, _, _, _, memory = run(tmp_path)
    backend = Backend()
    if field == "version":
        scope = backend.scope()
        scope["deployment_sha256"] = "changed"
        backend.scope = lambda: scope
        assert experience(memory, scope) == []
        report, _, provider, purposes, _ = run(tmp_path, backend=backend, memory=memory, fast=True)
        assert report["acceptance_passed"] and provider.calls == 1 and "model" in purposes
    elif field == "bad_memory":
        memory.path.write_text('{"broken":true}\n', encoding="utf-8")
        report, backend, provider, _, _ = run(tmp_path, backend=backend, memory=memory, fast=True)
        assert not report["acceptance_passed"] and backend.operations == [] and provider.calls == 0
    else:
        sample = deepcopy(first["observation"])
        if field == "api_down":
            sample["metrics"]["api_up"] = 0
        elif field == "healthy_db":
            sample["services"]["postgres"]["status"] = "healthy"
        elif field == "missing_business":
            sample.pop("business")
        else:
            sample["services"]["redis"] = {"status": "healthy"}
        assert not stopped_database(sample)


def test_unknown_executor_is_not_replayed_as_recovery(tmp_path):
    backend = Backend()
    backend.fail_restart = True
    report, backend, _, _, _ = run(tmp_path, backend=backend)
    assert backend.operations == ["stop", "restart", "restart"]
    assert report["execution_outcome"] == "unknown" and not report["recovery_verified"]
    assert report["cleanup_outcome"] == "succeeded" and report["cleanup_extra_restarts"] == 1
    assert not report["acceptance_passed"]


def test_failed_business_write_cannot_be_recovered(tmp_path):
    backend = Backend()
    backend.business.write_probe = lambda suffix: False
    report, backend, _, _, memory = run(tmp_path, backend=backend)
    assert not report["recovery_verified"] and not report["acceptance_passed"]
    assert report["cleanup_outcome"] == "succeeded" and not memory.path.exists()


def test_success_requires_two_independent_owned_business_observations(tmp_path):
    first, _, _, _, _ = run(tmp_path)
    bad = deepcopy(first)
    bad["verify_observations"][1] = deepcopy(bad["verify_observations"][0])
    assert not success_evidence(bad)
    bad = deepcopy(first)
    bad["verify_observations"][1]["business"]["owner_user_id"] = 999
    assert not success_evidence(bad)


def test_fast_memory_never_overrides_current_safety_after_approval(tmp_path):
    _, _, _, _, memory = run(tmp_path)
    backend = Backend()
    def confirm(request, challenge):
        if request["purpose"] == "recovery":
            backend.running = True  # 等待期间目标已自愈，不能再重启。
        return challenge
    report, backend, provider, _, _ = run(tmp_path, backend=backend, confirm=confirm, memory=memory, fast=True)
    assert not report["recovery_verified"] and not report["executor_called"]
    assert backend.operations == ["stop"] and provider.calls == 0


def test_expired_experiment_during_model_approval_never_injects(tmp_path):
    clock = [0.0]
    def confirm(request, challenge):
        if request["purpose"] == "model":
            clock[0] = 121.0
        return challenge
    backend, provider = Backend(), Provider()
    ctx = {"incident_id": "fixture-expired", "trace_id": "fixture-expired"}
    report = run_database(backend, provider, gate=AuthorizationGate(tmp_path / "grants.sqlite3",
        confirm=confirm, clock=lambda: clock[0]), journal=TraceJournal(ctx, tmp_path / "audit.jsonl"),
        memory=RecoveryMemory(tmp_path / "memory.jsonl"), model_identifier="fixture", execute=True)
    assert not report["fault_injection_attempted"]
    assert backend.operations == [] and provider.calls == 0 and not report["acceptance_passed"]
