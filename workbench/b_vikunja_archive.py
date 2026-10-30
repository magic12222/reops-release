"""显式将已验收的本项目Vikunja原件投影为历史经验；不修改原件、不执行动作。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from reops_agent.agent_event import build_agent_event
from reops_agent.authorization import digest
from reops_agent.contracts import PROJECT_ROOT, validate
from reops_agent.memory import RecoveryMemory
from reops_agent.pipeline import diagnose
from .b_privacy import dumps
from .b_runtime import condition_fingerprint
from .b_store import instant
from .b_vikunja import PROFILE, POLICY_VERSION, check_vikunja_start, current_business_healthy, policy, safe_vikunja_observation
from .contracts import Incident, Experience
from .vikunja_target import TARGET_ID

BASELINE = PROJECT_ROOT / "runtime/vikunja-evidence/b0dbc2a01d844ecf9953e4936e290416/report.json"
BASELINE_SHA256 = "bd9f49c0ee1822cff609fb64e85238000e83134937af59a4a76ecbe86d2a43ac"


def _projection(report, fingerprint):
    if (report.get("source") != "real" or report.get("kind") != "infrastructure_connection_acceptance"
            or report.get("passed") is not True or report.get("recovery_verified") is not True
            or report.get("fault_injection_attempted") is not True or report.get("b_agent_closed_loop") is not False
            or type(report.get("model_calls")) is not int or report["model_calls"] != 0
            or report.get("app_restart_observed") is not False or type(report.get("cleanup_extra_starts")) is not int or report["cleanup_extra_starts"] != 0
            or report.get("final_business_healthy") is not True):
        raise ValueError("vikunja_archive_not_verified_baseline")
    context = {key: report[key] for key in ("incident_id", "trace_id")}
    observation = safe_vikunja_observation(report["observation"])
    action = deepcopy(report["recovery_action"])
    execution = deepcopy(report["execution_result"])
    validate("recovery_result", execution)
    if (any(value[key] != context[key] for value in (observation, action, execution) for key in context)
            or not check_vikunja_start(action, observation)["allowed"]
            or execution["execution_status"] != "succeeded" or execution["exit_code"] != 0
            or execution.get("mutation_attempted") is not True
            or execution["action_id"] != action["action_id"] or execution.get("target_id") != TARGET_ID):
        raise ValueError("vikunja_archive_action_or_scope_invalid")
    if not instant(report["started_at"]) <= instant(observation["timestamp"]) <= instant(action["timestamp"]) <= instant(execution["timestamp"]):
        raise ValueError("vikunja_archive_action_time_invalid")
    samples = report.get("verify_observations")
    if not isinstance(samples, list) or len(samples) != 2:
        raise ValueError("vikunja_archive_two_verifications_required")
    ids = [observation["observation_id"]]
    previous = instant(execution["timestamp"])
    app_started = report["observation"]["business"]["app_started_at"]
    for sample in samples:
        validate("observation", sample)
        safe_sample = safe_vikunja_observation(sample)
        if (any(sample[key] != context[key] for key in context) or sample["observation_id"] in ids
                or instant(sample["timestamp"]) < previous or not current_business_healthy(safe_sample)
                or instant(sample["sample_completed_at"]) < instant(sample["timestamp"])
                or sample.get("business", {}).get("database_sql_valid") is not True
                or sample["business"].get("probe_read_valid") is not True
                or sample["business"].get("app_started_at") != app_started
                or any(sample["business"].get(key) != report["observation"]["business"].get(key) for key in ("project_id", "task_id"))):
            raise ValueError("vikunja_archive_verification_invalid")
        previous = instant(sample["timestamp"])
        ids.append(sample["observation_id"])
    if samples[0]["business"].get("write_valid") is not True or instant(report["finished_at"]) < previous:
        raise ValueError("vikunja_archive_write_or_time_invalid")
    scope = {**report["scope"], "app_started_at": app_started, "b_policy_version": POLICY_VERSION}
    if scope.get("target_id") != TARGET_ID:
        raise ValueError("vikunja_archive_target_invalid")
    diagnosis = diagnose(observation)
    diagnosis["diagnosis_id"] = action["diagnosis_id"]
    diagnosis["timestamp"] = observation["timestamp"]
    validate("diagnosis", diagnosis)
    scope_key = digest({"scope": scope, "policy": policy().__dict__})
    failure_key = condition_fingerprint(observation, diagnosis, PROFILE)
    verification = {"status": "recovered", "checked_at": samples[-1]["sample_completed_at"],
        "health_check_passed": True, "fault_cleared": True, "business_request_passed": True,
        "evidence": ["Archived fresh observation " + item["observation_id"] for item in samples]}
    result = {"schema_version": "1.0", **context, "result_id": "result-import-" + fingerprint[:24],
        "action_id": action["action_id"], "timestamp": samples[-1]["sample_completed_at"],
        "execution_status": "succeeded", "exit_code": 0, "stdout": None, "stderr": None,
        "duration_ms": execution["duration_ms"], "post_observation_id": samples[-1]["observation_id"],
        "verification": verification, "executor": {"executed": True, "success": True,
            "action": "start_service", "target": "postgres"}, "a_recovery_result": execution}
    validate("recovery_result", result)
    memory = build_agent_event(observation, diagnosis, action, result, verification, True)
    memory.update(event_id="event-import-" + fingerprint[:24], timestamp=report["finished_at"])
    events = []
    def event(stage, title, timestamp, evidence):
        value = {"id": f"projection-{fingerprint[:16]}-{len(events)}", "sequence": len(events), "timestamp": timestamp,
            "stage": stage, "status": "succeeded", "title": title,
            "detail": "Historical report projection; no new model or recovery. Source SHA256=" + fingerprint,
            "evidence": evidence}
        events.append(value)
    event("observe", "Archived stopped-database observation", observation["timestamp"], ["observation_id=" + observation["observation_id"], "report.json#/observation"])
    event("failure_detection", "Archived database failure", observation["timestamp"], ["postgres_up=0", "report.json#/observation"])
    event("root_cause_analysis", "Fixed-rule historical diagnosis", observation["timestamp"], ["source=rule", "b_agent_closed_loop=false", "report.json#/diagnosis_source"])
    event("recovery_decision", "Archived fixed recovery action", action["timestamp"], ["start_service(postgres)", "report.json#/recovery_action"])
    event("recovery_execution", "Archived A execution", execution["timestamp"], ["execution_status=succeeded", "report.json#/execution_result"])
    for sample in samples:
        event("verification", "fresh_business_check", sample["timestamp"], ["observation_id=" + sample["observation_id"] + ";business=passed", "report.json#/verify_observations"])
    memory["parent_event_id"] = events[-1]["id"]
    memory["data"].update(source="real", target_id=TARGET_ID, scope_fingerprint=scope_key,
        sequence=len(events), provenance={"kind": "verified_historical_report_projection", "sha256": fingerprint,
        "original_b_agent_closed_loop": False})
    validate("agent_event", memory)
    event("experience_update", "Verified baseline imported as historical experience", report["finished_at"],
        ["memory_event_id=" + memory["event_id"], "original_b_agent_closed_loop=false"])
    experience = Experience(id="experience-import-" + fingerprint[:24], target_id=TARGET_ID, incident_id=context["incident_id"],
        title="Vikunja stopped database · verified historical baseline", symptom=diagnosis["failure_type"] or "unknown",
        root_cause=diagnosis["root_cause"] or "unknown", action="start_service(postgres)",
        conditions=["target=" + TARGET_ID, "scope=" + scope_key, "conditions=" + failure_key,
            "source_event=" + events[-1]["id"], "memory_event=" + memory["event_id"],
            "source=verified_historical_report_projection", "report_sha256=" + fingerprint,
            *["service=" + name + ";status=" + value["status"] for name, value in observation["services"].items()],
            "business=GET " + observation["request"]["endpoint"] + ";status=" + str(observation["request"].get("status_code")),
            "original_b_agent_closed_loop=false", "requires current Safety, scope binding and two fresh business verifications"], status="verified")
    incident = Incident(id=context["incident_id"], target_id=TARGET_ID, trace_id=context["trace_id"],
        title="Historical Vikunja baseline · fixed rules", started_at=report["started_at"], status="recovered",
        diagnosis_source="rule", summary="Verified historical report imported as experience. Original model calls: 0; original B agent closed loop: false.",
        events=events, model_calls=[], experience_ids=[experience.id],
        verification={"status": "passed", "checks": ["observation_id=" + item["observation_id"] + ";business=passed" for item in samples]})
    return incident, experience, memory, scope_key, failure_key


def import_verified_baseline(store):
    """Only this fixed, previously accepted artifact is importable. No arbitrary-path API."""
    payload = BASELINE.read_bytes()
    fingerprint = sha256(payload).hexdigest()
    if fingerprint != BASELINE_SHA256 or store.source != "real":
        raise ValueError("vikunja_archive_fingerprint_or_source_mismatch")
    report = json.loads(payload)
    incident, experience, memory, scope_key, failure_key = _projection(report, fingerprint)
    with store.transaction() as db:
        existing = db.execute("SELECT body FROM incidents WHERE id=?", (incident.id,)).fetchone()
        if existing:
            if json.loads(existing[0]) != json.loads(dumps(incident.model_dump())):
                raise ValueError("vikunja_archive_conflicting_existing_record")
            saved = db.execute("SELECT body FROM experiences WHERE id=?", (experience.id,)).fetchone()
            if saved is None or json.loads(saved[0]) != json.loads(dumps(experience.model_dump())):
                raise ValueError("vikunja_archive_experience_missing_or_conflicting")
            history = RecoveryMemory(store.path.parent / "b-memory" / (scope_key + ".jsonl")).retrieve(experience.symptom, "postgres", limit=20)
            if not any(item["event_id"] == memory["event_id"] and item["recovered"] is True for item in history):
                raise ValueError("vikunja_archive_memory_missing_or_conflicting")
            return {"imported": False, "incident_id": incident.id, "sha256": fingerprint}
    RecoveryMemory(store.path.parent / "b-memory" / (scope_key + ".jsonl")).remember(memory)
    with store.transaction() as db:
        db.execute("INSERT INTO incidents VALUES(?,?,?)", (incident.id, dumps(incident.model_dump()), dumps({"scope_key": scope_key,
            "finished": True, "archive_sha256": fingerprint, "source_observation_id": report["observation"]["observation_id"]})))
        db.execute("INSERT INTO experiences VALUES(?,?,?)", (experience.id, dumps(experience.model_dump()), dumps({"scope_key": scope_key,
            "failure_key": failure_key, "memory_event_id": memory["event_id"], "source_event_ids": [incident.events[-1].id]})))
    return {"imported": True, "incident_id": incident.id, "sha256": fingerprint}
