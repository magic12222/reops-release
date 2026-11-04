"""移动契约离线测试；所有 fixture 均来自明确标记的仓库样例。"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event as ThreadEvent

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from dashboard_api.mobile import install_mobile_routes
from dashboard_api.models import Run, Event
from dashboard_api.store import Store
from workbench.contracts import Snapshot
from workbench.b_store import BStore, read_feed

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '/api/v1/mobile'


@pytest.fixture
def data():
    return json.loads((ROOT / 'workbench/example.snapshot.json').read_text(encoding='utf-8'))


@pytest.fixture
def make_client(monkeypatch):
    # Fixture credential has no external authority, stays only in this test process.
    value = 'offline-fixture-credential-' + 'x' * 32
    monkeypatch.setenv('REOPS_MOBILE_READ_TOKEN', value)
    def make(data, store=None, reader=None):
        app = FastAPI()
        install_mobile_routes(app, reader or (lambda: Snapshot.model_validate(data)), store)
        return TestClient(app, headers={'Authorization': 'Bearer ' + value})
    return make


def test_pagination_filters_utc_and_source(data, make_client):
    client = make_client(data)
    result = client.get(PREFIX + '/incidents?limit=1').json()
    assert result['total'] == 2 and result['has_more'] is True
    assert result['items'][0]['id'] == 'fixture-incident-02'
    assert result['source'] == 'offline_fixture'
    assert result['items'][0]['started_at'] == '2026-10-27T01:02:00+00:00'
    assert result['items'][0]['severity'] is None
    assert client.get(PREFIX + '/incidents?offset=999').json()['items'] == []
    assert client.get(PREFIX + '/incidents?status=failed').json()['total'] == 0
    assert client.get(PREFIX + '/incidents?target_id=missing').json()['total'] == 0
    result = client.get(PREFIX + '/incidents', params={'since': '2026-10-27T01:01:00Z',
        'until': '2026-10-27T01:02:00Z'}).json()
    assert result['total'] == 1 and result['items'][0]['id'] == 'fixture-incident-01'


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'offset=-1', 'status=bad',
    'severity=critical', 'target_id=', 'since=', 'until=', 'since=bad', 'since=2026-10-27',
    'since=2026-10-28T00:00:00Z&until=2026-10-27T00:00:00Z'])
def test_invalid_parameters(data, make_client, query):
    assert make_client(data).get(PREFIX + '/incidents?' + query).status_code == 422


def test_authentication_before_data_access(data, make_client, monkeypatch):
    def must_not_read():
        raise AssertionError('unauthorized reader called')
    client = make_client(data, reader=must_not_read)
    for value in ('', 'Bearer incorrect', 'Basic x'):
        r = client.get(PREFIX + '/overview', headers={'Authorization': value})
        assert r.status_code == 401 and r.headers['Cache-Control'] == 'no-store'
    monkeypatch.delenv('REOPS_MOBILE_READ_TOKEN')
    assert client.get(PREFIX + '/overview').json()['detail'] == 'mobile_access_not_configured'
    monkeypatch.setenv('REOPS_MOBILE_READ_TOKEN', 'short')
    assert client.get(PREFIX + '/overview').status_code == 503


def test_overview_honest_empty_and_health(data, make_client):
    client = make_client(data)
    value = client.get(PREFIX + '/overview').json()
    assert value['counts_by_status']['recovered'] == 2
    assert value['target_health'] == 'unknown'  # paused is not fresh monitoring
    assert value['recent_events'][0]['incident_id'] == 'fixture-incident-02'
    data['targets'][0]['monitoring'] = 'watching'
    assert client.get(PREFIX + '/overview').json()['target_health'] == 'healthy'
    data['generated_at'] = '2026-11-02T00:00:00Z'
    assert client.get(PREFIX + '/overview').json()['target_health'] == 'unknown'
    data.update(incidents=[], experiences=[], targets=[])
    value = client.get(PREFIX + '/overview').json()
    assert value['total'] == 0 and value['recent_events'] == []
    assert value['latest_incident_update_at'] is None and value['target_health'] == 'unknown'


@pytest.mark.parametrize('health,observed,expected', [
    ('unhealthy', '2026-10-27T01:02:00Z', 'unhealthy'),
    ('healthy', None, 'unknown'),
    ('healthy', '2026-10-27T01:03:00Z', 'unknown'),
    ('unknown', '2026-10-27T01:02:00Z', 'unknown')])
def test_target_freshness(data, make_client, health, observed, expected):
    data['targets'][0].update(health=health, observed_at=observed, monitoring='watching')
    assert make_client(data).get(PREFIX + '/overview').json()['target_health'] == expected


def test_detail_exact_links_reopen_and_other_trace_isolation(data, make_client, tmp_path):
    db = Store(tmp_path / 'dashboard.sqlite3')
    item = data['incidents'][0]
    run = Run('exact', item['id'], item['trace_id'], 'offline_fixture')
    event = Event('run-event', run.id, run.incident_id, run.trace_id, 0, 'observe', run.source,
                  'trace_journal', 'offline fixture')
    db.put_bundle(run, [event])
    db.create_run(replace(run, id='wrong-trace', trace_id='another-trace'))
    db.create_run(replace(run, id='wrong-incident', incident_id='another-incident'))
    db.create_run(replace(run, id='wrong-source', source='real'))
    value = make_client(data, Store(db.path)).get(PREFIX + '/incidents/' + item['id']).json()
    assert value['run_link_status'] == 'matched'
    assert [r['run_id'] for r in value['runs']] == ['exact']
    assert value['runs'][0]['event_ids'] == ['run-event']
    assert value['knowledge'][0]['id'] == 'fixture-exp-01'
    assert value['diagnosis']['status'] == 'succeeded' and value['recovery']['outcome'] == 'verified'
    assert db.list_runs()[1] == 4  # read projection never creates extra runs


def test_missing_run_database_and_incident(data, make_client, tmp_path):
    store = Store(tmp_path / 'read.sqlite3')
    client = make_client(data, store)
    path = PREFIX + '/incidents/' + data['incidents'][0]['id']
    assert client.get(path).json()['run_link_status'] == 'not_imported'
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError('private-path-and-credential')
    store.incident_snapshots = unavailable
    value = client.get(path)
    assert value.status_code == 200 and value.json()['run_link_status'] == 'unavailable'
    assert 'private-path' not in value.text
    assert client.get(PREFIX + '/incidents/missing').status_code == 404


@pytest.mark.parametrize('call_status,response,expected', [('running', None, 'running'),
    ('failed', None, 'failed'), ('unknown', None, 'unavailable'),
    ('succeeded', None, 'unavailable'), ('succeeded', 'real stored response', 'succeeded')])
def test_diagnosis_states_independent_from_recovery(data, make_client, call_status, response, expected):
    item = data['incidents'][0]
    item['model_calls'][0].update(status=call_status, response=response, input_tokens=None, output_tokens=None)
    value = make_client(data).get(PREFIX + '/incidents/' + item['id']).json()
    assert value['diagnosis']['status'] == expected
    assert value['recovery']['outcome'] == 'verified'
    assert value['diagnosis']['calls'][0]['input_tokens'] is None
    assert value['diagnosis']['diagnosed_at'] is None


def test_experience_not_model_and_no_execution_or_verify(data, make_client):
    data['experiences'] = []
    item = data['incidents'][0]
    item.update(model_calls=[], experience_ids=[], status='observing', diagnosis_source='rule', events=[])
    item['verification'] = {'status': 'pending', 'checks': []}
    data['incidents'] = [item]
    value = make_client(data).get(PREFIX + '/incidents/' + item['id']).json()
    assert value['diagnosis']['status'] == 'not_started'
    assert value['diagnosis']['source'] == 'rule'
    assert value['knowledge'] == [] and value['recovery']['execution_events'] == []
    assert value['recovery']['outcome'] == 'pending'


def test_failure_does_not_become_success_by_command_or_experience(data, make_client):
    item = data['incidents'][1]
    item.update(status='failed', verification={'status': 'failed', 'checks': ['business failed']})
    value = make_client(data).get(PREFIX + '/incidents/' + item['id']).json()
    assert value['diagnosis']['status'] == 'not_started'
    assert value['knowledge'] and value['recovery']['execution_events'][0]['status'] == 'succeeded'
    assert value['recovery']['outcome'] == 'failed'


@pytest.mark.parametrize('change', [
    lambda d: d['incidents'][0].update(target_id='orphan'),
    lambda d: d['incidents'][0].update(experience_ids=['missing']),
    lambda d: d['incidents'][0]['events'][0].update(sequence=20),
    lambda d: d['incidents'][0].update(started_at='2026-10-27'),
    lambda d: d.update(b_status='not_connected', incidents=[], experiences=[]),
    lambda d: d['incidents'][0]['verification'].update(status='pending')])
def test_invalid_feed_fails_closed(data, make_client, change):
    change(data)
    response = make_client(data).get(PREFIX + '/overview')
    assert response.status_code == 503 and response.json()['detail'] == 'mobile_data_unavailable'


def test_source_failure_is_redacted_and_post_is_disallowed(data, make_client):
    def broken():
        raise sqlite3.OperationalError('sensitive-path')
    client = make_client(data, reader=broken)
    assert client.get(PREFIX + '/overview').text == '{"detail":"mobile_data_unavailable"}'
    assert client.post(PREFIX + '/overview', json={}).status_code == 405
    assert client.post(PREFIX + '/incidents/x', json={}).status_code == 405


def test_credentials_redacted_and_producer_not_mutated(data, make_client, monkeypatch):
    secret = 'credential-sentinel-only-for-offline-test'
    monkeypatch.setenv('OFFLINE_FIXTURE_API_KEY', secret)
    data['incidents'][0]['model_calls'][0].update(request=json.dumps({'api_key': secret}), response='Bearer ' + secret)
    original = deepcopy(data)
    response = make_client(data).get(PREFIX + '/incidents/' + data['incidents'][0]['id'])
    assert response.status_code == 200 and secret not in response.text
    assert '[REDACTED]' in response.text and data == original


def test_bstore_restart_read_only_and_no_duplicate_reads(data, make_client, tmp_path):
    path = tmp_path / 'b.sqlite3'
    store = BStore(path, source='offline_fixture')
    with store.transaction() as db:
        for item in data['incidents']:
            db.execute('INSERT INTO incidents VALUES(?,?,?)', (item['id'], json.dumps(item), '{}'))
        for item in data['experiences']:
            db.execute('INSERT INTO experiences VALUES(?,?,?)', (item['id'], json.dumps(item), '{}'))
    original = path.read_bytes()
    def reader():
        feed = read_feed(path, allow_fixture=True)
        return Snapshot.model_validate({**data, 'incidents': feed.incidents, 'experiences': feed.experiences})
    for _ in range(3):
        assert make_client(data, reader=reader).get(PREFIX + '/incidents').json()['total'] == 2
    assert original == path.read_bytes()


def test_openapi_contains_response_models_and_bearer(data, make_client):
    doc = make_client(data).get('/openapi.json').json()
    assert doc['paths'][PREFIX + '/incidents']['get']['security'] == [{'HTTPBearer': []}]
    assert doc['paths'][PREFIX + '/incidents/{incident_id}']['get']['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/Detail')


def test_read_only_store_cannot_create_or_write(tmp_path):
    missing = tmp_path / 'absent.sqlite3'
    store = Store(missing, read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        store.list_runs()
    assert not missing.exists()
    writable = Store(tmp_path / 'existing.sqlite3')
    readonly = Store(writable.path, read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        readonly.create_run(Run('x', 'i', 't', 'real'))
    assert readonly.list_runs()[1] == 0


def test_reader_sees_only_committed_bundle(data, tmp_path):
    store = BStore(tmp_path / 'concurrent.sqlite3', source='offline_fixture')
    with store.transaction() as db:
        for item in data['incidents']:
            db.execute('INSERT INTO incidents VALUES(?,?,?)', (item['id'], json.dumps(item), '{}'))
        for item in data['experiences']:
            db.execute('INSERT INTO experiences VALUES(?,?,?)', (item['id'], json.dumps(item), '{}'))
    written, release = ThreadEvent(), ThreadEvent()
    def update():
        with store.transaction() as db:
            for item in data['incidents']:
                db.execute('UPDATE incidents SET body=? WHERE id=?', (json.dumps({**item, 'summary': 'new-committed'}), item['id']))
            written.set()
            assert release.wait(5)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(update)
        try:
            assert written.wait(5)
            assert all(i.summary != 'new-committed' for i in read_feed(store.path, allow_fixture=True).incidents)
        finally:
            release.set()
        future.result()
    assert all(i.summary == 'new-committed' for i in read_feed(store.path, allow_fixture=True).incidents)


def test_c_http_check_uses_get_only(data, make_client):
    from scripts.check_harmony_api import check
    value = check(make_client(data))
    assert value['detail']['incident']['id'] == 'fixture-incident-02'
    assert value['cross_device_verified'] is False


def test_real_app_queries_persisted_incidents_without_live_monitor(data, monkeypatch, tmp_path):
    from dashboard_api.api import create_app
    from workbench import a_adapter, b_adapter
    from workbench.contracts import TargetFeed
    monkeypatch.setenv('REOPS_MOBILE_READ_TOKEN', 'offline-fixture-token-' + 'x' * 32)
    path = tmp_path / 'persisted.sqlite3'
    store = BStore(path)
    with store.transaction() as db:
        for item in data['incidents']:
            db.execute('INSERT INTO incidents VALUES(?,?,?)', (item['id'], json.dumps(item), '{}'))
        for item in data['experiences']:
            db.execute('INSERT INTO experiences VALUES(?,?,?)', (item['id'], json.dumps(item), '{}'))
    monkeypatch.setenv('REOPS_B_STATE_DB', str(path))
    monkeypatch.setattr(a_adapter, 'read_targets', lambda: TargetFeed(status='not_connected', targets=[]))
    monkeypatch.setattr(b_adapter, '_store', None)
    before = path.read_bytes()
    with TestClient(create_app(store=Store(tmp_path / 'dashboard.sqlite3')),
                    headers={'Authorization': 'Bearer ' + 'offline-fixture-token-' + 'x' * 32}) as client:
        overview = client.get(PREFIX + '/overview')
        assert overview.status_code == 200
        assert overview.json()['total'] == 2
        assert overview.json()['a_status'] == 'not_connected'
        assert overview.json()['target_health'] == 'unknown' and overview.json()['targets'] == []
        detail = client.get(PREFIX + '/incidents/' + data['incidents'][0]['id']).json()
        assert 'target_monitoring_unavailable' in detail['gaps']
        # Original Web graph still requires its existing target references.
        assert client.get('/api/v1/workbench/snapshot').status_code == 503
    assert path.read_bytes() == before


def test_mobile_mode_has_no_legacy_query_or_control_and_never_creates_db(data, monkeypatch, tmp_path):
    from dashboard_api.api import create_mobile_read_app
    from workbench import a_adapter, b_adapter
    from workbench.contracts import AgentFeed, TargetFeed
    monkeypatch.setattr(a_adapter, 'read_targets', lambda: TargetFeed(status='not_connected', targets=[]))
    monkeypatch.setattr(b_adapter, 'read_agent', lambda: AgentFeed(status='ready', incidents=data['incidents'], experiences=data['experiences']))
    monkeypatch.setenv('REOPS_MOBILE_READ_TOKEN', 'offline-fixture-token-' + 'x' * 32)
    path = tmp_path / 'missing-dashboard.sqlite3'
    with TestClient(create_mobile_read_app(Store(path, read_only=True)),
                    headers={'Authorization': 'Bearer ' + 'offline-fixture-token-' + 'x' * 32}) as client:
        assert client.get('/api/v1/health').json()['mode'] == 'mobile_read_only'
        assert client.get(PREFIX + '/overview').json()['total'] == 2
        detail = client.get(PREFIX + '/incidents/' + data['incidents'][0]['id']).json()
        assert detail['run_link_status'] == 'unavailable'
        for route in ('/api/v1/runs', '/api/v1/workbench/snapshot', '/api/v1/researchloop/control/status'):
            assert client.get(route).status_code == 404
        for route in ('/api/v1/experiments', '/api/v1/workbench/control/start',
                      '/api/v1/researchloop/control/start', PREFIX + '/incidents/x'):
            assert client.post(route, json={}).status_code in {404, 405}
    assert not path.exists()
    with pytest.raises(ValueError, match='read_only_store'):
        create_mobile_read_app(Store(tmp_path / 'writable.sqlite3'))


@pytest.mark.parametrize('change', [
    lambda d: d['incidents'].append(deepcopy(d['incidents'][0])),
    lambda d: d['incidents'][0]['events'].append(deepcopy(d['incidents'][0]['events'][0])),
    lambda d: d['incidents'][0].update(experience_ids=['absent']),
    lambda d: d['incidents'][0]['model_calls'].append(deepcopy(d['incidents'][0]['model_calls'][0])),
    lambda d: d['experiences'][0].update(target_id='wrong-target'),
    lambda d: d['experiences'][0].update(incident_id='absent-origin'),
    lambda d: d['incidents'][0]['verification'].update(status='pending')])
def test_mobile_business_validation_survives_monitor_decoupling(data, make_client, change):
    from types import SimpleNamespace
    data.update(a_status='not_connected', targets=[])
    change(data)
    response = make_client(data, reader=lambda: SimpleNamespace(model_dump=lambda: data)).get(PREFIX + '/overview')
    assert response.status_code == 503 and response.json()['detail'] == 'mobile_data_unavailable'


@pytest.mark.parametrize('option', ['--researchloop-web', '--workbench-monitoring', '--workbench-agent'])
def test_mobile_startup_rejects_control_options(monkeypatch, option):
    from scripts import run_dashboard
    monkeypatch.setattr('sys.argv', ['run_dashboard', '--mobile-read-only', option])
    def forbidden(*args, **kwargs):
        raise AssertionError('must not load tokens or start incompatible service')
    monkeypatch.setattr(run_dashboard, 'load_local_token', forbidden)
    monkeypatch.setattr(run_dashboard.uvicorn, 'run', forbidden)
    with pytest.raises(SystemExit) as error:
        run_dashboard.main()
    assert error.value.code == 2


def test_mobile_startup_reuses_original_port_without_history_or_control(monkeypatch, tmp_path):
    from scripts import run_dashboard
    state = tmp_path / 'exists.sqlite3'
    state.touch()
    monkeypatch.setattr(run_dashboard, 'ROOT', tmp_path)
    monkeypatch.setenv('REOPS_B_STATE_DB', str(state))
    monkeypatch.setattr('sys.argv', ['run_dashboard', '--mobile-read-only'])
    def forbidden(*args, **kwargs):
        raise AssertionError('read-only startup must not import or load control credentials')
    monkeypatch.setattr(run_dashboard, 'load_local_token', forbidden)
    monkeypatch.setattr(run_dashboard, 'sync_history', forbidden)
    calls = []
    monkeypatch.setattr(run_dashboard.uvicorn, 'run', lambda *args, **kwargs: calls.append((args, kwargs)))
    run_dashboard.main()
    assert calls == [(('dashboard_api.api:create_mobile_read_app',),
                      {'factory': True, 'host': '127.0.0.1', 'port': 8020, 'workers': 1})]
