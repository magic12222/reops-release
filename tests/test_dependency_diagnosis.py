"""独立依赖诊断批准：纯替身 HTTP，不调用模型或 Docker。"""
import json

import httpx
import pytest

from dashboard_api.dependency_diagnosis import DependencyDiagnosis
from workbench.b_store import read_feed
from workbench.dependency_records import sync_dependency_records
from test_dependency_records import recorded
from test_web_control import client, headers, model, SECRET, PREFIX


def setup(tmp_path, monkeypatch, *, mode="ok"):
    store, path, _ = recorded(tmp_path, monkeypatch)
    sync_dependency_records(store, path)
    c, control = client(tmp_path / "api")
    identifier = read_feed(store.path).incidents[0].id
    calls = []
    def transport(request):
        calls.append(json.loads(request.content))
        if mode == "auth": return httpx.Response(401, content=b'private authentication body')
        if mode == "timeout": raise httpx.ReadTimeout("private message " + SECRET)
        result = {"root_cause":"Observed dependency failure " + SECRET, "evidence_event_ids":[],
            "suggested_plan":"no_action", "uncertainty":"retrospective only"}
        if mode == "invented_event": result["evidence_event_ids"] = ["invented"]
        if mode == "shell": result["suggested_plan"] = "run_shell"
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(result)}}],
            **({"usage":{"prompt_tokens":13,"completion_tokens":7,"total_tokens":20}} if mode != "missing_usage" else {})})
    diagnosis = c.app.state.dependency_diagnosis
    diagnosis.path = store.path
    diagnosis.transport = httpx.MockTransport(transport)
    return store, c, control, diagnosis, identifier, calls


def test_prepare_has_no_inference_and_approval_is_single_owner_config_bound(tmp_path, monkeypatch):
    store, _, control, d, identifier, calls = setup(tmp_path, monkeypatch)
    offer = d.prepare("owner", identifier)
    assert calls == [] and SECRET not in json.dumps(offer)
    with pytest.raises(ValueError): d.approve("another", offer["id"])
    result = d.approve("owner", offer["id"])
    assert len(calls) == 1 and calls[0] == offer["request"]
    assert calls[0]["max_tokens"] == 512 and "tools" not in calls[0]
    assert result["call"]["input_tokens"] == 13 and result["call"]["output_tokens"] == 7
    assert SECRET not in json.dumps(result)
    with pytest.raises(ValueError): d.approve("owner", offer["id"])
    second = d.prepare("owner", identifier)
    with pytest.raises(ValueError): d.approve("owner", second["id"])
    assert len(calls) == 1
    assert SECRET.encode() not in store.path.read_bytes()
    assert read_feed(store.path).incidents[0].diagnosis_source == "rule"


@pytest.mark.parametrize("mode", ["auth","timeout","invented_event","shell","missing_usage"])
def test_unknown_or_missing_usage_never_retries_or_fabricates_tokens(tmp_path, monkeypatch, mode):
    store, _, _, d, identifier, calls = setup(tmp_path, monkeypatch, mode=mode)
    result = d.approve("owner", d.prepare("owner", identifier)["id"])["call"]
    assert len(calls) == 1
    assert result["status"] == ("succeeded" if mode == "missing_usage" else "failed" if mode == "auth" else "unknown")
    expected = (13, 7) if mode in {"invented_event", "shell"} else (None, None)
    assert (result["input_tokens"], result["output_tokens"]) == expected
    assert SECRET not in json.dumps(result) and "private authentication body" not in json.dumps(result)
    with pytest.raises(ValueError): d.approve("owner", d.prepare("owner", identifier)["id"])
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["revision","expiry","unverified","disabled"])
def test_stale_approval_rejected_before_network(tmp_path, monkeypatch, change):
    _, _, control, d, identifier, calls = setup(tmp_path, monkeypatch)
    offer = d.prepare("owner", identifier)
    if change == "revision": control.model.services[control.model.selected]["revision"] = "new-revision"
    if change == "expiry": d.clock = lambda: 1e20
    if change == "unverified": control.model.services[control.model.selected]["model"].verified = False
    if change == "disabled": control.enabled = False
    with pytest.raises(ValueError): d.approve("owner", offer["id"])
    assert calls == []


def test_http_guard_rejects_old_recovery_approval_and_missing_csrf(tmp_path, monkeypatch):
    _, c, _, d, identifier, calls = setup(tmp_path, monkeypatch)
    # Explicitly verify the installed original routes still enforce CSRF before lookup/network.
    response = c.post(PREFIX+"/dependency-diagnosis/approve",headers={"Origin":"http://127.0.0.1:5173"},json={"approved":True,"offer_id":"old-policy"})
    assert response.status_code == 403
    response = c.post(PREFIX+"/dependency-diagnosis/approve",headers=headers(c),json={"approved":True,"offer_id":"old-policy"})
    assert response.status_code == 409 and calls == []
    h = headers(c)
    offer = c.post(PREFIX+"/dependency-diagnosis/prepare", headers=h, json={"incident_id":identifier})
    assert offer.status_code == 200 and calls == []
    result = c.post(PREFIX+"/dependency-diagnosis/approve", headers=h, json={"approved":True,"offer_id":offer.json()["id"]})
    assert result.status_code == 200 and len(calls) == 1


def test_connection_status_has_no_inference_or_approval(tmp_path, monkeypatch):
    store,c,control,d,identifier,calls=setup(tmp_path,monkeypatch)
    response=c.get(PREFIX+'/dependency-diagnosis/status')
    assert response.status_code==200
    assert response.json()=={'available':True,'profile':'dependency-audit-v1','advisory_only':True,'store_ready':True,'automatic_conversation':True,'live_conversation':True,'max_live_rounds':3}
    assert calls==[] and SECRET not in response.text


def test_automatic_conversation_is_durable_and_does_not_need_per_call_approval(tmp_path, monkeypatch):
    store, _, control, d, identifier, calls = setup(tmp_path, monkeypatch)
    first = d.analyze("owner", identifier, background=False)
    second = DependencyDiagnosis(control, store.path, transport=d.transport).analyze("another-tab", identifier)
    assert second["existing"] and second["call_id"] == first["call_id"]
    assert len(calls) == 1 and calls[0]["stream"] is True
    assert "response_format" not in calls[0] and "tools" not in calls[0]
    assert calls[0]["max_tokens"] == 512
    assert "source_sha256" not in calls[0]["messages"][1]["content"]
    incident = read_feed(store.path).incidents[0]
    assert incident.model_calls[0].status == "succeeded" and incident.diagnosis_source == "rule"
    assert SECRET.encode() not in store.path.read_bytes()


def test_stream_persists_real_partial_reply_before_completion_without_reasoning(tmp_path, monkeypatch):
    store, _, _, d, identifier, _ = setup(tmp_path, monkeypatch)
    observed = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"first reply"}}]}\n\n'
            calls = read_feed(store.path).incidents[0].model_calls
            observed.append(json.loads(calls[0].response)["content"])
            yield b'data: {"choices":[{"delta":{"reasoning_content":"private reasoning","content":" continued"},"finish_reason":"stop"}],"usage":{"prompt_tokens":21,"completion_tokens":9}}\n\n'
            yield b'data: [DONE]\n\n'
    ticks = iter(range(100))
    d.clock = lambda: next(ticks)
    d.transport = httpx.MockTransport(lambda _: httpx.Response(200,headers={"content-type":"text/event-stream"},stream=Stream()))
    d.analyze("owner", identifier, background=False)
    assert observed == ["first reply"]
    call = read_feed(store.path).incidents[0].model_calls[0]
    assert call.status == "succeeded" and json.loads(call.response)["content"] == "first reply continued"
    assert (call.input_tokens, call.output_tokens) == (21, 9)
    assert b'private reasoning' not in store.path.read_bytes()


@pytest.mark.parametrize("mode,code", [("auth","authentication_rejected"),("timeout","model_timeout")])
def test_automatic_failure_is_system_status_not_model_text_and_never_retries(tmp_path, monkeypatch, mode, code):
    store, _, _, d, identifier, calls = setup(tmp_path, monkeypatch, mode=mode)
    d.analyze("owner", identifier, background=False)
    d.analyze("owner", identifier, background=False)
    call = read_feed(store.path).incidents[0].model_calls[0]
    assert len(calls) == 1
    assert json.loads(call.response)["content"] is None and json.loads(call.response)["error"] == code
    assert SECRET not in call.response and 'private authentication' not in call.response


def test_new_conversation_preserves_legacy_failure_ledger(tmp_path, monkeypatch):
    store, _, _, d, identifier, calls = setup(tmp_path, monkeypatch, mode="auth")
    d.approve("owner", d.prepare("owner", identifier)["id"])
    legacy = read_feed(store.path).incidents[0].model_calls[0]
    d.analyze("owner", identifier, background=False)
    incident = read_feed(store.path).incidents[0]
    assert len(calls) == 2 and incident.model_calls[0] == legacy
    d.analyze("new-tab", identifier, background=False)
    assert len(calls) == 2


def test_automatic_route_keeps_same_origin_session_guard(tmp_path, monkeypatch):
    _, c, _, d, identifier, calls = setup(tmp_path, monkeypatch)
    route = PREFIX + '/dependency-diagnosis/analyze'
    assert c.post(route, headers={"Origin":"http://127.0.0.1:5173"},json={"incident_id":identifier}).status_code == 403
    original = d.analyze
    d.analyze = lambda owner, identifier: original(owner, identifier, background=False)
    result = c.post(route, headers=headers(c), json={"incident_id":identifier})
    assert result.status_code == 200 and len(calls) == 1
    assert c.post(route, headers=headers(c), json={"incident_id":identifier}).json()["existing"]
    assert len(calls) == 1


def test_one_new_verified_configuration_can_replace_rejected_gateway_request(tmp_path, monkeypatch):
    store, _, control, d, identifier, calls = setup(tmp_path, monkeypatch, mode="auth")
    d.analyze("owner", identifier, background=False)
    for revision in ("new-config", "third-config"):
        control.model.services[control.model.selected]["revision"] = revision
        d.analyze("owner", identifier, background=False)
    assert len(calls) == 2 and len(read_feed(store.path).incidents[0].model_calls) == 2


def test_unknown_network_outcome_never_repeats_on_configuration_change(tmp_path, monkeypatch):
    _, _, control, d, identifier, calls = setup(tmp_path, monkeypatch, mode="timeout")
    d.analyze("owner", identifier, background=False)
    control.model.services[control.model.selected]["revision"] = "new-config"
    d.analyze("owner", identifier, background=False)
    assert len(calls) == 1
