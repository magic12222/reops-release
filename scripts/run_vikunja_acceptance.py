"""Vikunja 实机连接恢复验收；一次终端批准覆盖固定整轮，不调用模型。"""
import argparse
import json
import sys
import time
from uuid import uuid4

from workbench.vikunja_authorization import VikunjaRunGate
from reops_agent.contracts import PROJECT_ROOT
from workbench.a_monitor import now
from workbench.vikunja_actions import VikunjaRecoveryTool
from workbench.vikunja_target import VikunjaDocker, VikunjaMonitor, stopped_database
from scripts.vikunja_baseline import BusinessSession, baseline


def save(path, report):
    # Only sanitized, structured measurements enter the report.
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def run_acceptance(*, backend, gate, b_store=None):
    if not isinstance(gate, VikunjaRunGate):
        raise ValueError("explicit_vikunja_run_gate_required")
    current = backend.inspect()
    if not current.running or not current.postgres_running:
        raise ValueError("healthy_containers_required")
    session = BusinessSession()
    monitor = VikunjaMonitor(session, backend=backend)
    directory = PROJECT_ROOT / "runtime/vikunja-evidence" / uuid4().hex
    directory.mkdir(parents=True)
    report = {"source": "real", "kind": "infrastructure_connection_acceptance",
        "started_at": now(), "model_calls": 0, "b_agent_closed_loop": False,
        "fault_injection_attempted": False, "recovery_verified": False,
        "cleanup_extra_starts": 0, "passed": False, "authorization_mode": "single_run"}
    identity = current.identity
    context = {"incident_id": "incident-vikunja-" + uuid4().hex, "trace_id": "trace-vikunja-" + uuid4().hex}
    report.update(context)
    try:
        report["baseline"] = baseline(session)
        if not report["baseline"]["passed"] or not backend.sql_probe(identity):
            raise ValueError("business_baseline_failed")
        # The baseline probe is distinct from the post-recovery write probe.
        session.probe_id = session.probe_title = None
        monitor.select()
        monitor.start()
        report["scope"] = identity.binding()
        binding = {"scope": report["scope"], **context,
            "business": {"project_id": session.project_id, "task_id": session.task_id},
            "operation": "stop_postgres_for_connection_acceptance", "max_stops": 1,
            "max_recovery_starts": 1, "necessary_cleanup_max_starts": 1,
            "app_restart_allowed": False, "model_calls": 0,
            "authorization_mode": "single_run", "allowed_recovery": "start_service(postgres)"}
        save(directory / "request.json", binding)
        print(json.dumps({"evidence_directory": str(directory), "next": "original_experiment_authorization"}), flush=True)
        grant = gate.request("experiment", binding)
        fresh = backend.inspect()
        if fresh != current or not backend.sql_probe(identity) or session.read() != (200, True):
            raise ValueError("scope_or_baseline_changed_before_stop")
        report["run_authorization"] = gate.consume(grant, "experiment", binding,
            operation_id=context["trace_id"] + ":stop")
        # Fixed full ID, pinned local daemon; no Compose operation or arbitrary command.
        report["fault_injection_attempted"] = True
        backend._run(["stop", "--time", "5", identity.postgres_id], endpoint=identity.endpoint, timeout=30)
        report["observation"] = monitor.observe(**context)
        if not stopped_database(report["observation"]):
            raise ValueError("stopped_database_business_failure_not_confirmed")
        if b_store is not None:
            from workbench.b_vikunja import run_approved_recovery
            report.update(run_approved_recovery(b_store, monitor, gate, report["observation"], context))
            report["kind"] = "b_agent_recovery_acceptance"
            report["app_restart_observed"] = backend.inspect().app_started_at != current.app_started_at
            report["passed"] = report["passed"] and not report["app_restart_observed"]
        else:
            action = {"schema_version": "1.0", **context, "action_id": "action-vikunja-" + uuid4().hex,
                "diagnosis_id": "diagnosis-vikunja-" + uuid4().hex, "timestamp": now(),
                "action": "start_service", "target": "postgres", "reason": "Confirmed stopped database and failed task request",
                "expected_success": .8, "estimated_cost": .1, "risk": .1,
                "requires_approval": False, "parameters": {}}
            report["diagnosis_source"] = "rule_infrastructure_acceptance"
            report["recovery_action"] = action
            save(directory / "report.json", report)
            tool = VikunjaRecoveryTool(monitor)
            recovery_binding = tool.prepare(action)
            recovery_grant = gate.request("recovery", recovery_binding)
            report["execution_result"] = tool.execute(action, gate=gate, grant=recovery_grant)
            if report["execution_result"]["execution_status"] != "succeeded":
                raise ValueError("database_start_not_confirmed")
            deadline = time.monotonic() + 45
            samples = []
            while time.monotonic() < deadline:
                sample = monitor.observe(**context)
                after = backend.inspect()
                if (sample["target_health"] == "healthy" and after.identity == identity
                        and after.app_started_at == current.app_started_at and backend.sql_probe(identity)):
                    if not samples:
                        if not session.write_probe() or not session.read_probe():
                            raise ValueError("new_task_write_readback_failed")
                    elif not session.read_probe():
                        raise ValueError("second_readback_failed")
                    sample["business"].update(database_sql_valid=True, probe_read_valid=True,
                        write_valid=len(samples) == 0, probe_id=session.probe_id)
                    samples.append(sample)
                    if len(samples) == 2:
                        break
                elif samples:
                    raise ValueError("business_verification_not_consecutive")
                time.sleep(1)
            report["verify_observations"] = samples
            report["recovery_verified"] = len(samples) == 2 and samples[0]["observation_id"] != samples[1]["observation_id"]
            report["app_restart_observed"] = backend.inspect().app_started_at != current.app_started_at
            report["passed"] = report["recovery_verified"] and not report["app_restart_observed"]
    except BaseException as error:
        report["error_type"] = type(error).__name__
        report["passed"] = False
    finally:
        # The experiment binding explicitly includes necessary independent restoration.
        # Cleanup cannot turn a failed recovery/verification into a success.
        try:
            if report["fault_injection_attempted"]:
                final = backend.inspect()
                if final.identity != identity:
                    raise ValueError("cleanup_scope_changed")
                if not final.postgres_running:
                    report["cleanup_extra_starts"] = 1
                    backend.start(identity)
                cleanup_deadline = time.monotonic() + 45
                while time.monotonic() < cleanup_deadline:
                    if session.read() == (200, True) and backend.sql_probe(identity):
                        report["final_business_healthy"] = True
                        break
                    time.sleep(1)
                if not report.get("final_business_healthy"):
                    raise ValueError("cleanup_health_unconfirmed")
        except BaseException as error:
            report.update(cleanup_error_type=type(error).__name__, passed=False)
        try:
            monitor.close()
        finally:
            session.close()
            report["finished_at"] = now()
            save(directory / "report.json", report)
    print(json.dumps({"passed": report["passed"], "evidence_directory": str(directory),
        "model_calls": 0, "fault_injection_attempted": report["fault_injection_attempted"],
        "recovery_verified": report["recovery_verified"], "cleanup_extra_starts": report["cleanup_extra_starts"]}))
    return {**report, "evidence_directory": str(directory)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="一次整轮批准；网页入口不需要复制口令")
    args = parser.parse_args()
    backend = VikunjaDocker()
    if not args.run:
        current = backend.inspect()
        print(json.dumps({"scope": current.identity.binding(), "fault_injected": False,
            "app_running": current.running, "postgres_running": current.postgres_running}))
        return 0
    if not sys.stdin.isatty():
        raise ValueError("original_interactive_terminal_required")
    report = run_acceptance(backend=backend,
        gate=VikunjaRunGate(PROJECT_ROOT / "runtime/vikunja-authorizations.sqlite3"))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}))
        raise SystemExit(1) from None
