"""C-owned SQLite; never shares the fault-injection target PostgreSQL."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from reops_agent.credential_handling import redact_persistent

from .models import Event, Run, SOURCES, STATUSES

STAGES = {"observe", "failure_detection", "localization", "root_cause_analysis",
          "recovery_decision", "recovery_execution", "verification", "experience_update"}
EVENT_STATUSES = {"started", "success", "failed", "skipped", "waiting_human"}
ORIGINS = {"trace_journal", "decision_trace", "experience_update"}

RUN_COLUMNS = ("id", "incident_id", "trace_id", "source", "status", "case_id", "fault_id",
               "started_at", "finished_at", "model_calls", "action_count",
               "recovery_latency_ms", "success", "metadata")
EVENT_COLUMNS = ("event_id", "run_id", "incident_id", "trace_id", "ordinal", "stage",
                 "source", "origin", "message", "data", "parent_event_id", "case_id",
                 "status", "timestamp", "original_event_id")


class Store:
    def __init__(self, path: str | Path, *, read_only: bool = False):
        self.path = str(path)
        self.read_only = read_only
        if read_only:
            # Audits must never create a missing database or run initialization DDL.
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, trace_id TEXT NOT NULL,
                    source TEXT NOT NULL CHECK (source IN ('real','offline_fixture','simulation')),
                    status TEXT NOT NULL, case_id TEXT, fault_id TEXT, started_at TEXT,
                    finished_at TEXT, model_calls INTEGER, action_count INTEGER,
                    recovery_latency_ms REAL, success INTEGER, metadata TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runs_by_incident ON runs(incident_id, trace_id);
                CREATE INDEX IF NOT EXISTS runs_by_source_time ON runs(source, started_at DESC);
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    incident_id TEXT NOT NULL, trace_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    stage TEXT NOT NULL, source TEXT NOT NULL, origin TEXT NOT NULL,
                    message TEXT NOT NULL, data TEXT NOT NULL, parent_event_id TEXT,
                    case_id TEXT, status TEXT, timestamp TEXT, original_event_id TEXT,
                    PRIMARY KEY (run_id, event_id), UNIQUE (run_id, ordinal)
                );
            """)

    @contextmanager
    def _connect(self, *, read_only: bool = False):
        db = (sqlite3.connect(Path(self.path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
              if self.read_only or read_only else sqlite3.connect(self.path, timeout=10))
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _check_run(run: Run):
        if not run.id or not run.incident_id or not run.trace_id:
            raise ValueError("run IDs must be nonempty")
        if run.source not in SOURCES or run.status not in STATUSES:
            raise ValueError("invalid source or run status")
        for value in (run.model_calls, run.action_count):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("counts must be nonnegative integers")
        if run.recovery_latency_ms is not None:
            raise ValueError("recovery latency is not defined in Phase C1")
        if run.success is not None and type(run.success) is not bool:
            raise ValueError("success must be boolean or unknown")
        if not isinstance(run.metadata, dict):
            raise ValueError("metadata must be an object")

    @staticmethod
    def _check_event(event: Event, run: Run):
        if (event.run_id, event.incident_id, event.trace_id, event.source) != (
                run.id, run.incident_id, run.trace_id, run.source):
            raise ValueError("event correlation or provenance differs from run")
        if (not event.event_id or not event.message or event.ordinal < 0
                or event.stage not in STAGES or event.origin not in ORIGINS
                or event.status not in EVENT_STATUSES | {None}
                or not isinstance(event.data, dict)):
            raise ValueError("invalid event read model")

    @staticmethod
    def _run_values(run: Run):
        values = run.to_dict()
        values["success"] = None if run.success is None else int(run.success)
        values["metadata"] = json.dumps(redact_persistent(run.metadata), ensure_ascii=False, allow_nan=False)
        return tuple(values[name] for name in RUN_COLUMNS)

    @staticmethod
    def _event_values(event: Event):
        values = event.to_dict()
        values["data"] = json.dumps(redact_persistent(event.data), ensure_ascii=False, allow_nan=False)
        values["message"] = redact_persistent(event.message)
        return tuple(values[name] for name in EVENT_COLUMNS)

    @staticmethod
    def _read_run(row):
        if row is None:
            return None
        values = dict(row)
        values["metadata"] = json.loads(values["metadata"])
        values["success"] = None if values["success"] is None else bool(values["success"])
        return Run(**values)

    @staticmethod
    def _read_event(row):
        values = dict(row)
        values["data"] = json.loads(values["data"])
        return Event(**values)

    def create_run(self, run: Run):
        self._check_run(run)
        with self._connect() as db:
            db.execute(f"INSERT INTO runs ({','.join(RUN_COLUMNS)}) VALUES ({','.join('?' for _ in RUN_COLUMNS)})",
                       self._run_values(run))

    def update_run(self, run: Run):
        self._check_run(run)
        with self._connect() as db:
            row = db.execute("SELECT incident_id,trace_id,source FROM runs WHERE id=?", (run.id,)).fetchone()
            if row is None:
                raise KeyError(run.id)
            if (row["incident_id"], row["trace_id"], row["source"]) != (run.incident_id, run.trace_id, run.source):
                raise ValueError("run correlation and provenance are immutable")
            names = RUN_COLUMNS[1:]
            db.execute(f"UPDATE runs SET {','.join(name+'=?' for name in names)} WHERE id=?",
                       self._run_values(run)[1:] + (run.id,))

    def delete_run(self, run_id: str) -> bool:
        with self._connect() as db:
            return db.execute("DELETE FROM runs WHERE id=?", (run_id,)).rowcount > 0

    def get_run(self, run_id: str) -> Run | None:
        with self._connect() as db:
            return self._read_run(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def list_runs(self, *, source: str | None = None, limit: int = 50, offset: int = 0):
        if source is not None and source not in SOURCES:
            raise ValueError("invalid source")
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("invalid pagination")
        where = " WHERE source=?" if source else ""
        params = (source,) if source else ()
        with self._connect() as db:
            total = db.execute("SELECT COUNT(*) FROM runs" + where, params).fetchone()[0]
            rows = db.execute("SELECT * FROM runs" + where +
                              " ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?",
                              params + (limit, offset)).fetchall()
        return [self._read_run(row) for row in rows], total

    def add_events(self, run_id: str, events: list[Event]):
        with self._connect() as db:
            run = self._read_run(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
            if run is None:
                raise KeyError(run_id)
            for event in events:
                self._check_event(event, run)
                db.execute(f"INSERT INTO events ({','.join(EVENT_COLUMNS)}) VALUES ({','.join('?' for _ in EVENT_COLUMNS)})",
                           self._event_values(event))

    def put_bundle(self, run: Run, events: list[Event], *, connection=None):
        """Atomically import or refresh one trace-scoped read model."""
        if connection is None:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                return self.put_bundle(run, events, connection=db)
        self._check_run(run)
        for event in events:
            self._check_event(event, run)
        if connection is not None:
            db = connection
            existing = db.execute("SELECT incident_id,trace_id,source FROM runs WHERE id=?", (run.id,)).fetchone()
            if existing and (existing["incident_id"], existing["trace_id"], existing["source"]) != (
                    run.incident_id, run.trace_id, run.source):
                raise ValueError("run correlation and provenance are immutable")
            incoming = {event.event_id: event for event in events}
            for row in db.execute("SELECT * FROM events WHERE run_id=?", (run.id,)):
                old = self._read_event(row)
                # Synthesized decision_trace rows may be replaced by the original journal.
                if old.origin == "decision_trace":
                    continue
                new = incoming.get(old.event_id)
                if new is None or replace(old, ordinal=new.ordinal,
                        case_id=old.case_id or new.case_id) != new:
                    raise ValueError("conflicting or truncated imported evidence")
            db.execute(f"INSERT INTO runs ({','.join(RUN_COLUMNS)}) VALUES ({','.join('?' for _ in RUN_COLUMNS)}) "
                       f"ON CONFLICT(id) DO UPDATE SET {','.join(name+'=excluded.'+name for name in RUN_COLUMNS[1:])}",
                       self._run_values(run))
            db.execute("DELETE FROM events WHERE run_id=?", (run.id,))
            db.executemany(f"INSERT INTO events ({','.join(EVENT_COLUMNS)}) VALUES ({','.join('?' for _ in EVENT_COLUMNS)})",
                           [self._event_values(event) for event in events])

    def list_events(self, run_id: str):
        with self._connect() as db:
            rows = db.execute("SELECT * FROM events WHERE run_id=? ORDER BY ordinal",
                              (run_id,)).fetchall()
        return [self._read_event(row) for row in rows]

    def snapshot(self, run_id: str):
        """Read one committed run and its events in the same SQLite snapshot."""
        with self._connect() as db:
            db.execute("BEGIN")
            run = self._read_run(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
            if run is None:
                return None
            rows = db.execute("SELECT * FROM events WHERE run_id=? ORDER BY ordinal",
                              (run_id,)).fetchall()
            return run, [self._read_event(row) for row in rows]

    def incident_snapshots(self, incident_id: str, trace_id: str, *, source: str):
        """Exact correlation only; both Run and Event sets share one committed snapshot."""
        if source not in SOURCES:
            raise ValueError('invalid source')
        with self._connect(read_only=True) as db:
            db.execute('BEGIN')
            runs = db.execute('SELECT * FROM runs WHERE incident_id=? AND trace_id=? AND source=? ORDER BY id',
                              (incident_id, trace_id, source)).fetchall()
            result = []
            for row in runs:
                run = self._read_run(row)
                events = [self._read_event(e) for e in db.execute(
                    'SELECT * FROM events WHERE run_id=? ORDER BY ordinal', (run.id,))]
                for event in events:
                    self._check_event(event, run)
                result.append((run, events))
            return result

    def append_live(self, run: Run, event: Event):
        """Append one already-durable B journal event without reordering or replaying it."""
        self._check_run(run)
        self._check_event(event, run)
        if event.origin != "trace_journal" or event.ordinal != 0:
            raise ValueError("live input must be one TraceJournal event")
        with self._connect() as db:
            prior = self._read_run(db.execute("SELECT * FROM runs WHERE id=?", (run.id,)).fetchone())
            if prior is not None:
                if (prior.incident_id, prior.trace_id, prior.source) != (
                        run.incident_id, run.trace_id, run.source):
                    raise ValueError("run correlation and provenance are immutable")
                if prior.metadata.get("ingest_kind") != "trace_journal":
                    raise ValueError("live append cannot overwrite a merged import")
                if prior.case_id and run.case_id and prior.case_id != run.case_id:
                    raise ValueError("conflicting case_id in live trace")
            row = db.execute("SELECT * FROM events WHERE run_id=? AND event_id=?",
                             (run.id, event.event_id)).fetchone()
            if row is not None:
                stored = self._read_event(row)
                replay = replace(event, ordinal=stored.ordinal,
                                 case_id=event.case_id or stored.case_id)
                if stored != replay:
                    raise ValueError("conflicting replayed event")
                return prior, stored, False
            last = db.execute("SELECT event_id,ordinal FROM events WHERE run_id=? ORDER BY ordinal DESC LIMIT 1",
                              (run.id,)).fetchone()
            if event.parent_event_id != (last["event_id"] if last else None):
                raise ValueError("live parent_event_id does not match preceding event")
            event = replace(event, ordinal=last["ordinal"] + 1 if last else 0)
            if prior is not None:
                terminal = {"recovered", "failed", "inconclusive"}
                if prior.status in terminal and run.status == "unknown":
                    run = replace(run, status=prior.status, success=prior.success,
                                  finished_at=prior.finished_at)
                run = replace(run, started_at=prior.started_at or run.started_at,
                              case_id=prior.case_id or run.case_id)
                names = RUN_COLUMNS[1:]
                db.execute(f"UPDATE runs SET {','.join(name+'=?' for name in names)} WHERE id=?",
                           self._run_values(run)[1:] + (run.id,))
            else:
                db.execute(f"INSERT INTO runs ({','.join(RUN_COLUMNS)}) VALUES ({','.join('?' for _ in RUN_COLUMNS)})",
                           self._run_values(run))
            db.execute(f"INSERT INTO events ({','.join(EVENT_COLUMNS)}) VALUES ({','.join('?' for _ in EVENT_COLUMNS)})",
                       self._event_values(event))
            return run, event, True
