"""真实格式审计的离线投影：幂等、冲突、双验证、来源和旧 Memory 隔离。"""
import json

import pytest

from workbench.b_store import BStore, read_feed
from workbench.dependency_records import sync_dependency_records
from test_vikunja_dependency import fixture, trigger


def recorded(tmp_path, monkeypatch):
    monitor, backend, automation, clock = fixture(tmp_path / "audit", monkeypatch)
    trigger(monitor, automation)
    return BStore(tmp_path / "records/state.sqlite3"), tmp_path / "audit/events.jsonl", automation


def test_real_dependency_event_format_persists_without_recovery_or_legacy_memory(tmp_path, monkeypatch):
    store, path, automation = recorded(tmp_path, monkeypatch)
    before = path.read_bytes()
    assert sync_dependency_records(store, path) == 1
    feed = read_feed(store.path)
    assert len(feed.incidents) == len(feed.experiences) == 1
    incident, exp = feed.incidents[0], feed.experiences[0]
    assert incident.status == "recovered" and exp.status == "verified"
    assert len(incident.verification.checks) == 2
    assert "original_b_agent_closed_loop=false" in exp.conditions
    assert not incident.model_calls and not list(tmp_path.rglob("b-memory"))
    assert "query=SELECT 1" in next(e for e in incident.events if e.title == "SQL readiness check").evidence
    assert sync_dependency_records(store, path) == 1
    assert read_feed(store.path) == feed and path.read_bytes() == before
    assert automation.actions == 1


@pytest.mark.parametrize("change", ["prefix", "truncate", "bad_json"])
def test_journal_changes_never_replace_saved_evidence(tmp_path, monkeypatch, change):
    store, path, _ = recorded(tmp_path, monkeypatch)
    sync_dependency_records(store, path)
    before = read_feed(store.path)
    raw = path.read_bytes()
    if change == "prefix": raw = raw.replace(b'fault_confirmed', b'fault_rewritten', 1)
    if change == "truncate": raw = raw[:-1]
    if change == "bad_json": raw += b'not json\n'
    path.write_bytes(raw)
    with pytest.raises(ValueError): sync_dependency_records(store, path)
    assert read_feed(store.path) == before


@pytest.mark.parametrize("change", ["missing_check", "duplicate_sample", "wrong_order", "failure", "missing_sql"])
def test_incomplete_or_failed_evidence_cannot_be_verified(tmp_path, monkeypatch, change):
    store, path, _ = recorded(tmp_path, monkeypatch)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if change == "missing_check": rows = [r for r in rows if not (r["event"] == "verification_passed" and r["check"] == 2)]
    if change == "duplicate_sample":
        checks = [r for r in rows if r["event"] == "verification_passed"]
        checks[1]["observation_id"] = checks[0]["observation_id"]
    if change == "wrong_order":
        checks = [r for r in rows if r["event"] == "verification_passed"]
        checks[1]["check"] = 1
    if change == "failure": rows[-1]["event"] = "recovery_requires_attention"
    if change == "missing_sql": rows = [r for r in rows if r["event"] != "sql_ready"]
    path.write_text("".join(json.dumps(r)+"\n" for r in rows))
    sync_dependency_records(store, path)
    assert read_feed(store.path).experiences[0].status != "verified"


def test_append_keeps_model_records_and_retirement(tmp_path, monkeypatch):
    store, path, _ = recorded(tmp_path, monkeypatch)
    sync_dependency_records(store, path)
    feed = read_feed(store.path)
    store.model_call(feed.incidents[0].id, {"id":"call-test", "model":"fixture", "status":"unknown",
        "request":"fixture", "response":None, "duration_ms":None,"input_tokens":None,"output_tokens":None,"redacted":True})
    store.retire(feed.experiences[0].id)
    with path.open("a") as handle: handle.write(json.dumps({"event":"policy_disabled"})+"\n")
    sync_dependency_records(store, path)
    after = read_feed(store.path)
    assert after.experiences[0].status == "retired" and len(after.incidents[0].model_calls) == 1


def test_existing_incident_conflict_rolls_back(tmp_path, monkeypatch):
    store, path, _ = recorded(tmp_path, monkeypatch)
    sync_dependency_records(store, path)
    with store.transaction() as db:
        db.execute("UPDATE incidents SET meta=?", ('{"profile":"legacy"}',))
    before = read_feed(store.path)
    with pytest.raises(ValueError, match="conflict"): sync_dependency_records(store, path)
    assert read_feed(store.path) == before


def test_partial_run_does_not_create_a_learning_stage_or_success(tmp_path, monkeypatch):
    store, path, _ = recorded(tmp_path, monkeypatch)
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:4])+"\n")
    sync_dependency_records(store, path)
    partial = read_feed(store.path)
    assert partial.experiences[0].status == "unverified"
    assert not any(event.stage == "experience_update" for event in partial.incidents[0].events)
    path.write_text("\n".join(lines)+"\n")
    sync_dependency_records(store, path)
    completed = read_feed(store.path)
    assert completed.experiences[0].status == "verified"
    assert completed.incidents[0].events[-1].stage == "experience_update"
