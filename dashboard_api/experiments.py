"""C4 request ledger and the sole, terminal-operated B Phase 8 experiment bridge.

HTTP only queues intent. This module never accepts an authorization answer over HTTP.
"""

import json
import hashlib
import math
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from reops_agent.credential_handling import redact_persistent

SCENARIO = "phase8_stopped_api"
GROUND_TRUTH = {"component": "api", "root_cause": "api_service_down",
                "injection": "stop_api_once", "expected_recovery": "start_service(web)"}
VERIFY_STATES = {"not_run", "recovered", "not_recovered", "inconclusive"}
CLEANUP_STATES = {"not_run", "succeeded", "failed", "unknown"}
EXECUTION_STATES = {"not_run", "succeeded", "failed", "unknown"}
SERVICE_STATES = {"healthy", "degraded", "unhealthy", "unknown"}
AUTHORIZATION_STATES = {"not_requested", "pending", "consumed", "expired",
                        "rejected", "not_consumed", "unknown"}
REPORT_BOOLEANS = ("acceptance_passed", "recovery_verified", "recovery_authorized",
                   "recovery_executed", "recovered", "execution_attempted",
                   "executor_called", "fault_injection_attempted", "memory_written")


def stamp():
    return datetime.now(timezone.utc).isoformat()


class ExperimentLedger:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY, body TEXT NOT NULL)""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _connection(self):
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _needs_review(record):
        # Also fail closed for records written before the review_required field existed.
        report = record.get("report")
        return (record.get("state") == "waiting_authorization"
                or record.get("review_required") is True
                or record.get("state") == "finished" and record.get("manual_review") is None
                and (record.get("result") == "unknown"
                     or record.get("cleanup") in ("failed", "unknown")
                     or record.get("injection") == "attempted" and record.get("cleanup") != "succeeded"
                     or not isinstance(report, dict)
                     or not isinstance(report.get("final_observation"), dict)))

    def _assert_no_hold(self, db, *, exclude=None):
        for row in db.execute("SELECT body FROM experiments WHERE id<>?", (exclude or "",)):
            if self._needs_review(json.loads(row[0])):
                raise ValueError("another_experiment_requires_operator_inspection")

    def has_hold(self):
        with self._connection() as db:
            return any(self._needs_review(json.loads(row[0])) for row in
                       db.execute("SELECT body FROM experiments"))

    @staticmethod
    def _redact_record(record):
        cleaned = redact_persistent(record)
        # The top-level authorization field is a C status enum, not a credential.
        if record.get("authorization") in AUTHORIZATION_STATES:
            cleaned["authorization"] = record["authorization"]
        return cleaned

    @staticmethod
    def _evidence_observation(observation):
        """Store the C4 evidence needed for review, never arbitrary observer fields."""
        if not isinstance(observation, dict):
            return None
        services = observation.get("services")
        metrics = observation.get("metrics")
        request = observation.get("request")
        return {
            "observation_id": observation.get("observation_id") if type(observation.get("observation_id")) is str else None,
            "incident_id": observation.get("incident_id") if type(observation.get("incident_id")) is str else None,
            "trace_id": observation.get("trace_id") if type(observation.get("trace_id")) is str else None,
            "timestamp": observation.get("timestamp") if type(observation.get("timestamp")) is str else None,
            "services": {name: {"status": services[name]["status"]
                                  if isinstance(services.get(name), dict)
                                  and type(services[name].get("status")) is str
                                  and services[name]["status"] in SERVICE_STATES else "unknown"}
                         for name in ("api", "postgres", "redis")}
                        if isinstance(services, dict) else None,
            "metrics": {name + "_up": metrics.get(name + "_up")
                        if type(metrics.get(name + "_up")) in (int, float)
                        and math.isfinite(metrics[name + "_up"]) else None
                        for name in ("api", "postgres", "redis")}
                       if isinstance(metrics, dict) else None,
            "request": {"method": "GET" if request.get("method") == "GET" else None,
                        "endpoint": "/users" if request.get("endpoint") == "/users" else None,
                        "status_code": request.get("status_code") if type(request.get("status_code")) is int else None}
                       if isinstance(request, dict) else None,
        }

    def _evidence_report(self, report):
        samples = report.get("verify_observations")
        return {"acceptance_passed": report.get("acceptance_passed") if type(report.get("acceptance_passed")) is bool else None,
                "model_calls": report.get("model_calls") if type(report.get("model_calls")) is int and 0 <= report["model_calls"] <= 1 else None,
                "execution_outcome": report.get("execution_outcome") if type(report.get("execution_outcome")) is str and report["execution_outcome"] in EXECUTION_STATES else "unknown",
                "recovery_verified": report.get("recovery_verified") if type(report.get("recovery_verified")) is bool else None,
                "memory_written": report.get("memory_written") if type(report.get("memory_written")) is bool else None,
                "verify_observations": [self._evidence_observation(item) for item in samples[-2:]]
                                       if isinstance(samples, list) else [],
                "final_observation": self._evidence_observation(report.get("final_observation"))}

    def _read(self, db, experiment_id):
        row = db.execute("SELECT body FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, experiment_id):
        with self._connection() as db:
            return self._read(db, experiment_id)

    def list(self):
        with self._connection() as db:
            rows = db.execute("SELECT body FROM experiments ORDER BY rowid DESC LIMIT 100").fetchall()
        return [json.loads(row[0]) for row in rows]

    def request(self, scenario):
        if scenario != SCENARIO:
            raise ValueError("unsupported_experiment_scenario")
        record = self._new_record()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_no_hold(db)
            db.execute("INSERT INTO experiments VALUES (?,?)", (record["id"], json.dumps(record)))
        return record

    @staticmethod
    def _new_record():
        experiment_id = f"experiment-c4-{uuid4()}"
        record = {"id": experiment_id, "scenario": SCENARIO, "source": "real",
                  "state": "waiting_operator", "requested_at": stamp(), "started_at": None,
                  "finished_at": None, "incident_id": None, "trace_id": None,
                  "ground_truth": GROUND_TRUTH.copy(), "authorization": "not_requested",
                  "injection": "not_attempted", "recovery": "not_attempted",
                  "verify": "not_run", "cleanup": "not_run", "result": "unknown",
                  "error": None, "review_required": False, "manual_review": None}
        return record

    def queue(self, scenario):
        """HTTP deduplication and durable rate limit under the claim lock."""
        if scenario != SCENARIO:
            raise ValueError("unsupported_experiment_scenario")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_no_hold(db)
            rows = [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM experiments ORDER BY rowid DESC")]
            for existing in rows:
                if existing.get("state") == "waiting_operator":
                    return existing
            if rows and (datetime.now(timezone.utc) - datetime.fromisoformat(
                    rows[0]["requested_at"])).total_seconds() < 30:
                raise ValueError("experiment_request_rate_limited")
            record = self._new_record()
            db.execute("INSERT INTO experiments VALUES (?,?)", (record["id"], json.dumps(record)))
        return record

    def claim(self, experiment_id):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._read(db, experiment_id)
            if record is None:
                raise KeyError(experiment_id)
            if record["state"] != "waiting_operator":
                raise ValueError("experiment_already_claimed")
            self._assert_no_hold(db, exclude=experiment_id)
            record.update(state="waiting_authorization", authorization="pending",
                          started_at=stamp())
            db.execute("UPDATE experiments SET body=? WHERE id=?", (json.dumps(record), experiment_id))
        return record

    def finish(self, experiment_id, report=None, error=None):
        # A crash leaves waiting_authorization for operator inspection, never a fabricated failure.
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._read(db, experiment_id)
            if record is None or record["state"] != "waiting_authorization":
                raise ValueError("experiment_not_claimed")
            if report is not None and not isinstance(report, dict):
                raise ValueError("experiment_report_invalid")
            report = report or {}
            if report and (report.get("incident_id") != record["incident_id"]
                           or report.get("trace_id") != record["trace_id"]):
                raise ValueError("experiment_report_correlation_mismatch")
            valid = (report.get("phase") == "8"
                     and report.get("real_model") is True and report.get("real_observation") is True
                     and all(type(report.get(key)) is bool for key in REPORT_BOOLEANS)
                     and type(report.get("verification_status")) is str
                     and report["verification_status"] in VERIFY_STATES
                     and type(report.get("cleanup_outcome")) is str
                     and report["cleanup_outcome"] in CLEANUP_STATES
                     and type(report.get("execution_outcome")) is str
                     and report["execution_outcome"] in EXECUTION_STATES
                     and type(report.get("model_calls")) is int and 0 <= report["model_calls"] <= 1
                     and isinstance(report.get("error"), (str, type(None)))
                     and isinstance(report.get("execution_skipped_reason"), (str, type(None))))
            # B's acceptance: verified recovery, durable Memory, successful cleanup,
            # and no error. Check the supporting execution and Verify evidence too.
            passed = (valid and error is None and report["acceptance_passed"] is True
                      and report["recovery_verified"] is True
                      and report["recovered"] is True
                      and report["recovery_authorized"] is True
                      and report["recovery_executed"] is True
                      and report["execution_attempted"] is True
                      and report["executor_called"] is True
                      and report["fault_injection_attempted"] is True
                      and report["memory_written"] is True
                      and report["model_calls"] == 1
                      and report["execution_outcome"] == "succeeded"
                      and report["verification_status"] == "recovered"
                      and report["cleanup_outcome"] == "succeeded"
                      and report.get("error") is None
                      and report.get("execution_skipped_reason") is None
                      and report.get("system_observed_healthy") is True
                      and self._verify_confirmed(report, record)
                      and self._final_environment_confirmed(report.get("final_observation"), record))
            if valid and report["acceptance_passed"] is False and self._acceptance_evidence(report, record):
                valid = False
            reason = report.get("execution_skipped_reason") if valid else None
            result = ("passed" if passed else
                      "unknown" if not valid or error is not None or report.get("acceptance_passed") is True else
                      "expired" if reason and "expired" in reason else
                      "rejected" if report.get("error") and report["fault_injection_attempted"] is False else
                      "failed" if report["verification_status"] == "not_recovered" else
                      "unknown")
            review_required = (result == "unknown" or report.get("cleanup_outcome") in ("failed", "unknown")
                               or report.get("execution_outcome") == "unknown"
                               or report.get("fault_injection_attempted") is True
                               and report.get("cleanup_outcome") != "succeeded"
                               or not self._final_environment_confirmed(report.get("final_observation"), record))
            record.update(state="finished", finished_at=stamp(),
                          authorization="consumed" if report.get("recovery_authorized") is True else
                          "expired" if result == "expired" else
                          "rejected" if result == "rejected" else "not_consumed",
                          injection="attempted" if report.get("fault_injection_attempted") is True else "not_attempted",
                          recovery="confirmed" if report.get("recovery_verified") is True else
                          "attempted_unconfirmed" if report.get("executor_called") is True else "not_attempted",
                          verify=report.get("verification_status") if type(report.get("verification_status")) is str and report["verification_status"] in VERIFY_STATES else "unknown",
                          cleanup=report.get("cleanup_outcome") if type(report.get("cleanup_outcome")) is str and report["cleanup_outcome"] in CLEANUP_STATES else "unknown",
                          result=result,
                          review_required=review_required,
                          error="experiment_report_error" if error is not None else
                          "experiment_report_invalid" if not valid else
                          "experiment_report_inconsistent" if report.get("acceptance_passed") is True and not passed else
                          "experiment_report_error" if report.get("error") else None,
                          report=self._evidence_report(report))
            record = self._redact_record(record)
            db.execute("UPDATE experiments SET body=? WHERE id=?", (json.dumps(record, allow_nan=False), experiment_id))
        return record

    def bind(self, experiment_id, incident_id, trace_id):
        if (type(incident_id) is not str or not incident_id.strip()
                or type(trace_id) is not str or not trace_id.strip()):
            raise ValueError("experiment_correlation_id_invalid")
        if redact_persistent(incident_id) != incident_id or redact_persistent(trace_id) != trace_id:
            raise ValueError("experiment_correlation_id_invalid")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._read(db, experiment_id)
            if (record is None or record["state"] != "waiting_authorization"
                    or record["incident_id"] is not None or record["trace_id"] is not None):
                raise ValueError("experiment_not_claimed")
            record.update(incident_id=incident_id, trace_id=trace_id)
            db.execute("UPDATE experiments SET body=? WHERE id=?", (json.dumps(record), experiment_id))

    def mark_unknown(self, experiment_id):
        """Preserve uncertainty after an unexpected exception; never retry a claimed request."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._read(db, experiment_id)
            if record is None or record["state"] != "waiting_authorization":
                return
            record.update(state="finished", finished_at=stamp(), result="unknown",
                          authorization="unknown", injection="unknown", recovery="unknown",
                          verify="unknown", cleanup="unknown", review_required=True,
                          error="operator_run_interrupted_inspect_b_audit_and_environment")
            db.execute("UPDATE experiments SET body=? WHERE id=?", (json.dumps(record), experiment_id))

    @staticmethod
    def _observation_healthy(observation, record, *, verify_trace):
        if (not isinstance(observation, dict) or observation.get("incident_id") != record["incident_id"]
                or verify_trace and observation.get("trace_id") != record["trace_id"]):
            return False
        if type(observation.get("observation_id")) is not str or not observation["observation_id"].strip():
            return False
        timestamp = observation.get("timestamp")
        if type(timestamp) is not str:
            return False
        try:
            if datetime.fromisoformat(timestamp.replace("Z", "+00:00")).utcoffset() is None:
                return False
        except ValueError:
            return False
        services = observation.get("services")
        request = observation.get("request")
        metrics = observation.get("metrics")
        return (isinstance(services, dict) and isinstance(request, dict) and isinstance(metrics, dict)
                and all(isinstance(services.get(name), dict)
                        and services[name].get("status") == "healthy"
                        for name in ("api", "postgres", "redis"))
                and all(type(metrics.get(name + "_up")) in (int, float)
                        and metrics[name + "_up"] == 1 for name in ("api", "postgres", "redis"))
                and request.get("method") == "GET" and request.get("endpoint") == "/users"
                and type(request.get("status_code")) is int and request["status_code"] == 200)

    def _final_environment_confirmed(self, observation, record):
        return (self._observation_healthy(observation, record, verify_trace=False)
                and type(observation.get("trace_id")) is str
                and observation["trace_id"] != record["trace_id"])

    def _verify_confirmed(self, report, record):
        observations = report.get("verify_observations")
        verification = report.get("verification_result")
        return (isinstance(observations, list) and len(observations) >= 2
                and all(self._observation_healthy(item, record, verify_trace=True)
                        for item in observations[-2:])
                and all(type(item.get("observation_id")) is str and item["observation_id"].strip()
                        for item in observations[-2:])
                and observations[-2]["observation_id"] != observations[-1]["observation_id"]
                and isinstance(verification, dict) and verification.get("status") == "recovered"
                and all(verification.get(key) is True for key in
                        ("health_check_passed", "fault_cleared", "business_request_passed")))

    def _acceptance_evidence(self, report, record):
        return (all(report.get(key) is True for key in ("recovery_verified", "recovery_authorized",
                "recovery_executed", "recovered", "execution_attempted", "executor_called",
                "fault_injection_attempted", "memory_written", "system_observed_healthy"))
                and report.get("model_calls") == 1
                and report.get("execution_outcome") == "succeeded"
                and report.get("verification_status") == "recovered"
                and report.get("cleanup_outcome") == "succeeded" and report.get("error") is None
                and report.get("execution_skipped_reason") is None
                and self._verify_confirmed(report, record)
                and self._final_environment_confirmed(report.get("final_observation"), record))

    def resolve_review(self, experiment_id, *, reviewer, audit_reference, environment_reference,
                       audit_checked, environment_confirmed):
        """Terminal operator records B audit inspection and independent environment review."""
        if not sys.stdin.isatty():
            raise RuntimeError("interactive_terminal_required")
        if any(type(value) is not str or not value.strip() for value in
               (reviewer, audit_reference, environment_reference)) or audit_checked is not True or environment_confirmed is not True:
            raise ValueError("manual_review_evidence_required")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._read(db, experiment_id)
            if record is None or record.get("state") != "finished" or not self._needs_review(record):
                raise ValueError("experiment_review_not_required_or_still_running")
            record["manual_review"] = {"reviewer": reviewer, "audit_reference": audit_reference,
                                       "audit_checked": True, "environment_reference": environment_reference,
                                       "environment_confirmed": True, "reviewed_at": stamp()}
            record["review_required"] = False
            record = self._redact_record(record)
            db.execute("UPDATE experiments SET body=? WHERE id=?", (json.dumps(record, allow_nan=False), experiment_id))
        return record


def run_pending(ledger: ExperimentLedger, experiment_id: str):
    """Explicit operator action; B's original interactive AuthorizationGate remains authoritative."""
    if not sys.stdin.isatty():
        raise RuntimeError("interactive_terminal_required")
    from dataclasses import replace
    from reops_agent.authorization import AuthorizationGate
    from reops_agent.contracts import PROJECT_ROOT
    from reops_agent.docker_executor import LocalDocker
    from reops_agent.memory import RecoveryMemory
    from reops_agent.nexent_provider import NexentConfig, NexentRCAProvider
    from reops_agent.recovery_smoke import context, fault_recovery
    from reops_agent.trace_journal import TraceJournal
    from reops_agent.online_reports import replace_complete

    config = replace(NexentConfig.from_env(), max_output_tokens=512)
    config.require_real_model()
    if config.api_base.rstrip("/") != "http://aigw.dlut.edu.cn/v1" or config.model_id != "DeepSeek-V3.1-W8A8":
        raise ValueError("phase8_model_scope_rejected")
    ledger.claim(experiment_id)
    try:
        ctx = context() | {"incident_id": f"incident-c4-{uuid4()}", "trace_id": f"trace-c4-{uuid4()}"}
        ledger.bind(experiment_id, ctx["incident_id"], ctx["trace_id"])
        runtime = PROJECT_ROOT / "runtime"
        # Reserve a fresh evidence directory before any model or Docker operation.
        # Never replace an earlier experiment's report or append to historical Memory.
        evidence = runtime / "c4-evidence" / ctx["trace_id"]
        evidence.mkdir(parents=True, exist_ok=False)
        sources = [PROJECT_ROOT / "docker-compose.yml"]
        for directory, pattern in (("reops_agent", "*.py"), ("dashboard_api", "*.py"),
                                   ("shared", "*.schema.json")):
            sources.extend((PROJECT_ROOT / directory).rglob(pattern))
        replace_complete(evidence / "request.json", json.dumps({
            "experiment_id": experiment_id, **ctx,
            "scenario": SCENARIO, "ground_truth": GROUND_TRUTH,
            "database": str(Path(ledger.path).resolve()),
            "journal": str(runtime / "c4-audit.jsonl"),
            "memory_initial_state": "empty",
            "model_max_output_tokens": 512,
            "source_sha256": {str(path.relative_to(PROJECT_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted(sources) if path.is_file()},
        }, ensure_ascii=False, allow_nan=False, indent=2), artifact="request")
        report = fault_recovery(LocalDocker(), NexentRCAProvider(config),
            gate=AuthorizationGate(runtime / "c4-authorizations.sqlite3"),
            journal=TraceJournal(ctx, runtime / "c4-audit.jsonl"),
            memory=RecoveryMemory(evidence / "memory.jsonl"),
            model_identifier=config.model_id, execute_recovery=True, real_model=True,
            real_observation=True, phase8_online=True)
        # Persist the complete, redacted B result before acknowledging C acceptance.
        # A write failure marks the ledger unknown; it must never repeat the experiment.
        replace_complete(evidence / "report.json", json.dumps(redact_persistent(report),
            ensure_ascii=False, allow_nan=False, indent=2), artifact="json")
        return ledger.finish(experiment_id, report)
    except BaseException:
        # An exception can happen after a side effect. Preserve uncertainty for inspection.
        ledger.mark_unknown(experiment_id)
        raise


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run one queued C4 request through B's terminal authorization")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run-pending")
    action.add_argument("--resolve-review")
    args = parser.parse_args()
    from .api import DEFAULT_DB
    import os
    ledger = ExperimentLedger(os.getenv("REOPS_C_DB_PATH", str(DEFAULT_DB)))
    if args.resolve_review:
        if not sys.stdin.isatty():
            raise RuntimeError("interactive_terminal_required")
        reviewer = input("Reviewer identity: ")
        audit_reference = input("B audit inspection reference: ")
        environment_reference = input("Independent environment recheck reference: ")
        if input("Type AUDIT_REVIEWED after inspecting B audit and possible actions: ") != "AUDIT_REVIEWED":
            raise ValueError("manual_review_confirmation_required")
        if input("Type ENVIRONMENT_RECHECKED after an independent health and identity check: ") != "ENVIRONMENT_RECHECKED":
            raise ValueError("manual_review_confirmation_required")
        if input(f"Type {args.resolve_review} to release the C ledger hold: ") != args.resolve_review:
            raise ValueError("manual_review_confirmation_required")
        result = ledger.resolve_review(args.resolve_review, reviewer=reviewer,
            audit_reference=audit_reference, environment_reference=environment_reference,
            audit_checked=True, environment_confirmed=True)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    result = run_pending(ledger, args.run_pending)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
