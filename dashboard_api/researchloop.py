"""数据库场景独立C台账；终端或独立网页人工授权入口领取，证据HTTP只读，不改变原C4。"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from reops_agent.credential_handling import redact_persistent
from reops_agent.docker_executor import now
from reops_agent.researchloop_recovery import SCENARIO, success_evidence
from reops_agent.researchloop_backend import healthy


class DatabaseLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS researchloop_experiments (id TEXT PRIMARY KEY, body TEXT NOT NULL)")

    def list(self):
        with closing(sqlite3.connect(self.path)) as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM researchloop_experiments ORDER BY rowid DESC LIMIT 100")]

    def claim_new(self, context):
        # 持久running/unknown保留阻断；此入口不提供自动清除或重放。
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            records = [json.loads(row[0]) for row in db.execute("SELECT body FROM researchloop_experiments")]
            if any(item.get("state") != "finished" or item.get("review_required") is not False for item in records):
                raise ValueError("database_experiment_requires_operator_inspection")
            record = {"id": "experiment-researchloop-" + uuid4().hex, **context, "scenario": SCENARIO,
                "source": "real", "state": "waiting_authorization", "result": "unknown",
                "review_required": True, "created_at": now()}
            db.execute("INSERT INTO researchloop_experiments VALUES (?,?)", (record["id"], json.dumps(record)))
        return record

    def finish(self, experiment_id, report, *, saved=False):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM researchloop_experiments WHERE id=?", (experiment_id,)).fetchone()
            if row is None:
                raise ValueError("database_experiment_missing")
            record = json.loads(row[0])
            if record["state"] != "waiting_authorization" or any(
                    record[key] != report.get(key) for key in ("incident_id", "trace_id")):
                raise ValueError("database_experiment_correlation_or_replay_rejected")
            passed = (saved is True and success_evidence(report) and report.get("memory_written") is True
                and report.get("acceptance_passed") is True and report.get("cleanup_outcome") == "succeeded"
                and healthy(report.get("final_observation", {})))
            final = report.get("final_observation")
            clean = (isinstance(final, dict) and healthy(final) and report.get("cleanup_outcome") == "succeeded"
                and final.get("incident_id") == record["incident_id"]
                and final.get("trace_id") == report.get("cleanup_trace_id")
                and report.get("execution_outcome") in {"not_run", "succeeded", "failed"})
            # 没有注入的拒绝，只有基线已健康才允许解除本条占用。
            rejected = (saved is True and report.get("fault_injection_attempted") is False
                and report.get("executor_called") is False and healthy(report.get("baseline", {})))
            passed = passed and clean
            inconsistent = report.get("acceptance_passed") is True and not passed
            if inconsistent:
                clean = rejected = False
            record.update(state="finished", finished_at=now(), result="passed" if passed else
                "rejected" if rejected else "failed" if clean and saved else "unknown",
                review_required=not (passed or rejected or clean and saved),
                report=redact_persistent(report))
            db.execute("UPDATE researchloop_experiments SET body=? WHERE id=?",
                       (json.dumps(record, allow_nan=False), experiment_id))
        return record


def read_records(path):
    """HTTP读取不创建新台账；旧C数据库兼容。"""
    with closing(sqlite3.connect(path)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='researchloop_experiments'").fetchone() is None:
            return []
        return [json.loads(row[0]) for row in db.execute(
            "SELECT body FROM researchloop_experiments ORDER BY rowid DESC LIMIT 100")]
