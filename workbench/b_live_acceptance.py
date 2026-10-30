"""Bounded two-fault real acceptance; original human experiment/recovery Gates remain mandatory."""
import argparse
from copy import deepcopy
from pathlib import Path
import json
import sys
from uuid import uuid4

from reops_agent.authorization import AuthorizationGate, digest
from reops_agent.contracts import PROJECT_ROOT
from reops_agent.docker_executor import LocalDocker
from reops_agent.online_reports import replace_complete
from reops_agent.pipeline import diagnose
from .b_a_port import AAuthorization
from .b_a_policy import plan_a_start, verify_a_business
from .b_privacy import dumps
from .b_service import WorkbenchHost
from .b_store import now


def context(prefix):
    return {"incident_id": prefix + "-" + uuid4().hex, "trace_id": "trace-" + uuid4().hex}


def run_acceptance(host, injector, *, run=False):
    report = {"source": host.source, "started_at": now(), "acceptance_passed": False,
              "faults": [], "incidents": [], "cleanup": None, "error": None}
    if not run:
        return report
    scope = None

    def save():
        replace_complete(host.directory / "acceptance.json", dumps(report), artifact="json")

    try:
        host.start(watching=True)
        scope = host.runtime.port.scope("reops-lab-api")
        injection_scope = injector.recovery_scope()
        if injection_scope["containers"]["api"] != scope["container_id"]:
            raise ValueError("acceptance_injection_target_mismatch")
        baseline = host.monitor.observe(**context("incident-ab-baseline"))
        if not verify_a_business(baseline)[2]:
            raise ValueError("acceptance_baseline_unhealthy")
        report.update(scope_digest=digest(scope), baseline=host.runtime._sample(baseline))
        binding = {"scope": scope, "test": "two_external_stopped_api_incidents",
            "max_fault_stops": 2, "max_recovery_actions_per_incident": 1,
            "cleanup": "at_most_one_A_start_with_separate_original_recovery_grant",
            "model": "configured_provider" if host.provider is not None else "not_configured_rule_then_experience"}
        save()  # Persistence must succeed before asking for a fault capability.
        grant = host.gate.request("experiment", binding)
        host.gate.consume(grant, "experiment", binding, operation_id="ab-experiment:" + uuid4().hex)
        for index in range(2):
            if (host.gate._now() >= grant.expires_at or host.runtime.port.scope("reops-lab-api") != scope
                    or injector.recovery_scope() != injection_scope):
                raise ValueError("acceptance_scope_changed_or_experiment_expired")
            before = host.monitor.observe(**context("incident-ab-before"))
            if not verify_a_business(before)[2]:
                raise ValueError("acceptance_before_fault_unhealthy")
            report["faults"].append({"number": index + 1, "timestamp": now(), "attempted": True,
                                     "confirmed": False, "before_observation_id": before["observation_id"]})
            save()
            # Existing test-only whitelist, pinned to the same A-selected immutable ID.
            # Recovery still exclusively uses A RecoveryTool and its original grant.
            injector.inject_web_failure_test_only(expected_container_id=scope["container_id"])
            observed = host.monitor.observe(**context("incident-ab-fault"))
            if observed["metrics"].get("api_up") != 0:
                raise ValueError("acceptance_external_stop_not_observed")
            report["faults"][-1]["confirmed"] = True
            incident_id = host.runtime.notify("reops-lab-api", observed)
            if incident_id is None:
                raise ValueError("acceptance_incident_missing")
            report["incidents"].append(incident_id)
            save()
            incident = next(item for item in host.export().incidents if item.id == incident_id)
            if incident.status != "recovered" or incident.verification.status != "passed":
                raise ValueError("acceptance_recovery_not_verified")
        final = host.monitor.observe(**context("incident-ab-final"))
        snapshot = host.export()
        report["final_observation"] = host.runtime._sample(final)
        report["snapshot"] = snapshot.model_dump()
        report["acceptance_passed"] = (verify_a_business(final)[2]
            and len(snapshot.incidents) == 2 and snapshot.incidents[1].diagnosis_source == "experience"
            and all(item.status == "recovered" and len(item.verification.checks) == 2 for item in snapshot.incidents)
            and snapshot.incidents[1].model_calls == [])
    except BaseException:
        report["error"] = "acceptance_rejected_or_incomplete"
    finally:
        if scope is not None and report["faults"]:
            try:
                current = host.monitor.observe(**context("incident-ab-cleanup-check"))
                if not verify_a_business(current)[2]:
                    if host.runtime.port.scope("reops-lab-api") != scope or current["metrics"].get("api_up") != 0:
                        raise ValueError("cleanup_requires_manual_review")
                    # A separate trace/grant; cannot change a failed original incident or Memory.
                    current = host.monitor.observe(**context("incident-ab-cleanup"))
                    action = plan_a_start(diagnose(current), current)
                    binding = host.runtime.port.prepare("reops-lab-api", action, current)
                    grant = host.gate.request("recovery", binding)
                    outcome = host.runtime.port.execute("reops-lab-api", action, current,
                        AAuthorization(host.gate, grant, deepcopy(binding)))
                    report["cleanup"] = {"trace_id": current["trace_id"], "execution_status": outcome.status}
                final = host.monitor.observe(**context("incident-ab-final-check"))
                report["final_healthy"] = verify_a_business(final)[2]
                report["final_observation"] = host.runtime._sample(final)
            except BaseException:
                report["final_healthy"] = False
                report["cleanup"] = {"status": "manual_review_required"}
            report["acceptance_passed"] = report["acceptance_passed"] and report.get("final_healthy") is True
        report["finished_at"] = now()
        try:
            if host.store is not None:
                report["snapshot"] = host.export().model_dump()
                save()
        finally:
            # Export or persistence failure must still release the monitor/adapters.
            host.close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--directory", type=Path, default=PROJECT_ROOT / ("runtime/ab-online-" + uuid4().hex[:8]))
    args = parser.parse_args(argv)
    if not args.run:
        from .b_cli import main as check
        return check([])
    args.directory.mkdir(parents=True, exist_ok=False)
    # Tee original prompts so ConPTY wrapping cannot corrupt human challenge transcription.
    original_stdout = sys.stdout
    with (args.directory / "operator-prompts.txt").open("w", encoding="utf-8", buffering=1) as prompts:
        class Tee:
            def write(self, text):
                prompts.write(text)
                return original_stdout.write(text)
            def flush(self):
                prompts.flush()
                original_stdout.flush()
        sys.stdout = Tee()
        try:
            gate = AuthorizationGate(args.directory / "authorizations.sqlite3", ttl=300)
            report = run_acceptance(WorkbenchHost(args.directory, gate=gate, execute=True), LocalDocker(), run=True)
            print(json.dumps({"acceptance_passed": report["acceptance_passed"], "directory": str(args.directory),
                              "final_healthy": report.get("final_healthy"), "error": report["error"]}))
            return 0 if report["acceptance_passed"] else 1
        finally:
            sys.stdout = original_stdout


if __name__ == "__main__":
    raise SystemExit(main())
