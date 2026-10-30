"""依赖恢复审计的版本化读模型。只投影事实，不创建旧 B Memory 或执行权限。"""
from hashlib import sha256
import json
import re

from .b_privacy import dumps
from .b_store import instant, now
from .contracts import Incident, Experience, ModelCall, Event
from .vikunja_target import TARGET_ID

VERSION = "dependency-audit-v1"
STAGES = {
    "dependency_safety_passed": ("recovery_decision", "Dependency Safety checks passed"),
    "dependency_observed": ("observe", "Fresh target HTTP observation"),
    "sql_probe": ("verification", "SQL readiness check"),
    "business_check": ("verification", "Target HTTP and SQL validation"),
    "fault_confirmed": ("failure_detection", "Fault confirmed"),
    "recovery_started": ("recovery_decision", "Dependency recovery selected"),
    "dependency_action_reserved": ("recovery_decision", "Action authorization consumed"),
    "database_started": ("recovery_execution", "Database started"),
    "sql_wait_started": ("verification", "Waiting for SQL readiness"),
    "sql_ready": ("verification", "SQL ready"),
    "application_exit_confirmed": ("localization", "Dependent application exit confirmed"),
    "application_started": ("recovery_execution", "Application started"),
    "application_start_skipped": ("recovery_execution", "Application remained running"),
    "verification_started": ("verification", "Business verification started"),
    "verification_passed": ("verification", "Fresh business and SQL check passed"),
    "recovery_verified": ("verification", "Recovery verified"),
    "dependency_action_failed": ("recovery_execution", "Action failed or uncertain"),
    "recovery_requires_attention": ("verification", "Recovery needs attention"),
}


def project_run(rows):
    first = rows[0][1]
    context = {key: first[key] for key in ("incident_id", "trace_id")}
    if (not re.fullmatch(r"incident-vikunja-auto-[a-f0-9]{32}", context["incident_id"])
            or not re.fullmatch(r"trace-vikunja-auto-[a-f0-9]{32}", context["trace_id"])
            or first["event"] != "fault_confirmed"
            or first.get("plan_id") != "vikunja_dependency_v1"):
        raise ValueError("dependency_record_origin_invalid")
    events, checks = [], []
    previous = float("-inf")
    for line, row, fingerprint in rows:
        timestamp = instant(row["timestamp"])
        if timestamp < previous or any(row.get(key) != value for key, value in context.items()):
            raise ValueError("dependency_record_order_or_context_conflict")
        previous = timestamp
        name = row["event"]
        if name not in STAGES:
            continue
        stage, title = STAGES[name]
        # Strict field projection: never publish arbitrary audit payloads or authentication.
        evidence = [f"source=dependency_audit_projection", f"profile={VERSION}",
                    "source_file=runtime/vikunja-web/events.jsonl",
                    f"source_line={line}", f"source_sha256={fingerprint}", f"event={name}"]
        if name == "dependency_action_reserved" and isinstance(row.get("authorization_id"), str):
            evidence.append("authorization_consumed_by_a=true")
        for key in ("step", "action_id", "observation_id", "check", "reason", "source", "timeout_seconds",
                    "method", "endpoint", "status_code", "query", "passed", "business_passed"):
            value = row.get(key)
            if type(value) in (str, int, bool) and len(str(value)) <= 200:
                evidence.append(f"{key}={value}")
        if name == "verification_passed" and row.get("source") == "fresh_business_read_and_sql":
            if type(row.get("check")) is int and isinstance(row.get("observation_id"), str):
                checks.append((row["check"], row["observation_id"]))
        failed = (name in {"recovery_requires_attention", "dependency_action_failed"}
                  or name in {"business_check", "sql_probe"} and row.get("passed") is False)
        events.append({"id": f"dependency-event-{fingerprint[:32]}", "sequence": len(events),
            "timestamp": row["timestamp"], "stage": stage, "status": "failed" if failed else "succeeded",
            "title": title, "detail": "Recorded automatic dependency recovery event. Original audit remains unchanged.",
            "evidence": evidence})
    final = rows[-1][1]
    names = [row["event"] for _, row, _ in rows]
    verified = (final["event"] == "recovery_verified" and type(final.get("model_calls")) is int and final["model_calls"] == 0
        and final.get("plan_id") == "vikunja_dependency_v1"
        and [n for n, _ in checks[-2:]] == [1, 2] and len({v for _, v in checks[-2:]}) == 2
        and final.get("observations") == [v for _, v in checks[-2:]]
        and all(name in names for name in ("database_started", "sql_ready", "verification_started"))
        and any(name in names for name in ("application_started", "application_start_skipped"))
        and not any(name in names for name in ("dependency_action_failed", "recovery_requires_attention")))
    failed = "recovery_requires_attention" in names or "dependency_action_failed" in names
    terminal = final["event"] in {"recovery_verified", "recovery_requires_attention"}
    exp_id = "experience-dependency-" + sha256(context["trace_id"].encode()).hexdigest()[:24]
    exp = Experience(id=exp_id, target_id=TARGET_ID, incident_id=context["incident_id"],
        title="Dependency recovery · " + ("verified audit record" if verified else "incomplete audit record"),
        symptom="Two stopped-database business observations", root_cause="Dependent exit evidence recorded" if "application_exit_confirmed" in names else "Root cause not established by this audit",
        action="start_service(postgres) → SELECT 1 → conditional start_service(api) → two fresh checks",
        conditions=[f"profile={VERSION}", "plan=vikunja_dependency_v1", "source=dependency_audit_projection",
            "original_b_agent_closed_loop=false", "model_calls=0", "not eligible for legacy database-only memory reuse",
            *["source_event=" + event["id"] for event in events]],
        status="verified" if verified else "failed" if failed else "unverified")
    incident = Incident(id=context["incident_id"], target_id=TARGET_ID, trace_id=context["trace_id"],
        title="Automatic dependency recovery", started_at=first["timestamp"],
        status="recovered" if verified else "failed" if failed else "unknown" if terminal else
            "verifying" if any(name in names for name in ("sql_wait_started", "verification_started")) else
            "executing" if "recovery_started" in names else "diagnosing",
        diagnosis_source="rule", summary="Dependency audit projection · fixed execution policy · original model calls 0 · original B loop false",
        events=events, model_calls=[], experience_ids=[exp_id],
        verification={"status": "passed" if verified else "failed" if failed else "unknown" if terminal else "pending",
                      "checks": ["fresh_business_read_and_sql;observation_id=" + value for _, value in checks]})
    return incident, exp


def sync_dependency_records(store, journal):
    """Append-only, idempotent import. Any changed prefix rolls back the entire batch."""
    if not journal.is_file():
        return 0
    payload = journal.read_bytes()
    if payload and not payload.endswith(b"\n"):
        raise ValueError("dependency_journal_incomplete")
    rows = []
    for number, line in enumerate(payload.splitlines(), 1):
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("dependency_journal_invalid")
        rows.append((number, row, sha256(line).hexdigest()))
    groups = {}
    for item in rows:
        row = item[1]
        if row.get("event") in STAGES and isinstance(row.get("trace_id"), str):
            groups.setdefault(row["trace_id"], []).append(item)
    projected = [project_run(group) for group in groups.values()
                 if group[0][1].get("plan_id") == "vikunja_dependency_v1"]
    with store.transaction() as db:
        db.execute("CREATE TABLE IF NOT EXISTS dependency_import(version TEXT PRIMARY KEY, hashes TEXT NOT NULL)")
        old = db.execute("SELECT hashes FROM dependency_import WHERE version=?", (VERSION,)).fetchone()
        hashes = [item[2] for item in rows]
        previous = json.loads(old[0]) if old else []
        if hashes[:len(previous)] != previous:
            raise ValueError("dependency_journal_prefix_conflict")
        for incident, experience in projected:
            saved_event = None
            existing = db.execute("SELECT body,meta FROM incidents WHERE id=?", (incident.id,)).fetchone()
            if existing:
                body, meta = map(json.loads, existing)
                if meta.get("profile") != VERSION or body["trace_id"] != incident.trace_id:
                    raise ValueError("dependency_incident_conflict")
                incident.model_calls = [ModelCall.model_validate(call) for call in body["model_calls"]]
                saved_event = next((event for event in body["events"] if "source=dependency_read_model" in event["evidence"]), None)
            if incident.status in {"recovered", "failed", "unknown"}:
                persisted = Event.model_validate(saved_event) if saved_event else Event(
                    id="dependency-saved-" + sha256(incident.trace_id.encode()).hexdigest()[:24], sequence=len(incident.events),
                    timestamp=now(), stage="experience_update", status="succeeded", title="Recovery audit saved as experience",
                    detail="BStore read-model persistence; original audit is unchanged. This does not establish a B model or legacy Memory loop.",
                    evidence=["source=dependency_read_model", "profile=" + VERSION, "original_b_agent_closed_loop=false"])
                persisted.sequence = len(incident.events)
                incident.events.append(persisted)
            exp = db.execute("SELECT meta FROM experiences WHERE id=?", (experience.id,)).fetchone()
            if exp and json.loads(exp[0]).get("profile") != VERSION:
                raise ValueError("dependency_experience_conflict")
            # Retirement is an explicit user state, never undone by replay.
            prior_exp = db.execute("SELECT body FROM experiences WHERE id=?", (experience.id,)).fetchone()
            if prior_exp and json.loads(prior_exp[0])["status"] == "retired":
                experience.status = "retired"
            meta = dumps({"profile": VERSION, "scope_key": VERSION, "finished": incident.status in {"recovered", "failed"}})
            db.execute("INSERT OR REPLACE INTO incidents VALUES(?,?,?)", (incident.id, dumps(incident.model_dump()), meta))
            db.execute("INSERT OR REPLACE INTO experiences VALUES(?,?,?)", (experience.id, dumps(experience.model_dump()), meta))
        db.execute("INSERT OR REPLACE INTO dependency_import VALUES(?,?)", (VERSION, json.dumps(hashes)))
    return len(projected)
