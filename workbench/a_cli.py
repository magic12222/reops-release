"""Explicit local operator entry; default check has no target mutations."""

import argparse
import json
from uuid import uuid4

from reops_agent.authorization import AuthorizationGate
from .a_actions import RecoveryTool
from .a_docker import ROOT
from .a_monitor import TargetMonitor, now


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="Sample until operator pauses/quits")
    args = parser.parse_args(argv)
    monitor = TargetMonitor()
    try:
        monitor.select()
    except Exception:
        print(json.dumps({"status": "not_connected", "error": "target_unavailable_check_docker_and_ownership"}))
        return 2
    try:
        if not args.watch:
            print(monitor.read_targets().model_dump_json(indent=2))
            return 0
        monitor.start()
        print("Sampling only. Commands: status, observation, pause, start, recover, quit")
        while True:
            command = input("A> ").strip()
            if command == "quit":
                break
            try:
                if command == "pause":
                    monitor.pause()
                elif command == "start":
                    monitor.start()
                elif command == "observation":
                    print(json.dumps(monitor.observe("incident-cli-" + uuid4().hex,
                                                     "trace-cli-" + uuid4().hex), indent=2))
                elif command == "recover":
                    action = {"schema_version": "1.0", "action_id": "act-cli-" + uuid4().hex,
                              "incident_id": "incident-cli-" + uuid4().hex,
                              "trace_id": "trace-cli-" + uuid4().hex, "diagnosis_id": "diag-cli-operator",
                              "timestamp": now(), "action": "start_service", "target": "web",
                              "reason": "Operator requests one fixed start of the externally stopped API",
                              "expected_success": 0.5, "estimated_cost": 0.1, "risk": 0.1,
                              "requires_approval": False, "parameters": {}}
                    tool = RecoveryTool(monitor)
                    gate = AuthorizationGate(ROOT / "runtime/a-workbench-authorizations.sqlite3")
                    grant = gate.request("recovery", tool.prepare(action))
                    print(json.dumps(tool.execute(action, gate=gate, grant=grant), indent=2))
                elif command != "status":
                    print("Unknown command")
                    continue
                print(monitor.read_targets().model_dump_json(indent=2))
            except Exception:
                print("Operation rejected or unavailable; inspect state before retrying")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        monitor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
