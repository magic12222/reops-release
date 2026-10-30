"""经验先检索再进入实际模型请求；全为隔离SQLite/HTTP替身。"""
from datetime import datetime, timedelta
import json

import pytest

from dashboard_api.knowledge_retrieval import retrieve_experiences
from test_dependency_records import recorded
from workbench.b_store import read_feed
from workbench.dependency_records import sync_dependency_records


def knowledge_case(tmp_path, monkeypatch):
    store, journal, _ = recorded(tmp_path, monkeypatch)
    sync_dependency_records(store, journal)
    origin = read_feed(store.path).incidents[0]
    current = origin.model_copy(deep=True, update={"id": "new-incident", "trace_id": "new-trace",
        "started_at": (datetime.fromisoformat(origin.started_at) + timedelta(seconds=1)).isoformat(),
        "status": "diagnosing", "model_calls": []})
    return store, origin, current


def test_prior_verified_experience_is_retrieved_read_only_with_exact_source(tmp_path, monkeypatch):
    store, origin, current = knowledge_case(tmp_path, monkeypatch)
    before = store.path.read_bytes()
    result = retrieve_experiences(store.path, current)
    assert result['status'] == 'hit' and len(result['matches']) == 1
    match = result['matches'][0]
    assert match['trace_id'] == origin.trace_id and match['incident_id'] == origin.id
    assert any(event.id == match['source_event_id'] for event in origin.events)
    assert match['used_as'] == 'model_context' and match['execution_applied'] is False
    assert result['execution_permission'] is False and store.path.read_bytes() == before


@pytest.mark.parametrize('change', ['retired', 'failed', 'unverified', 'other_target', 'old_profile', 'future', 'self', 'missing_check', 'missing_save'])
def test_ineligible_history_is_never_a_hit(tmp_path, monkeypatch, change):
    store, origin, current = knowledge_case(tmp_path, monkeypatch)
    if change == 'future': current.started_at = origin.started_at
    if change == 'self': current.id = origin.id
    with store.transaction() as db:
        exp = json.loads(db.execute('SELECT body FROM experiences').fetchone()[0])
        body = json.loads(db.execute('SELECT body FROM incidents').fetchone()[0])
        if change in {'retired','failed','unverified'}: exp['status'] = change
        if change == 'other_target': current.target_id = 'different-target'
        if change == 'old_profile': exp['conditions'] = ['profile=legacy']
        if change == 'missing_check': body['verification']['checks'] = ['single']
        if change == 'missing_save':
            body['events'] = [event for event in body['events'] if event['stage'] != 'experience_update']
        db.execute('UPDATE experiences SET body=?',(json.dumps(exp),))
        db.execute('UPDATE incidents SET body=?',(json.dumps(body),))
    result = retrieve_experiences(store.path, current)
    assert result['status'] == 'miss' and result['matches'] == []


def test_missing_source_reports_unavailable_without_creating_files(tmp_path, monkeypatch):
    _, _, current = knowledge_case(tmp_path, monkeypatch)
    path = tmp_path/'missing/state.sqlite3'
    assert retrieve_experiences(path,current)['status'] == 'unavailable'
    assert not path.exists()


def test_hit_is_in_actual_live_request_before_model_submission(tmp_path, monkeypatch):
    from test_dependency_diagnosis import setup
    from dashboard_api.live_conversation import LiveConversation
    import time
    store, _, _, diagnosis, _, calls = setup(tmp_path, monkeypatch)
    origin = read_feed(store.path).incidents[0]
    current = origin.model_copy(deep=True, update={"id":"new-incident", "trace_id":"new-trace",
        "started_at":(datetime.fromisoformat(origin.started_at)+timedelta(seconds=1)).isoformat(),
        "status":"diagnosing", "events":origin.events[:1], "experience_ids":[], "model_calls":[],
        "verification":origin.verification.model_copy(update={"status":"pending", "checks":[]})})
    with store.transaction() as db:
        db.execute('INSERT INTO incidents VALUES(?,?,?)',(current.id,current.model_dump_json(),'{"profile":"dependency-audit-v1"}'))
    live = LiveConversation(diagnosis,poll_seconds=.005,timeout_seconds=3)
    live.start('owner',current.id)
    deadline=time.monotonic()+2
    while not calls and time.monotonic()<deadline:time.sleep(.005)
    store.update(current.id,status='failed',verification={'status':'failed','checks':[]})
    live.workers[current.id].join(3)
    assert not live.workers[current.id].is_alive()
    first=read_feed(store.path).incidents[-1].model_calls[0]
    request=json.loads(first.request)
    assert request['knowledge_retrieval']['status']=='hit'
    match=request['knowledge_retrieval']['matches'][0]
    assert match['experience_id'] in calls[0]['messages'][-1]['content']
    assert match['trace_id']==origin.trace_id
    assert request['knowledge_retrieval']['completed_at']<=request['requested_at']


def test_lookup_endpoint_is_read_only_without_a_verified_api(tmp_path, monkeypatch):
    from test_dependency_diagnosis import setup
    from test_web_control import PREFIX
    store, client, control, _, identifier, calls = setup(tmp_path,monkeypatch)
    control.model.services[control.model.selected]['model'].verified=False
    before=store.path.read_bytes()
    response=client.get(PREFIX+'/dependency-diagnosis/knowledge/'+identifier)
    assert response.status_code==200 and response.json()['status']=='miss'
    assert calls==[] and store.path.read_bytes()==before
