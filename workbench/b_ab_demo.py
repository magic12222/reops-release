"""Runnable A+B integration fixtures: real monitor/tool code with in-memory I/O only."""
import argparse
import json
from pathlib import Path

from reops_agent.authorization import AuthorizationGate
from .a_docker import Identity, Inspection, TargetError
from .a_monitor import TargetMonitor
from .b_service import WorkbenchHost


class Backend:
    def __init__(self):
        self.identity = Identity("unix:///offline-fixture.sock", "offline-engine", "a" * 64,
                                 "sha256:" + "b" * 64, "c" * 64)
        self.running, self.unavailable, self.uncertain = True, False, False
        self.starts = 0

    def inspect(self):
        if self.unavailable:
            raise TargetError("offline_observer_unavailable")
        return Inspection(self.identity, self.running, "running" if self.running else "exited")

    def start(self, expected):
        if expected != self.identity or self.running:
            raise TargetError("offline_wrong_target")
        self.starts += 1
        if self.uncertain:
            raise TargetError("offline_unknown_start", mutation_attempted=True)
        self.running = True


class Probe:
    def __init__(self):
        self.valid = True

    def read(self, trace_id):
        return True, 200, self.valid, 1.0


class Provider:
    offline_only = True
    def __init__(self):
        self.calls, self.fail = 0, False

    def complete(self, request, *, timeout_seconds):
        self.calls += 1
        if self.fail:
            raise RuntimeError("offline_model_unavailable")
        return json.dumps({"suspected_root_cause": "api_service_down", "affected_component": "api",
            "confidence": .95, "evidence": ["api_up=0; api stopped"],
            "reasoning_summary": "Offline model fixture diagnoses the observed stopped API.",
            "suggested_action": {"action": "restart_service", "target": "web"}})


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    summary = []
    for name in ("first-and-reuse", "observation-failure", "model-failure", "recovery-failure", "verification-failure"):
        path = directory / name
        backend, probe, provider = Backend(), Probe(), Provider()
        monitor = TargetMonitor(backend, probe, interval=.1)
        gate = AuthorizationGate(path / "authorizations.sqlite3", confirm=lambda request, challenge: challenge)
        host = WorkbenchHost(path, monitor=monitor, provider=provider, model="offline-api-provider",
                             execute=True, gate=gate, source="offline_fixture")
        try:
            host.start(watching=True)
            host.runtime.verify_timeout = .5
            host.runtime.verify_poll_interval = .001
            backend.running = False  # Simulated external stop; no Docker commands exist here.
            backend.unavailable = name == "observation-failure"
            backend.uncertain = name == "recovery-failure"
            provider.fail = name == "model-failure"
            probe.valid = name != "verification-failure"
            initial = monitor.observe("incident-a-fixture", "trace-a-fixture")
            if backend.unavailable:
                host.tick()
            else:
                host.runtime.notify("reops-lab-api", initial)
                host.runtime.notify("reops-lab-api", initial)
                if name == "first-and-reuse":
                    backend.running = False
                    host.runtime.notify("reops-lab-api", monitor.observe("incident-a-again", "trace-a-again"))
            snapshot = host.export()
            (directory / (name + ".snapshot.json")).write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
            with host.store.transaction() as db:
                events = [json.loads(row[0]) for row in db.execute("SELECT body FROM events ORDER BY rowid")]
            (directory / (name + ".events.json")).write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
            summary.append({"case": name, "statuses": [item.status for item in snapshot.incidents],
                            "fixture_provider_calls": provider.calls, "fixture_tool_calls": backend.starts})
        finally:
            host.close()
    report = {"source": "offline_fixture", "real_model_calls": 0, "real_recovery_actions": 0, "cases": summary}
    (directory / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="runtime/ab-offline")
    args = parser.parse_args()
    print(json.dumps(generate(args.output)))


if __name__ == "__main__":
    main()
