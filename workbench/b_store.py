"""SQLite incident latch and durable read model; GET uses read-only connections."""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from reops_agent.contracts import validate
from reops_agent.b_clock import utc_now
from .b_privacy import dumps
from .contracts import AgentFeed, Incident


def now():
    return utc_now().isoformat()


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("b_timestamp_timezone_required")
    return parsed.timestamp()


class BStore:
    def __init__(self, path, *, source="real"):
        if source not in {"real", "offline_fixture"}:
            raise ValueError("b_source_invalid")
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(source TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS targets(
                    id TEXT PRIMARY KEY, watermark REAL NOT NULL, latched TEXT);
                CREATE TABLE IF NOT EXISTS observations(
                    target TEXT, id TEXT, PRIMARY KEY(target,id));
                CREATE TABLE IF NOT EXISTS incidents(
                    id TEXT PRIMARY KEY, body TEXT NOT NULL, meta TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    id TEXT PRIMARY KEY, incident TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS experiences(
                    id TEXT PRIMARY KEY, body TEXT NOT NULL, meta TEXT NOT NULL);
            """)
            existing = db.execute("SELECT source FROM metadata").fetchone()
            if existing and existing[0] != source:
                raise ValueError("b_store_source_conflict")
            if not existing:
                db.execute("INSERT INTO metadata VALUES(?)", (source,))
        self.source = source

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def claim(self, target, observation, *, failing, healthy, scope_key, context=None):
        """One irrevocable claim per target fault, including across process restarts."""
        sampled = instant(observation["timestamp"])
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM observations WHERE target=? AND id=?",
                          (target, observation["observation_id"])).fetchone():
                return None
            db.execute("INSERT INTO observations VALUES(?,?)", (target, observation["observation_id"]))
            row = db.execute("SELECT watermark,latched FROM targets WHERE id=?", (target,)).fetchone()
            if row and sampled <= row[0]:
                return None
            latched = row[1] if row else None
            if latched:
                origin = db.execute("SELECT body,meta FROM incidents WHERE id=?", (latched,)).fetchone()
                body, meta = json.loads(origin[0]), json.loads(origin[1])
                if ((healthy and meta.get("finished") is True and not meta.get("tool_pending"))
                        or meta["scope_key"] == "observer_unavailable" and scope_key != "observer_unavailable"):
                    latched = None
            db.execute("INSERT OR REPLACE INTO targets VALUES(?,?,?)", (target, sampled, latched))
            if latched or not failing:
                return None
            if context is not None:
                if (set(context) != {"incident_id", "trace_id"} or any(not isinstance(value, str) or not value for value in context.values())
                        or any(context[key] != observation[key] for key in context)):
                    raise ValueError("b_external_context_invalid")
                incident_id, trace_id = context["incident_id"], context["trace_id"]
            else:
                incident_id, trace_id = "incident-b-" + uuid4().hex, "trace-b-" + uuid4().hex
            incident = Incident(id=incident_id, target_id=target, trace_id=trace_id,
                title="Observed service incident", started_at=observation["timestamp"],
                status="observing", diagnosis_source="unknown", summary="observation_accepted",
                events=[], model_calls=[], experience_ids=[],
                verification={"status": "pending", "checks": []})
            meta = {"scope_key": scope_key, "source_observation_id": observation["observation_id"],
                    "source_incident_id": observation["incident_id"], "source_trace_id": observation["trace_id"],
                    "finished": False}
            db.execute("INSERT INTO incidents VALUES(?,?,?)", (incident_id, dumps(incident.model_dump()), dumps(meta)))
            db.execute("UPDATE targets SET latched=? WHERE id=?", (incident_id, target))
            return incident

    def get(self, incident_id):
        with self.transaction() as db:
            row = db.execute("SELECT body,meta FROM incidents WHERE id=?", (incident_id,)).fetchone()
            return json.loads(row[0]), json.loads(row[1])

    def update(self, incident_id, **fields):
        with self.transaction() as db:
            body = json.loads(db.execute("SELECT body FROM incidents WHERE id=?", (incident_id,)).fetchone()[0])
            body.update(fields)
            body = Incident.model_validate(body).model_dump()
            db.execute("UPDATE incidents SET body=? WHERE id=?", (dumps(body), incident_id))

    def tool_pending(self, incident_id, pending):
        with self.transaction() as db:
            meta = json.loads(db.execute("SELECT meta FROM incidents WHERE id=?", (incident_id,)).fetchone()[0])
            meta["tool_pending"] = pending
            db.execute("UPDATE incidents SET meta=? WHERE id=?", (dumps(meta), incident_id))

    def event(self, incident_id, stage, status, code, *, evidence=(), source_event=None, documents=None):
        with self.transaction() as db:
            body = json.loads(db.execute("SELECT body FROM incidents WHERE id=?", (incident_id,)).fetchone()[0])
            event = {"id": "event-b-" + uuid4().hex, "sequence": len(body["events"]),
                "timestamp": now(), "stage": stage, "status": status, "title": code,
                "detail": code, "evidence": list(evidence)}
            shared_status = {"succeeded": "success", "running": "started", "unknown": "failed"}.get(status, status)
            shared = {"schema_version": "1.0", "event_id": event["id"],
                "incident_id": incident_id, "trace_id": body["trace_id"],
                "parent_event_id": body["events"][-1]["id"] if body["events"] else None,
                "timestamp": event["timestamp"], "stage": stage, "status": shared_status,
                "message": code, "data": {"target_id": body["target_id"], "sequence": event["sequence"],
                    "source": self.source, "evidence": list(evidence)}}
            for schema, document in (documents or {}).items():
                if schema != "recovery_result":
                    raise ValueError("b_audit_document_not_allowed")
                validate(schema, document)
                if any(document[key] != shared[key] for key in ("incident_id", "trace_id")):
                    raise ValueError("b_audit_document_correlation_mismatch")
                shared["data"][schema] = document
            if source_event is not None:
                validate("agent_event", source_event)
                if (source_event["incident_id"] != incident_id or source_event["trace_id"] != body["trace_id"]
                        or source_event["stage"] != stage or source_event["status"] != shared_status
                        or source_event["parent_event_id"] != shared["parent_event_id"]
                        or source_event["data"]["sequence"] != event["sequence"]):
                    raise ValueError("b_source_event_correlation_invalid")
                shared = source_event
                event.update(id=shared["event_id"], timestamp=shared["timestamp"])
            validate("agent_event", shared)
            body["events"].append(event)
            db.execute("INSERT INTO events VALUES(?,?,?)", (event["id"], incident_id, dumps(shared)))
            db.execute("UPDATE incidents SET body=? WHERE id=?", (dumps(body), incident_id))
            return event["id"]

    def model_call(self, incident_id, call):
        with self.transaction() as db:
            body = json.loads(db.execute("SELECT body FROM incidents WHERE id=?", (incident_id,)).fetchone()[0])
            calls = [item for item in body["model_calls"] if item["id"] != call["id"]]
            body["model_calls"] = calls + [call]
            Incident.model_validate(body)
            db.execute("UPDATE incidents SET body=? WHERE id=?", (dumps(body), incident_id))

    def finish(self, incident_id, timestamp, *, recovered):
        with self.transaction() as db:
            row = db.execute("SELECT body,meta FROM incidents WHERE id=?", (incident_id,)).fetchone()
            body, meta = json.loads(row[0]), json.loads(row[1])
            meta["finished"] = True
            db.execute("UPDATE incidents SET meta=? WHERE id=?", (dumps(meta), incident_id))
            # Fresh successful Verify closes the latch. Old queued samples stay below watermark.
            db.execute("UPDATE targets SET watermark=max(watermark,?),latched=? WHERE id=? AND latched=?",
                (instant(timestamp), None if recovered else incident_id, body["target_id"], incident_id))

    def experiences(self, target):
        with self.transaction() as db:
            rows = db.execute("SELECT body,meta FROM experiences ORDER BY rowid").fetchall()
        return [(json.loads(body), json.loads(meta)) for body, meta in rows
                if json.loads(body)["target_id"] == target]

    def save_experience(self, experience, meta):
        with self.transaction() as db:
            db.execute("INSERT INTO experiences VALUES(?,?,?)", (experience["id"], dumps(experience), dumps(meta)))

    def retire(self, experience_id):
        with self.transaction() as db:
            body = json.loads(db.execute("SELECT body FROM experiences WHERE id=?", (experience_id,)).fetchone()[0])
            body["status"] = "retired"
            db.execute("UPDATE experiences SET body=? WHERE id=?", (dumps(body), experience_id))


def read_feed(path, *, allow_fixture=False):
    path = Path(path).resolve()
    if not path.is_file():
        return AgentFeed(status="not_connected", incidents=[], experiences=[])
    # No mkdir, DDL, PRAGMA writes, model import or runtime initialization in GET.
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        db.execute("BEGIN")
        source = db.execute("SELECT source FROM metadata").fetchone()[0]
        if source != "real" and not allow_fixture:
            raise ValueError("b_fixture_cannot_be_real_feed")
        incidents = [json.loads(row[0]) for row in db.execute("SELECT body FROM incidents ORDER BY rowid")]
        experiences = [json.loads(row[0]) for row in db.execute("SELECT body FROM experiences ORDER BY rowid")]
        feed = AgentFeed(status="ready", incidents=incidents, experiences=experiences)
        origins = {item.id: item for item in feed.incidents}
        exps = {item.id: item for item in feed.experiences}
        for item in feed.incidents:
            if [event.sequence for event in item.events] != list(range(len(item.events))):
                raise ValueError("b_event_sequence_conflict")
            if item.status == "recovered" and item.verification.status != "passed":
                raise ValueError("b_verification_required")
            if item.diagnosis_source == "experience" and not item.experience_ids:
                raise ValueError("b_experience_required")
            if any(key not in exps or exps[key].target_id != item.target_id for key in item.experience_ids):
                raise ValueError("b_experience_reference_invalid")
        for exp in feed.experiences:
            origin = origins.get(exp.incident_id)
            if (origin is None or origin.target_id != exp.target_id or not origin.events
                    or exp.status == "verified" and origin.verification.status != "passed"):
                raise ValueError("b_experience_origin_invalid")
        return feed
    finally:
        db.close()
