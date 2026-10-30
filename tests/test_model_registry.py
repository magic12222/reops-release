"""多模型管理/出口边界离线验证，绝不向真实供应商发送测试凭据。"""
import json
from threading import Event

import httpcore
import httpx
import pytest

from dashboard_api.model_endpoints import PublicBackend, validate_endpoint, public_transport, WebRCAProvider
from dashboard_api.model_registry import ModelRegistry
from dashboard_api.web_model import WebModel, BASE, MODEL
from reops_agent.nexent_provider import NexentConfig, WEB_TRANSPORT
from test_web_control import client, model, headers, PREFIX, SECRET, wait


def fields(**changes):
    return {"name": "科研模型", "provider": "自定义提供商", "model": "custom-model",
        "endpoint": "https://models.example.com/v1", "api_key": SECRET, **changes}


def test_add_edit_keep_key_select_verify_and_snapshot_do_not_persist_or_leak(tmp_path):
    registry = ModelRegistry(model())
    original = registry.for_run()
    new = registry.save(fields())
    assert registry.status()["id"] == "builtin-dlut" and registry.verified
    assert new["verified"] is False and SECRET not in json.dumps(registry.status())
    edited = registry.save(fields(name="新名称", api_key=""), new["id"])
    assert edited["revision"] != new["revision"] and not edited["verified"]
    assert not list(tmp_path.iterdir())
    registry.select(new["id"])
    with pytest.raises(ValueError, match="not_verified"):
        registry.for_run()
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "custom-model"}]})
    registry.verify(new["id"], httpx.MockTransport(handle))
    snapshot = registry.for_run()
    assert snapshot.api_base == "https://models.example.com/v1" and snapshot.model_id == "custom-model"
    assert snapshot.enable_real_model and snapshot.api_key == SECRET
    assert requests[0].url == "https://models.example.com/v1/models"
    assert requests[0].headers["authorization"] == "Bearer " + SECRET
    registry.select("builtin-dlut")
    assert not registry.verified and snapshot.api_base != original.api_base
    registry.save(fields(api_key="", model="another-model"), new["id"])
    assert snapshot.model_id == "custom-model"  # frozen submitted job config


def test_changed_endpoint_requires_explicit_key_and_validation_is_atomic():
    registry = ModelRegistry(model())
    saved = registry.save(fields())
    before = registry.status()
    with pytest.raises(ValueError, match="requires_key"):
        registry.save(fields(endpoint="https://new.example.com/v1", api_key=""), saved["id"])
    assert registry.status() == before
    with pytest.raises(ValueError, match="not_found"):
        registry.save(fields(), "missing")
    assert len(registry.status()["services"]) == 2
    for index in range(14):
        registry.save(fields(name=str(index)))
    with pytest.raises(ValueError, match="service_limit"):
        registry.save(fields())


def test_candidate_edit_preserves_active_config_proof_and_binding():
    registry=ModelRegistry(model())
    before=registry.status()
    binding=registry.binding()
    snapshot=registry.for_run()
    candidate=registry.save(fields(),before['id'],preserve_active=True)
    assert candidate['id']!=before['id'] and not candidate['active'] and not candidate['verified']
    assert registry.status()['id']==before['id'] and registry.verified
    assert registry.binding()==binding and registry.for_run()==snapshot
    assert SECRET not in json.dumps(registry.status())
    edited=registry.save(fields(api_key='',name='Candidate edited'),candidate['id'],preserve_active=True)
    assert edited['id']==candidate['id'] and len(registry.services)==2
    registry.select(candidate['id'])
    assert registry.status()['id']==candidate['id'] and not registry.verified
    with pytest.raises(ValueError,match='not_verified'):registry.for_run()


def test_candidate_capacity_failure_does_not_overwrite_active():
    registry=ModelRegistry(model())
    for index in range(15):registry.save(fields(name=str(index)))
    before=registry.status()
    with pytest.raises(ValueError,match='service_limit'):
        registry.save(fields(),before['id'],preserve_active=True)
    assert registry.status()==before and registry.verified


def test_http_edit_active_returns_candidate_and_keeps_current(tmp_path):
    c,control=client(tmp_path)
    h=headers(c)
    original=control.model.binding()
    saved=c.put(PREFIX+'/services/builtin-dlut',headers=h,json={**fields(),'as_candidate':True})
    assert saved.status_code==200
    assert saved.json()['id']!='builtin-dlut' and saved.json()['active'] is False
    current=c.get(PREFIX+'/status').json()['model']
    assert current['id']=='builtin-dlut' and current['verified'] is True
    assert control.model.binding()==original and SECRET not in json.dumps(current)


def test_stale_candidate_revision_is_rejected_without_changing_any_connection():
    registry=ModelRegistry(model())
    first=registry.save(fields())
    registry.save(fields(name='Newer candidate'),first['id'],expected_revision=first['revision'])
    before=registry.status()
    with pytest.raises(ValueError,match='revision_conflict'):
        registry.save(fields(name='Stale candidate'),first['id'],expected_revision=first['revision'])
    assert registry.status()==before and registry.verified


def test_http_candidate_revision_conflict_and_fixed_payload(tmp_path):
    c,control=client(tmp_path);h=headers(c)
    saved=c.post(PREFIX+'/services',headers=h,json=fields()).json()
    payload={**fields(api_key='',name='New candidate'),'expected_revision':saved['revision']}
    assert c.put(PREFIX+'/services/'+saved['id'],headers=h,json=payload).status_code==200
    before=control.model.status()
    rejected=c.put(PREFIX+'/services/'+saved['id'],headers=h,json=payload)
    assert rejected.status_code==409 and rejected.json()['detail']=='model_service_revision_conflict'
    assert control.model.status()==before and SECRET not in rejected.text
    for revision in [None,False,{},'']:
        assert c.put(PREFIX+'/services/'+saved['id'],headers=h,json={**payload,'expected_revision':revision}).status_code==422
    assert c.post(PREFIX+'/services',headers=h,json=payload).status_code==422
    assert c.put(PREFIX+'/services/'+saved['id'],headers=h,json={**payload,'as_candidate':'true'}).status_code==422


def test_legacy_explicit_key_update_does_not_silently_fork_service(tmp_path):
    c,control=client(tmp_path);h=headers(c)
    saved=c.put(PREFIX+'/services/builtin-dlut',headers=h,json=fields())
    assert saved.status_code==200 and saved.json()['id']=='builtin-dlut'
    assert not control.model.verified and len(control.model.services)==1


def test_candidate_http_flow_uses_selected_verified_config_for_job(tmp_path,monkeypatch):
    c,control=client(tmp_path);h=headers(c)
    old_binding=control.model.binding()
    old=control.model.status()
    saved=c.put(PREFIX+'/services/builtin-dlut',headers=h,json={**fields(),
        'as_candidate':True,'expected_revision':old['revision']}).json()
    assert control.model.binding()==old_binding
    identifier=saved['id']
    assert c.post(PREFIX+'/services/'+identifier+'/select',headers=h,json={}).status_code==200
    assert c.post(PREFIX+'/jobs',headers=h,json={'strategy':'model'}).status_code==409
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(200,json={'data':[{'id':'custom-model'}]})
    original=WebModel.verify
    monkeypatch.setattr(WebModel,'verify',lambda self,transport=None:original(self,httpx.MockTransport(respond)))
    assert c.post(PREFIX+'/services/'+identifier+'/verify',headers=h,json={}).status_code==200
    captured=[]
    def run(job,config):
        captured.append((job['model_binding'],config))
        return {'result':'passed'}  # Offline execution boundary; no actual model or recovery.
    control.runner=run
    assert c.post(PREFIX+'/jobs',headers=h,json={'strategy':'model'}).status_code==200
    wait(c,lambda value:not value['busy'])
    binding,config=captured[0]
    assert binding['service_id']==identifier and binding['revision']==saved['revision']
    assert config.api_base=='https://models.example.com/v1' and config.model_id=='custom-model'
    assert len(requests)==1 and requests[0].method=='GET' and requests[0].url.path=='/v1/models'
    assert SECRET not in c.get(PREFIX+'/status').text


@pytest.mark.parametrize("url", ["http://models.example.com/v1", "https://127.0.0.1/v1", "https://localhost/v1",
    "https://169.254.169.254/v1", "https://[::1]/v1", "https://models.example.com:8443/v1",
    "https://user:pass@models.example.com/v1", "https://models.example.com/v1?key=private",
    "https://models.example.com/v1#private", "https://models.example.com/../v1",
    "https://models.example.com/%2e%2e/v1", "https://models.example.com\\@localhost/v1", "https://foo.internal/v1"])
def test_endpoint_rejects_unsafe_syntax_without_network(url):
    with pytest.raises(ValueError, match="endpoint_invalid"):
        validate_endpoint(url)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fd00::1", "::ffff:127.0.0.1"])
def test_dns_private_mixed_or_rebound_resolution_never_connects(monkeypatch, ip):
    import dashboard_api.model_endpoints as module
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, '', ("8.8.8.8", 443)), (2, 1, 6, '', (ip, 443))])
    backend = PublicBackend()
    monkeypatch.setattr(backend.backend, "connect_tcp", lambda *a, **kw: pytest.fail("private target must not connect"))
    with pytest.raises(httpcore.ConnectError, match="network_rejected"):
        backend.connect_tcp("models.example.com", 443)


def test_public_resolution_pins_actual_connection_and_keeps_tls_server_name_separate(monkeypatch):
    import dashboard_api.model_endpoints as module
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, '', ("8.8.8.8", 443))])
    calls = []
    backend = PublicBackend()
    monkeypatch.setattr(backend.backend, "connect_tcp", lambda host, port, **kw: calls.append((host, port)) or "fixture-stream")
    assert backend.connect_tcp("models.example.com", 443) == "fixture-stream"
    assert calls == [("8.8.8.8", 443)]
    transport = public_transport()
    assert isinstance(transport._pool._network_backend, PublicBackend)
    transport.close()


def test_tun_dns_benchmark_pool_keeps_https_hostname_or_exact_legacy_http_boundary(monkeypatch):
    import dashboard_api.model_endpoints as module
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, '', ("198.18.0.114", 443))])
    backend = PublicBackend()
    monkeypatch.setattr(backend.backend, "connect_tcp", lambda host, port, **kw: (host, port))
    assert backend.connect_tcp("models.example.com", 443) == ("198.18.0.114", 443)
    assert backend.connect_tcp("aigw.dlut.edu.cn", 80) == ("198.18.0.114", 80)
    with pytest.raises(httpcore.ConnectError):
        backend.connect_tcp("models.example.com", 80)


def test_web_provider_context_is_thread_local_and_restored(monkeypatch):
    import dashboard_api.model_endpoints as module
    def complete(self, *a, **kw):
        assert WEB_TRANSPORT.get() is public_transport
        raise RuntimeError("fixture")
    monkeypatch.setattr(module.NexentRCAProvider, "complete", complete)
    provider = WebRCAProvider(NexentConfig(BASE, MODEL, SECRET, enable_real_model=True, allow_dlut_http=True))
    assert WEB_TRANSPORT.get() is None
    with pytest.raises(RuntimeError):
        provider.complete({})
    assert WEB_TRANSPORT.get() is None


def test_pinned_transport_retains_original_tls_and_host_header(monkeypatch):
    import dashboard_api.model_endpoints as module
    lookups, destinations, tls, writes = [], [], [], []
    def resolve(host, port, **kwargs):
        lookups.append(host)
        return [(2, 1, 6, '', ("8.8.8.8", port))]
    monkeypatch.setattr(module.socket, "getaddrinfo", resolve)
    class Stream:
        def __init__(self):
            self.body = b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}'
        def read(self, max_bytes, timeout=None):
            value, self.body = self.body, b''
            return value
        def write(self, buffer, timeout=None):
            writes.append(buffer)
        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls.append(server_hostname)
            return self
        def get_extra_info(self, key):
            return None
        def close(self):
            pass
    transport = public_transport()
    def connect(host, port, **kwargs):
        destinations.append((host, port))
        return Stream()
    monkeypatch.setattr(transport._pool._network_backend.backend, "connect_tcp", connect)
    with httpx.Client(transport=transport, trust_env=False, follow_redirects=False) as c:
        assert c.get("https://models.example.com/v1/models").json() == {}
    assert lookups == ['models.example.com'] and destinations == [('8.8.8.8', 443)]
    assert tls == ['models.example.com']
    assert b'Host: models.example.com' in b''.join(writes)


def test_actual_sdk_uses_selected_public_transport_and_raw_usage_offline(monkeypatch):
    import dashboard_api.model_endpoints as module
    from reops_agent.measurements import measurement_scope
    from test_b_measurements import meter
    pytest.importorskip('nexent.core.models')
    requests = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in [dict(id='fixture', object='chat.completion.chunk', created=1, model='custom-model',
                choices=[dict(index=0, delta=dict(role='assistant', content='{"ok":true}'), finish_reason='stop')]),
                dict(id='fixture', object='chat.completion.chunk', created=1, model='custom-model', choices=[],
                    usage=dict(prompt_tokens=13, completion_tokens=7, total_tokens=20))]:
                yield b'data: ' + json.dumps(chunk).encode() + b'\n\n'
            yield b'data: [DONE]\n\n'
    def handle(request):
        requests.append(request)
        return httpx.Response(200, headers={'content-type':'text/event-stream'}, stream=Stream())
    monkeypatch.setattr(module, 'public_transport', lambda: httpx.MockTransport(handle))
    provider = WebRCAProvider(NexentConfig('https://models.example.com/v1', 'custom-model', SECRET,
        max_output_tokens=512, enable_real_model=True))
    measurement = meter()
    measurement.begin_model(20)
    request = {name: {} for name in ('service_status','metrics','health_check','relevant_logs','rule_based_diagnosis','recovery_evidence')}
    with measurement_scope(measurement):
        assert provider.complete(request, timeout_seconds=20) == '{"ok":true}'
    result = measurement.close()
    assert len(requests) == 1 and str(requests[0].url) == 'https://models.example.com/v1/chat/completions'
    assert json.loads(requests[0].content)['model'] == 'custom-model'
    assert result['usage'] == dict(input_tokens=13, output_tokens=7, source='server_usage')
    assert result['http_successes'] == 1 and WEB_TRANSPORT.get() is None
def test_http_crud_select_and_guards_reuse_original_session_rules(tmp_path, monkeypatch):
    c, control = client(tmp_path)
    h = headers(c)
    added = c.post(PREFIX + "/services", headers=h, json=fields())
    assert added.status_code == 200 and SECRET not in added.text
    item = added.json()
    assert c.put(PREFIX + "/services/" + item["id"], headers=h, json=fields(api_key="", name="Edited")).status_code == 200
    assert c.post(PREFIX + "/services/" + item["id"] + "/select", headers=h, json={}).status_code == 200
    assert c.post(PREFIX + "/jobs", headers=h, json={"strategy": "model"}).status_code == 409
    assert c.post(PREFIX + "/services", headers={**h, "Origin": "https://evil.invalid"}, json=fields()).status_code == 403
    assert c.post(PREFIX + "/services", headers={"Origin": h["Origin"]}, json=fields()).status_code == 403
    calls = []
    monkeypatch.setattr(WebModel, "verify", lambda self, transport=None: calls.append(self.config.model_id) or setattr(self, "verified", True) or self.status())
    assert c.post(PREFIX + "/services/" + item["id"] + "/verify", headers=h, json={}).status_code == 200
    assert calls == ["custom-model"]
    assert SECRET not in c.get(PREFIX + "/status").text


def test_active_job_rejects_all_configuration_mutations_and_keeps_bound_snapshot(tmp_path):
    c, control = client(tmp_path)
    entered = Event()
    release = Event()
    snapshots = []
    def runner(job, config):
        snapshots.append((job["model_binding"], config))
        entered.set()
        release.wait(3)
        return {"result": "rejected"}
    control.runner = runner
    h = headers(c)
    c.post(PREFIX + "/jobs", headers=h, json={"strategy": "model"})
    assert entered.wait(1)
    for suffix, method, body in [("/services", "post", fields()), ("/services/builtin-dlut", "put", fields()),
        ("/services/builtin-dlut/select", "post", {}), ("/services/builtin-dlut/verify", "post", {})]:
        response = getattr(c, method)(PREFIX + suffix, headers=h, json=body)
        assert response.status_code == 409 and response.json()["detail"] == "experiment_busy"
    assert snapshots[0][0]["endpoint"] == BASE and snapshots[0][1].model_id == MODEL
    release.set()
    wait(c, lambda value: not value["busy"])
