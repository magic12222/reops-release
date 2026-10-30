"""Explicit offline stateful acceptance. Never imported by the real adapter."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4

from reops_agent.authorization import AuthorizationGate
from reops_agent.executor import ExecutionOutcome
from .b_runtime import BRuntime, TargetPolicy
from .b_store import BStore, now, read_feed
from .contracts import Snapshot, Target


class OfflineA:
    """An in-memory fault simulator, with no subprocess, socket or model SDK."""
    offline_only = True

    def __init__(self):
        self.healthy, self.executions, self.scope_version = False, 0, 1
        self.fail_execution = self.fail_observe = self.fail_verify = False
        self.observations = []

    def scope(self, target_id):
        return {"target_id": target_id, "fixture_identity": self.scope_version}

    def observe(self, target_id, context):
        if self.fail_observe:
            raise RuntimeError("observer_private_context_must_not_escape")
        started, timestamp = now(), now()
        # Windows wall clock may repeat at sub-millisecond intervals. Wait for a real
        # clock tick instead of fabricating future timestamps for the fixture.
        while timestamp <= started:
            time.sleep(.001)
            timestamp = now()
        value = {"schema_version": "1.0", **context, "observation_id": "obs-offline-b-" + uuid4().hex,
            "timestamp": timestamp, "system": {"name": "b-offline-lab", "environment": "offline_fixture"},
            "services": {"api": {"status": "healthy", "message": "health probe healthy"},
                "postgres": {"status": "healthy" if self.healthy else "unhealthy",
                             "message": "health probe healthy" if self.healthy else "stopped"}},
            "metrics": {"api_up": 1, "postgres_up": int(self.healthy)}, "logs": [],
            "request": {"method": "GET", "endpoint": "/users", "status_code": 200 if self.healthy else 503}}
        self.observations.append(deepcopy(value))
        return value

    def execute(self, target_id, action, observation, authorization):
        if authorization.get("consumed") is not True or authorization.get("purpose") != "recovery":
            raise RuntimeError("offline_authorization_missing")
        assert (action["action"], action["target"]) == ("restart_service", "postgres")
        self.executions += 1
        if self.fail_execution:
            raise RuntimeError("tool_outcome_uncertain")
        self.healthy = not self.fail_verify
        return ExecutionOutcome("succeeded", 0, None, None, 1.0, deepcopy(observation),
            {"executed": True, "success": True, "action": action["action"], "target": action["target"]})


class OfflineProvider:
    offline_only = True

    def __init__(self, *, fail=False):
        self.calls, self.fail = 0, fail

    def complete(self, request, *, timeout_seconds):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider_private_error_must_not_escape")
        return json.dumps({"suspected_root_cause": "postgres_service_down", "affected_component": "postgres",
            "evidence": ["postgres_up=0; current PostgreSQL service stopped"], "confidence": .95,
            "reasoning_summary": "Offline fixture: stopped service and postgres_up=0 agree.",
            "suggested_action": {"action": "restart_service", "target": "postgres"}})


def setup(directory, *, provider=None, execute=True, confirm=None):
    store = BStore(Path(directory) / "state.sqlite3", source="offline_fixture")
    a = OfflineA()
    policy = TargetPolicy("b-offline-target", "b-offline-lab", "offline_fixture")
    # Auto-confirm is confined to the explicit in-memory fixture, never a real runtime default.
    gate = AuthorizationGate(Path(directory) / "authorization.sqlite3",
                             confirm=confirm or (lambda request, challenge: challenge))
    provider = provider if provider is not None else OfflineProvider()
    runtime = BRuntime(store, a, policy, gate=gate, provider=provider, model="offline-fixture-provider",
                       execute=execute, model_timeout=1)
    return runtime, a, provider


def sample(a, target="b-offline-target"):
    return a.observe(target, {"incident_id": "a-sample-" + uuid4().hex, "trace_id": "a-trace-" + uuid4().hex})


def snapshot(store):
    feed = read_feed(store.path, allow_fixture=True)
    target = Target(id="b-offline-target", name="B stateful offline target", runtime="docker",
        health="unknown", monitoring="paused", observed_at=None, components=[],
        allowed_actions=["restart_service(postgres)"])
    return Snapshot(schema_version="0.1", source="offline_fixture", generated_at=now(),
        a_status="ready", b_status=feed.status, targets=[target],
        incidents=feed.incidents, experiences=feed.experiences)


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for name in ("first-and-reuse", "observation-failure", "model-failure", "recovery-failure", "verification-failure"):
        runtime, a, provider = setup(directory / name,
            provider=OfflineProvider(fail=name == "model-failure"))
        if name == "observation-failure":
            runtime.observation_failed(runtime.policy.target_id)
        else:
            a.fail_execution = name == "recovery-failure"
            a.fail_verify = name == "verification-failure"
            initial = sample(a)
            runtime.notify(runtime.policy.target_id, initial)
            runtime.notify(runtime.policy.target_id, initial)
            if name == "first-and-reuse":
                a.healthy = False  # A second independent fault after verified recovery.
                runtime.notify(runtime.policy.target_id, sample(a))
        result = snapshot(runtime.store)
        (directory / (name + ".snapshot.json")).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        # Export native shared 1.0 events, not copies of the workbench example.
        with runtime.store.transaction() as db:
            events = [json.loads(row[0]) for row in db.execute("SELECT body FROM events ORDER BY rowid")]
        (directory / (name + ".events.json")).write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="runtime/b-workbench-offline")
    args = parser.parse_args()
    directory = generate(args.output)
    print(json.dumps({"source": "offline_fixture", "output": str(directory.resolve()), "real_model_calls": 0,
                      "real_recovery_actions": 0, "online_acceptance": "not_performed"}))


if __name__ == "__main__":
    main()
