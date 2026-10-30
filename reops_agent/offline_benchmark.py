"""离线 fixture benchmark：复用 Phase 7D 编排，禁止网络和真实命令。"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

from .authorization import AuthorizationGate
from .contracts import PROJECT_ROOT, validate
from .docker_executor import DockerRecoveryExecutor, LocalDocker, now
from .memory import RecoveryMemory
from .nexent_provider import NexentRCAProvider
from .recovery_smoke import run_recovery
from .trace_journal import TraceJournal

FIXTURES = PROJECT_ROOT / "benchmarks/offline/scenarios.json"


def observation(state, previous=None):
    value = json.loads((PROJECT_ROOT / "shared/examples/healthy_observation.example.json").read_text(encoding="utf-8"))
    value.update(observation_id=f"obs-fixture-{uuid4()}", timestamp=now(), logs=[],
                 incident_id="incident-benchmark", trace_id=f"trace-benchmark-{uuid4()}")
    if previous:
        value.update({key: previous[key] for key in ("incident_id", "trace_id")})
    value["services"] = {name: {"status": "healthy", "message": "health probe healthy"}
                         for name in ("api", "postgres", "redis")}
    value["metrics"] = {name + "_up": 1 for name in value["services"]}
    value["request"] = {"method": "GET", "endpoint": "/users", "status_code": 200, "latency_ms": 1}
    if state == "api_down":
        value["services"]["api"].update(status="unhealthy", message="stopped")
        value["metrics"]["api_up"] = 0
        value["request"]["status_code"] = None
    elif state in {"postgres_down", "redis_abnormal"}:
        name = "postgres" if state == "postgres_down" else "redis"
        value["services"][name].update(status="unhealthy", message="stopped")
        value["metrics"][name + "_up"] = 0
        value["request"]["status_code"] = 503
    elif state in {"health_failure", "configuration_failure", "resource_failure"}:
        value["services"]["api"].update(status="unhealthy", message="health probe unhealthy")
        value["request"]["status_code"] = 503
    elif state == "ambiguous":
        for service in value["services"].values():
            service.update(status="unknown", message=None)
        value["metrics"] = {}
        value["request"]["status_code"] = None
    elif state != "healthy":
        raise ValueError("unknown_fixture_state")
    validate("observation", value)
    return value


class FixtureProvider:
    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = 0

    def complete(self, request, *, timeout_seconds):
        self.calls += 1
        if self.scenario.get("malformed"):
            return "{invalid-json"
        state = self.scenario["state"]
        component = "postgres" if state == "postgres_down" else "api"
        result = {"suspected_root_cause": "database_unavailable" if component == "postgres" else "api_service_down",
                  "affected_component": component, "confidence": .97,
                  "evidence": ["postgres_up=0 postgres stopped" if component == "postgres" else "api_up=0 api stopped"],
                  "reasoning_summary": "离线响应 fixture；不评估真实模型能力",
                  "suggested_action": {"action": "restart_service", "target": "postgres" if component == "postgres" else "web"}}
        if state == "healthy":
            result.update(suspected_root_cause="healthy", evidence=["all services healthy"],
                          suggested_action={"action": "no_action", "target": None})
        result.update(deepcopy(self.scenario.get("rca_override", {})))
        return json.dumps(result)


class FixtureBackend:
    def __init__(self, scenario):
        self.scenario, self.restarts, self.samples = scenario, 0, 0
        self.last = None
        self.scope = {"project": "reops-lab", "compose_file": str(PROJECT_ROOT / "docker-compose.yml"),
            "compose_sha256": hashlib.sha256((PROJECT_ROOT / "docker-compose.yml").read_bytes()).hexdigest(),
            "docker_endpoint": "npipe://offline-fixture", "business_url": "http://127.0.0.1:18000/users",
            "containers": {name: char * 64 for name, char in (("api", "a"), ("postgres", "b"), ("redis", "c"))}}

    def recovery_scope(self):
        return deepcopy(self.scope)

    def container(self, service):
        return self.scope["containers"][service], {}

    def restart(self, target, *, expected_container_id=None):
        if target != "web" or expected_container_id != self.scope["containers"]["api"]:
            raise AssertionError("fixture_scope_violation")
        self.restarts += 1

    def observe(self, previous):
        state = "healthy" if self.restarts else self.scenario["state"]
        mode = self.scenario.get("mode")
        if not self.restarts and mode == "transient":
            state = "healthy"
        if self.restarts:
            self.samples += 1
            if mode == "still_unhealthy" or mode == "inconsistent" and self.samples >= 3:
                state = "api_down"
            if mode == "observe_exception" and self.samples >= 2:
                raise RuntimeError("fixture_observation_unavailable")
            if mode == "reused_observation" and self.last:
                return deepcopy(self.last)
        value = observation(state, previous)
        self.last = deepcopy(value)
        return value


def _forbidden(*args, **kwargs):
    raise AssertionError("offline_benchmark_forbids_real_io")


def run_scenario(scenario, directory):
    pre = observation(scenario["state"])
    backend, provider = FixtureBackend(scenario), FixtureProvider(scenario)
    mode = scenario.get("mode")
    def confirm(request, challenge):
        return None if mode == "authorization_denied" and request["purpose"] == "recovery" else challenge
    gate = AuthorizationGate(directory / "grants.sqlite3", confirm=confirm)
    original_consume = gate.consume
    def consume(grant, purpose, binding, *, operation_id):
        if purpose == "recovery" and mode == "authorization_mismatch":
            binding = {**binding, "incident_id": "incident-other"}
        if purpose == "recovery" and mode == "authorization_replay":
            original_consume(grant, purpose, binding, operation_id=operation_id)
        return original_consume(grant, purpose, binding, operation_id=operation_id)
    gate.consume = consume
    journal = TraceJournal(pre, directory / "audit.jsonl")
    memory = RecoveryMemory(directory / "memory.jsonl")
    def factory(scoped):
        if mode in {"executor_timeout", "executor_exception"}:
            def fail(*args):
                raise TimeoutError() if mode == "executor_timeout" else RuntimeError("fixture_executor_exception")
            return fail
        return DockerRecoveryExecutor(dry_run=False, backend=scoped, verify_timeout=0)
    started = time.perf_counter()
    report = run_recovery(pre, provider, backend=backend, gate=gate, journal=journal, memory=memory,
        execute_recovery=scenario.get("execute", True), executor_factory=factory,
        verify_timeout=0, poll_interval=0)
    elapsed = (time.perf_counter() - started) * 1000
    actual = {key: report[key] for key in ("diagnosis_validated", "recovery_authorized", "executor_called",
              "recovery_executed", "recovery_verified", "model_calls", "verification_status")}
    actual.update(failure_detected=report.get("diagnosis", {}).get("failure_detected"),
                  plan=report.get("recovery_action", {}).get("action"),
                  target=report.get("recovery_action", {}).get("target"),
                  safety_allowed=report.get("safety", {}).get("allowed"),
                  rca_source=report.get("rca", {}).get("source"),
                  rca_root=report.get("rca", {}).get("result", {}).get("suspected_root_cause"))
    checks = {key: actual.get(key) == expected for key, expected in scenario["expected"].items()}
    event = json.loads(memory.path.read_text(encoding="utf-8")) if memory.path.exists() else None
    checks["memory_consistency"] = (event is None if actual["failure_detected"] is False else
        event is not None and event["data"]["recovered"] == report["recovery_verified"]
        and event["incident_id"] == pre["incident_id"] and event["trace_id"] == pre["trace_id"])
    checks["single_call_budget"] = provider.calls <= 1
    checks["no_false_recovery"] = not report["recovery_verified"] or scenario["expected"].get("recovery_verified") is True
    return {"case_id": scenario["id"], "category": scenario["category"], "expected": scenario["expected"],
            "actual": actual, "checks": checks, "passed": all(checks.values()),
            "fixture_restarts": backend.restarts, "harness_elapsed_ms": round(elapsed, 3),
            "real_model_calls": 0, "real_recovery_actions": 0,
            "token_api_cost": None, "pipeline_result": report}


def run_benchmark(fixtures=FIXTURES):
    scenarios = json.loads(Path(fixtures).read_text(encoding="utf-8"))
    ids = [case["id"] for case in scenarios]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) for name in ids):
        raise ValueError("duplicate_or_invalid_case_id")
    results = []
    with ExitStack() as stack:
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.create_connection", "subprocess.run",
                       "subprocess.Popen"):
            stack.enter_context(patch(target, side_effect=_forbidden))
        # Block imported class aliases too, including accidental backend/provider construction.
        stack.enter_context(patch.object(LocalDocker, "__init__", side_effect=_forbidden))
        stack.enter_context(patch.object(NexentRCAProvider, "__init__", side_effect=_forbidden))
        (PROJECT_ROOT / "runtime").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="benchmark-", dir=PROJECT_ROOT / "runtime") as temp:
            for case in scenarios:
                directory = Path(temp) / case["id"]
                directory.mkdir()
                results.append(run_scenario(case, directory))
    def accuracy(field):
        scores = [case["checks"][field] for case in results if field in case["expected"]]
        return {"correct": sum(scores), "total": len(scores), "rate": sum(scores) / len(scores) if scores else None}
    def conditional_rate(eligible, successful):
        subset = [case for case in results if eligible(case)]
        count = sum(successful(case) for case in subset)
        return {"count": count, "total": len(subset), "rate": count / len(subset) if subset else None}
    metrics = {label: accuracy(field) for label, field in (
        ("detection_accuracy", "failure_detected"), ("fixture_rca_accuracy", "rca_root"),
        ("plan_accuracy", "plan"), ("safety_decision_accuracy", "safety_allowed"))}
    metrics.update(
        recovery_success_rate=conditional_rate(lambda c: c["actual"]["executor_called"], lambda c: c["actual"]["recovery_executed"]),
        verify_success_rate=conditional_rate(lambda c: c["actual"]["recovery_executed"], lambda c: c["actual"]["recovery_verified"]),
        false_recovery_rate=conditional_rate(lambda c: not c["expected"]["recovery_verified"], lambda c: c["actual"]["recovery_verified"]),
        no_action_accuracy=conditional_rate(lambda c: not c["expected"]["executor_called"], lambda c: not c["actual"]["executor_called"]),
        unsafe_action_rejection_rate=conditional_rate(lambda c: c["category"] == "unsafe", lambda c: not c["actual"]["executor_called"]),
        fixture_model_call_count=sum(c["actual"]["model_calls"] for c in results),
        real_model_call_count=0, real_recovery_actions=0, token_api_cost=None,
        recovery_latency_ms=None,
        harness_elapsed_ms=sum(c["harness_elapsed_ms"] for c in results))
    return {"mode": "offline-fixture", "generated_at": now(), "fixture_sha256": hashlib.sha256(Path(fixtures).read_bytes()).hexdigest(),
            "case_count": len(results), "passed": sum(c["passed"] for c in results),
            "metrics": metrics, "cases": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "runtime/offline-benchmark.json")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if not output.is_relative_to(PROJECT_ROOT / "runtime"):
        parser.error("输出必须位于本项目 runtime 内")
    (PROJECT_ROOT / "runtime").mkdir(exist_ok=True)
    report = run_benchmark()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "case_count", "passed", "metrics")}, ensure_ascii=True, indent=2))
    return 0 if report["passed"] == report["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
