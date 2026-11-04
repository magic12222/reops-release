"""历史查询部署的权限、同源口径与凭据边界；不使用真实业务记录。"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from dashboard_api.history_access import create_history_app
from dashboard_api.mobile_access import provision_token, load_token, credential_target
from dashboard_api.store import Store
from workbench.b_store import BStore

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '/api/v1/mobile'
TOKEN = 'isolated-fixture-credential-' + 'x' * 40


def test_archive_version_ignores_parent_git_and_tracks_source_changes(tmp_path, monkeypatch):
    import dashboard_api.history_access as access
    (tmp_path / '.git').mkdir()
    root = tmp_path / 'extracted'
    (root / 'dashboard_api').mkdir(parents=True)
    source = root / 'dashboard_api/api.py'
    source.write_text('first', encoding='utf-8')
    def forbidden(*args, **kwargs):
        raise AssertionError('archive_must_not_run_git')
    monkeypatch.setattr(access.subprocess, 'run', forbidden)
    first = access.code_version(root)
    assert first['git_commit'] is None
    assert len(first['loaded_code_sha256']) == 64
    source.write_text('second', encoding='utf-8')
    assert access.code_version(root)['loaded_code_sha256'] != first['loaded_code_sha256']


@pytest.mark.parametrize('error', [FileNotFoundError(), subprocess.CalledProcessError(1, 'git')])
def test_version_does_not_require_git_executable_or_valid_head(tmp_path, monkeypatch, error):
    import dashboard_api.history_access as access
    (tmp_path / '.git').mkdir()
    def unavailable(*args, **kwargs):
        raise error
    monkeypatch.setattr(access.subprocess, 'run', unavailable)
    assert access.code_version(tmp_path)['git_commit'] is None


class Vault:
    def __init__(self):
        self.values = {}
    def get(self, key):
        if key not in self.values:
            raise ValueError('not_found')
        return self.values[key]
    def put(self, key, value):
        self.values[key] = value


@pytest.fixture
def app(tmp_path, monkeypatch):
    import dashboard_api.history_access as access
    from workbench.contracts import AgentFeed
    fixture = json.loads((ROOT / 'workbench/example.snapshot.json').read_text(encoding='utf-8'))
    feed = AgentFeed(status='ready', incidents=fixture['incidents'], experiences=fixture['experiences'])
    b_path, dashboard_path = tmp_path / 'b.sqlite3', tmp_path / 'dashboard.sqlite3'
    BStore(b_path)
    Store(dashboard_path)
    monkeypatch.setattr(access, 'read_feed', lambda _: deepcopy(feed))
    monkeypatch.setattr(access, 'code_version', lambda _: {'git_commit': 'fixture', 'loaded_code_sha256': 'a' * 64})
    return create_history_app(b_path=b_path, dashboard_path=dashboard_path, root=tmp_path, token=TOKEN)


def test_local_web_and_mobile_same_records_and_no_monitoring(app):
    client = TestClient(app, base_url='http://127.0.0.1:8021', client=('127.0.0.1', 41000), headers={'Authorization': 'Bearer ' + TOKEN})
    web = client.get('/api/v1/workbench/snapshot')
    page = client.get(PREFIX + '/incidents?limit=100')
    assert web.status_code == page.status_code == 200
    assert web.headers['X-ReOps-Instance'] == page.headers['X-ReOps-Instance']
    assert {i['id'] for i in web.json()['incidents']} == {i['id'] for i in page.json()['items']}
    assert all(t['health'] == 'unknown' and t['monitoring'] == 'not_connected' and t['allowed_actions'] == [] for t in web.json()['targets'])
    overview = client.get(PREFIX + '/overview').json()
    assert overview['a_status'] == 'not_connected' and overview['target_health'] == 'unknown'
    deployment = client.get(PREFIX + '/deployment').json()
    assert deployment['incident_count'] == page.json()['total']
    assert deployment['mode'] == 'persisted_history_read_only'
    assert deployment['archive_policy'] == 'fixed_legacy_memory_files'


def test_usb_tls_listener_does_not_gain_local_web_privileges(app):
    client = TestClient(app, base_url='https://127.0.0.1:8443', client=('127.0.0.1', 41000))
    assert client.get('/api/v1/workbench/snapshot').status_code == 404
    assert client.get('/api/v1/health').status_code == 404
    assert client.get(PREFIX + '/overview').status_code == 401
    assert client.get(PREFIX + '/overview', headers={'Authorization': 'Bearer ' + TOKEN}).status_code == 200


@pytest.mark.parametrize('peer', ['172.16.56.25', 'testclient'])
def test_remote_only_authenticated_mobile_get(app, peer):
    client = TestClient(app, client=(peer, 41000))
    for path in (PREFIX + '/overview', PREFIX + '/incidents', PREFIX + '/deployment'):
        response = client.get(path)
        assert response.status_code == 401
        assert response.headers['Cache-Control'] == 'no-store'
    for path in ('/api/v1/workbench/snapshot', '/api/v1/health', '/openapi.json', '/docs', '/api/v1/runs',
                 '/api/v1/researchloop/control/status', '/api/v1/mobile/incidents/x/extra'):
        assert client.get(path, headers={'X-Forwarded-For': '127.0.0.1', 'Authorization': 'Bearer ' + TOKEN}).status_code == 404
    for method in ('post', 'put', 'patch', 'delete', 'options', 'head'):
        assert getattr(client, method)(PREFIX + '/overview', headers={'Authorization': 'Bearer ' + TOKEN}).status_code == 404
    assert client.get(PREFIX + '/overview', headers={'Authorization': 'Bearer ' + TOKEN}).status_code == 200
    assert client.get(PREFIX + '/incidents/missing', headers={'Authorization': 'Bearer ' + TOKEN}).status_code == 404


def test_credential_reuse_rotation_and_process_override(monkeypatch, tmp_path):
    monkeypatch.delenv('REOPS_MOBILE_READ_TOKEN', raising=False)
    vault = Vault()
    assert provision_token(credentials=vault, root=tmp_path)
    first = load_token(credentials=vault, root=tmp_path)
    assert len(first) >= 32
    assert not provision_token(credentials=vault, root=tmp_path)
    assert load_token(credentials=vault, root=tmp_path) == first
    assert provision_token(rotate=True, credentials=vault, root=tmp_path)
    assert load_token(credentials=vault, root=tmp_path) != first
    monkeypatch.setenv('REOPS_MOBILE_READ_TOKEN', 'invalid')
    with pytest.raises(ValueError):
        load_token(credentials=vault, root=tmp_path)


def test_existing_project_databases_required(tmp_path):
    with pytest.raises(ValueError, match='existing_project_databases_required'):
        create_history_app(b_path=tmp_path / 'missing', dashboard_path=tmp_path / 'missing2', root=tmp_path, token=TOKEN)
    assert list(tmp_path.iterdir()) == []


def test_optional_live_monitor_uses_fresh_samples_preserves_history_and_boundaries(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import dashboard_api.history_access as access
    from workbench.contracts import AgentFeed, TargetFeed
    fixture = json.loads((ROOT / 'workbench/example.snapshot.json').read_text(encoding='utf-8'))
    feed = AgentFeed(status='ready', incidents=fixture['incidents'], experiences=fixture['experiences'])
    b_path, dashboard_path = tmp_path / 'b.sqlite3', tmp_path / 'dashboard.sqlite3'
    BStore(b_path)
    Store(dashboard_path)
    monkeypatch.setattr(access, 'read_feed', lambda _: deepcopy(feed))
    monkeypatch.setattr(access, 'code_version', lambda _: {'git_commit': 'fixture', 'loaded_code_sha256': 'a' * 64})
    class Monitor:
        failed = False
        observed = datetime.now(timezone.utc)
        def read_targets(self):
            if self.failed:
                raise ValueError('private diagnostic')
            target = {**fixture['targets'][0], 'health': 'healthy', 'monitoring': 'watching',
                      'observed_at': self.observed.isoformat(), 'allowed_actions': ['start_service(web)']}
            return TargetFeed(status='ready', targets=[target])
    monitor = Monitor()
    application = create_history_app(b_path=b_path, dashboard_path=dashboard_path, root=tmp_path,
                                     token=TOKEN, archives=False, monitor=monitor)
    client = TestClient(application, base_url='https://127.0.0.1:8443', client=('127.0.0.1', 41000),
                        headers={'Authorization': 'Bearer ' + TOKEN})
    overview = client.get(PREFIX + '/overview').json()
    assert overview['a_status'] == 'ready' and overview['target_health'] == 'healthy'
    assert overview['total'] == len(feed.incidents)
    deployment = client.get(PREFIX + '/deployment').json()
    assert deployment['monitoring'] == 'watching' and deployment['mode'] == 'live_monitoring_with_persisted_history'
    for path in ('/api/v1/workbench/snapshot', '/api/v1/workbench/control/status', '/docs'):
        assert client.get(path).status_code == 404
    assert client.post(PREFIX + '/overview').status_code == 404
    local = TestClient(application, base_url='http://127.0.0.1:8021', client=('127.0.0.1', 41000))
    targets = local.get('/api/v1/workbench/snapshot').json()['targets']
    ids = [t['id'] for t in targets]
    assert len(ids) == len(set(ids)) and all(t['allowed_actions'] == [] for t in targets)
    monitor.observed -= timedelta(seconds=120)
    assert client.get(PREFIX + '/overview').json()['target_health'] == 'unknown'
    monitor.failed = True
    overview = client.get(PREFIX + '/overview').json()
    assert overview['a_status'] == 'not_connected' and overview['total'] == len(feed.incidents)
    assert overview['target_health'] == 'unknown'
    assert client.get(PREFIX + '/deployment').json()['records_sha256'] == deployment['records_sha256']


def test_private_tls_provisioning_never_writes_private_key(tmp_path):
    pytest.importorskip('cryptography')
    from scripts.configure_mobile_access import provision_tls
    vault = Vault()
    leaf, ca = provision_tls('172.16.56.203', credentials=vault, directory=tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {'server.crt', 'root-ca.crt'}
    assert all(b'PRIVATE KEY' not in p.read_bytes() for p in tmp_path.iterdir())
    original = leaf.read_bytes(), ca.read_bytes()
    provision_tls('172.16.56.203', credentials=vault, directory=tmp_path)
    assert original == (leaf.read_bytes(), ca.read_bytes())
    with pytest.raises(ValueError, match='address_changed'):
        provision_tls('172.16.56.204', credentials=vault, directory=tmp_path)
    provision_tls('172.16.56.204', credentials=vault, directory=tmp_path, renew=True)
    assert ca.read_bytes() == original[1]
    assert leaf.read_bytes() != original[0]
    assert {p.name for p in tmp_path.iterdir()} == {'server.crt', 'root-ca.crt'}
    for bad in ('0.0.0.0', '127.0.0.1', '8.8.8.8', '169.254.1.1'):
        with pytest.raises(ValueError, match='private_lan'):
            provision_tls(bad, credentials=vault, directory=tmp_path)
