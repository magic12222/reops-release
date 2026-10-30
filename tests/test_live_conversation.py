"""Real checkpoint ordering and non-blocking multi-turn conversations; fake HTTP only."""
import json
from threading import Event
import time

import httpx
import pytest

from dashboard_api.dependency_diagnosis import DependencyDiagnosis
from dashboard_api.live_conversation import LiveConversation, PROFILE
from workbench.b_store import read_feed
from workbench.dependency_records import sync_dependency_records
from test_dependency_records import recorded
from test_web_control import client, headers, PREFIX, SECRET


def setup_live(tmp_path, monkeypatch, *, fail_first=False):
    store, path, _ = recorded(tmp_path, monkeypatch)
    lines = path.read_text().splitlines()
    fault = next(index for index,line in enumerate(lines) if json.loads(line)['event']=='fault_confirmed')
    sql = next(index for index,line in enumerate(lines) if json.loads(line)['event']=='sql_ready')
    path.write_text('\n'.join(lines[:fault+1])+'\n')
    sync_dependency_records(store,path)
    c,control=client(tmp_path/'api')
    calls=[]
    entered=Event();release=Event()
    def gateway(request):
        body=json.loads(request.content)
        calls.append(body)
        if len(calls)==1:
            entered.set()
            assert release.wait(3)
            if fail_first:return httpx.Response(500,json={'error':'private gateway body '+SECRET})
        return httpx.Response(200,json={'choices':[{'message':{'content':f'Actual reply for round {len(calls)}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':10,'completion_tokens':5}})
    d=c.app.state.dependency_diagnosis
    d.path=store.path;d.transport=httpx.MockTransport(gateway)
    live=LiveConversation(d,poll_seconds=.005,timeout_seconds=4)
    c.app.state.live_conversation.diagnosis=d
    identifier=read_feed(store.path).incidents[0].id
    return store,path,lines,sql,c,control,d,live,identifier,calls,entered,release


def wait_until(predicate):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.005)
    raise AssertionError('offline conversation did not reach checkpoint')


def test_three_real_turns_overlap_recovery_and_include_actual_prior_reply(tmp_path,monkeypatch):
    store,path,lines,sql,_,control,d,live,identifier,calls,entered,release=setup_live(tmp_path,monkeypatch)
    result=live.start('owner',identifier)
    assert not result['existing'] and result['max_model_calls']==3 and entered.wait(2)
    assert len(calls)==1 and read_feed(store.path).incidents[0].status=='diagnosing'
    request=json.loads(read_feed(store.path).incidents[0].model_calls[0].request)
    assert request['knowledge_retrieval']['status']=='miss'
    assert '先检索已验证经验库' in calls[0]['messages'][-1]['content']
    assert request['knowledge_retrieval']['completed_at'] <= request['requested_at']
    assert 'recovery_verified' not in json.dumps(calls[0])
    # Recovery records can advance while the first model request is still blocked.
    path.write_text('\n'.join(lines[:sql+1])+'\n')
    sync_dependency_records(store,path)
    assert read_feed(store.path).incidents[0].status=='verifying'
    assert live.start('another-tab',identifier)['existing'] and len(calls)==1
    release.set()
    wait_until(lambda:len(calls)==2)
    assert any(m['role']=='assistant' and m['content']=='Actual reply for round 1' for m in calls[1]['messages'])
    assert 'Recovery verified' not in calls[1]['messages'][-1]['content']
    path.write_text('\n'.join(lines)+'\n')
    sync_dependency_records(store,path)
    live.workers[identifier].join(3)
    assert not live.workers[identifier].is_alive() and len(calls)==3
    assert any(m['content']=='Actual reply for round 2' for m in calls[2]['messages'])
    incident=read_feed(store.path).incidents[0]
    assert incident.status=='recovered' and incident.diagnosis_source=='rule'
    assert [json.loads(call.request)['phase'] for call in incident.model_calls]==['diagnosis','progress','verification']
    assert all(json.loads(call.request)['analysis_mode']==PROFILE for call in incident.model_calls)
    assert all(call.status=='succeeded' for call in incident.model_calls)
    assert 'api_key' not in json.dumps(calls) and SECRET.encode() not in store.path.read_bytes()
    assert live.start('reload',identifier)['existing']
    assert d.analyze('reload',identifier)['live'] and len(calls)==3
    assert LiveConversation(d).start('after-restart',identifier)['existing']


def test_failed_round_is_not_fabricated_as_an_assistant_message(tmp_path,monkeypatch):
    store,path,lines,_,_,_,_,live,identifier,calls,entered,release=setup_live(tmp_path,monkeypatch,fail_first=True)
    live.start('owner',identifier);assert entered.wait(2)
    path.write_text('\n'.join(lines)+'\n');sync_dependency_records(store,path);release.set()
    live.workers[identifier].join(3)
    assert len(calls)==3
    assert not any(m['role']=='assistant' for m in calls[1]['messages'])
    first=read_feed(store.path).incidents[0].model_calls[0]
    assert first.status=='failed' and json.loads(first.response)['content'] is None
    assert 'private gateway body' not in first.response


def test_live_does_not_reconstruct_a_past_recovery_as_live(tmp_path,monkeypatch):
    store,path,lines,_,_,_,_,live,identifier,calls,_,_=setup_live(tmp_path,monkeypatch)
    path.write_text('\n'.join(lines)+'\n');sync_dependency_records(store,path)
    with pytest.raises(ValueError,match='requires_active'):
        live.start('owner',identifier)
    assert calls==[]


def test_live_post_needs_csrf_but_no_per_round_approval(tmp_path,monkeypatch):
    store,path,lines,_,c,_,_,_,identifier,calls,entered,release=setup_live(tmp_path,monkeypatch)
    route=PREFIX+'/dependency-diagnosis/live'
    assert c.post(route,headers={'Origin':'http://127.0.0.1:5173'},json={'incident_id':identifier}).status_code==403
    result=c.post(route,headers=headers(c),json={'incident_id':identifier})
    assert result.status_code==200 and entered.wait(2)
    path.write_text('\n'.join(lines)+'\n');sync_dependency_records(store,path);release.set()
    worker=c.app.state.live_conversation.workers[identifier];worker.join(3)
    assert len(calls)==3 and not worker.is_alive()
