"""工作台监控接线离线验证：真实Docker、HTTP业务与恢复动作均不调用。"""
import json
import pytest
from fastapi.testclient import TestClient
from scripts.run_workbench_preview import create_app
from dashboard_api.workbench_control import MonitorControl, PREFIX
from workbench.a_monitor import TargetMonitor
from workbench import a_adapter
from test_a_workbench import Backend, Probe, wait_sample

ORIGIN = {"Origin":"http://127.0.0.1:5174"}

@pytest.fixture
def wired():
    backend, probe = Backend(), Probe()
    monitor = TargetMonitor(backend, probe, interval=.1)
    control = MonitorControl(monitor,enabled=True)
    app = create_app(control=control)
    with TestClient(app,base_url="http://127.0.0.1:8021",client=("127.0.0.1",50000)) as client:
        yield client,control,monitor,backend,probe
    assert a_adapter.read_targets().status == "not_connected"
    assert monitor._thread is None or not monitor._thread.is_alive()


def headers(client):
    result = client.get(PREFIX+'/status')
    assert result.status_code == 200
    assert 'HttpOnly' in result.headers['set-cookie'] and 'SameSite=strict' in result.headers['set-cookie']
    assert result.headers['cache-control'] == 'no-store'
    return {**ORIGIN,'X-ReOps-Monitor-Token':result.json()['csrf']}


def test_lifecycle_and_real_snapshot_facade_use_one_monitor_without_get_io(wired):
    client,control,monitor,backend,probe = wired
    h = headers(client)
    for _ in range(3):
        assert client.get('/api/v1/workbench/snapshot').json()['a_status'] == 'not_connected'
    assert backend.calls == probe.calls == backend.starts == 0
    assert client.post(PREFIX+'/select',headers=h,json={}).status_code == 200
    snapshot = client.get('/api/v1/workbench/snapshot').json()
    assert snapshot['a_status'] == 'ready' and snapshot['b_status'] == 'not_connected'
    assert snapshot['targets'][0]['monitoring'] == 'paused'
    calls = backend.calls,probe.calls
    assert client.get('/api/v1/workbench/snapshot').status_code == 200
    assert (backend.calls,probe.calls) == calls
    control.last_command = None
    assert client.post(PREFIX+'/start',headers=h,json={}).status_code == 200
    wait_sample(monitor)
    assert client.get('/api/v1/workbench/snapshot').json()['targets'][0]['monitoring'] == 'watching'
    assert client.post(PREFIX+'/pause',headers=h,json={}).status_code == 200
    assert client.get('/api/v1/workbench/snapshot').json()['targets'][0]['monitoring'] == 'paused'
    assert backend.starts == 0


@pytest.mark.parametrize('extra',[{'Origin':'https://evil.invalid'}, {'Origin':'null'},
    {'Host':'evil.invalid:8021'}, {'Sec-Fetch-Site':'same-site'}, {'Sec-Fetch-Site':'cross-site'},
    {'X-ReOps-Monitor-Token':'wrong'}])
def test_control_rejects_cross_origin_and_wrong_session_before_sampling(wired,extra):
    client,_,_,backend,probe = wired
    h = {**headers(client),**extra}
    assert client.post(PREFIX+'/select',headers=h,json={}).status_code == 403
    assert backend.calls == probe.calls == backend.starts == 0


def test_missing_origin_missing_cookie_and_foreign_token_rejected(wired):
    client,_,_,backend,_ = wired
    h = headers(client)
    assert client.post(PREFIX+'/select',headers={'X-ReOps-Monitor-Token':h['X-ReOps-Monitor-Token']},json={}).status_code == 403
    client.cookies.clear()
    assert client.post(PREFIX+'/select',headers=h,json={}).status_code == 403
    headers(client)
    assert client.post(PREFIX+'/select',headers=h,json={}).status_code == 403
    assert backend.calls == backend.starts == 0


@pytest.mark.parametrize('payload',[{'target':'other'}, {'url':'http://private.invalid'}, {'command':'start'}, [], None])
def test_control_has_no_caller_selected_target_or_action(wired,payload):
    client,_,_,backend,_ = wired
    assert client.post(PREFIX+'/select',headers={**headers(client),'Content-Type':'application/json'},content=json.dumps(payload)).status_code == 422
    assert backend.calls == backend.starts == 0


def test_unsupported_commands_size_type_rate_and_busy_are_bounded(wired):
    client,control,_,backend,_ = wired
    h = headers(client)
    assert client.post(PREFIX+'/recover',headers=h,json={}).status_code == 404
    assert client.post(PREFIX+'/select',headers=h,content='{}').status_code == 415
    assert client.post(PREFIX+'/select',headers={**h,'Content-Type':'application/json'},content=' '*129).status_code == 413
    assert client.post(PREFIX+'/select',headers=h,json={}).status_code == 200
    assert client.post(PREFIX+'/start',headers=h,json={}).json()['detail'] == 'monitor_rate_limited'
    control.operations.acquire()
    try:
        assert client.post(PREFIX+'/pause',headers=h,json={}).json()['detail'] == 'monitor_operation_busy'
    finally:
        control.operations.release()
    assert backend.starts == 0


def test_target_errors_are_redacted_and_get_does_not_retry(wired):
    client,_,_,backend,_ = wired
    backend.failure = True
    result = client.post(PREFIX+'/select',headers=headers(client),json={})
    assert result.status_code == 409 and result.json()['detail'] == 'monitor_target_unavailable'
    assert 'secret-sentinel' not in result.text
    calls = backend.calls
    assert client.get('/api/v1/workbench/snapshot').json()['a_status'] == 'not_connected'
    assert backend.calls == calls


def test_default_service_keeps_monitoring_disabled_without_discovery():
    backend,probe = Backend(),Probe()
    monitor = TargetMonitor(backend,probe)
    control = MonitorControl(monitor)
    with TestClient(create_app(control=control),base_url='http://127.0.0.1:8021',client=('127.0.0.1',1)) as client:
        h = headers(client)
        assert client.get(PREFIX+'/status').json()['enabled'] is False
        assert client.post(PREFIX+'/select',headers=h,json={}).status_code == 403
        assert backend.calls == probe.calls == backend.starts == 0
    monitor.close()
