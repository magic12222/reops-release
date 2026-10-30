"""配置重启恢复、安全存储与事务失败回归；供应商/模型请求均为替身。"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from dashboard_api.model_service_store import ModelServiceStore, WindowsCredentials
from dashboard_api.model_registry import ModelRegistry
from dashboard_api.web_model import WebModel
from test_model_registry import fields
from test_web_control import model, SECRET, client, headers, PREFIX
from dashboard_api.web_control import WebControl


class Vault:
    def __init__(self):
        self.values = {}
        self.fail = False
    def put(self, target, key):
        if self.fail:
            raise ValueError('untrusted ' + key)
        self.values[target] = key
    def get(self, target):
        return self.values[target]
    def delete(self, target):
        self.values.pop(target, None)


def setup(tmp_path):
    vault = Vault()
    store = ModelServiceStore(tmp_path / 'services.json', vault)
    return ModelRegistry(model(), store), store, vault


def test_save_select_restart_restores_qwen_and_all_services_without_verification_or_key_file(tmp_path):
    registry, store, vault = setup(tmp_path)
    saved = registry.save(fields(name='Qwen', model='Qwen3-8B'))
    assert registry.status()['id'] == 'builtin-dlut'
    registry.select(saved['id'])
    before = registry.binding()
    restored = ModelRegistry(WebModel(), ModelServiceStore(store.path, vault))
    assert restored.status()['id'] == saved['id']
    assert restored.status()['model'] == 'Qwen3-8B'
    assert restored.binding() == before
    assert restored.status()['storage_state'] == 'saved'
    assert restored.status()['source'] == 'persisted_local'
    assert all(not item['verified'] for item in restored.status()['services'])
    with pytest.raises(ValueError, match='not_verified'):
        restored.for_run()
    assert SECRET not in json.dumps(restored.status())
    for file in tmp_path.iterdir():
        assert SECRET.encode() not in file.read_bytes()
    assert 'api_key' not in store.path.read_text(encoding='utf-8')


def test_candidate_and_key_reuse_persist_without_replacing_the_active_configuration(tmp_path):
    registry, store, vault = setup(tmp_path)
    active = registry.status()
    saved = registry.save(fields(api_key='', endpoint=active['endpoint']), active['id'], preserve_active=True)
    assert registry.status()['id'] == active['id'] and registry.verified
    restored = ModelRegistry(WebModel(), ModelServiceStore(store.path, vault))
    assert restored.status()['id'] == active['id']
    assert saved['id'] in restored.services
    assert restored.services[saved['id']]['model'].config.api_key == SECRET
    assert restored.services[saved['id']]['model'].verified is False


def test_vault_failure_has_no_success_or_partial_memory_metadata_or_credential_change(tmp_path):
    registry, store, vault = setup(tmp_path)
    before = registry.status()
    vault.fail = True
    with pytest.raises(ValueError, match='^model_storage_write_failed$') as error:
        registry.save(fields())
    assert SECRET not in str(error.value)
    assert registry.status() == before and not store.path.exists()
    assert not vault.values


def test_atomic_file_failure_preserves_previous_config_and_cleans_new_credentials(tmp_path, monkeypatch):
    registry, store, vault = setup(tmp_path)
    saved = registry.save(fields())
    before, raw, keys = registry.status(), store.path.read_bytes(), dict(vault.values)
    def fail(*_):
        raise OSError('untrusted ' + SECRET)
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(ValueError, match='^model_storage_write_failed$'):
        registry.save(fields(name='Changed', api_key='offline-new-key-value'), saved['id'])
    assert registry.status() == before and store.path.read_bytes() == raw
    assert vault.values == keys
    assert not list(tmp_path.glob('.model-services-*.tmp'))


def test_failed_current_selection_does_not_switch_or_invalidate_existing_proof(tmp_path, monkeypatch):
    registry, store, vault = setup(tmp_path)
    saved = registry.save(fields())
    before = registry.status()
    monkeypatch.setattr(os, 'replace', lambda *_: (_ for _ in ()).throw(OSError()))
    with pytest.raises(ValueError, match='write_failed'):
        registry.select(saved['id'])
    assert registry.status() == before and registry.verified
    assert ModelRegistry(WebModel(), ModelServiceStore(store.path, vault)).selected == 'builtin-dlut'


def test_key_rotation_removes_only_the_replaced_owned_credential(tmp_path):
    registry, store, vault = setup(tmp_path)
    saved = registry.save(fields())
    old_keys = set(vault.values)
    registry.save(fields(api_key='offline-replacement-key'), saved['id'])
    assert len(vault.values) == len(old_keys)
    assert len(old_keys - set(vault.values)) == 1
    restored = ModelRegistry(WebModel(), ModelServiceStore(store.path, vault))
    assert restored.services[saved['id']]['model'].config.api_key == 'offline-replacement-key'


def test_two_processes_cannot_overwrite_newer_saved_selection(tmp_path):
    first, store, vault = setup(tmp_path)
    stale = ModelRegistry(WebModel(), ModelServiceStore(store.path, vault))
    saved = first.save(fields())
    with pytest.raises(ValueError, match='storage_conflict'):
        stale.save(fields(name='stale'))
    other = ModelRegistry(WebModel(), ModelServiceStore(store.path, vault))
    first.select(saved['id'])
    with pytest.raises(ValueError, match='storage_conflict'):
        other.select('builtin-dlut')
    assert ModelRegistry(WebModel(), ModelServiceStore(store.path, vault)).selected == saved['id']


@pytest.mark.parametrize('damage', ['json', 'selection', 'credential_ref', 'duplicate', 'missing_key', 'version'])
def test_unreadable_saved_state_never_silently_falls_back_to_legacy_key_or_overwrites_it(tmp_path, damage):
    registry, store, vault = setup(tmp_path)
    registry.save(fields())
    raw = store.path.read_text(encoding='utf-8')
    value = json.loads(raw)
    if damage == 'json':
        raw = '{invalid'
    elif damage == 'selection':
        value['selected'] = 'missing'
    elif damage == 'credential_ref':
        value['services'][0]['credential_ref'] = 'OtherApp/private-entry'
    elif damage == 'duplicate':
        raw = raw[:-1] + ',"selected":"builtin-dlut"}'
    elif damage == 'missing_key':
        vault.values.clear()
    elif damage == 'version':
        value['version'] = True
    if damage not in ('json', 'duplicate'):
        raw = json.dumps(value)
    store.path.write_text(raw, encoding='utf-8')
    restored = ModelRegistry(model(), ModelServiceStore(store.path, vault))
    assert restored.status()['storage_error'] == 'model_storage_restore_failed'
    assert not restored.status()['configured'] and not restored.verified
    with pytest.raises(ValueError, match='restore_failed'):
        restored.save(fields())
    assert store.path.read_text(encoding='utf-8') == raw
    assert SECRET not in json.dumps(restored.status())


def test_http_reports_persistence_failure_without_key_echo_or_false_saved_status(tmp_path):
    vault = Vault()
    control = WebControl(tmp_path/'c.sqlite3', enabled=True, model=model(), model_store=ModelServiceStore(tmp_path/'services.json', vault))
    c, _ = client(tmp_path, control)
    h = headers(c)
    vault.fail = True
    response = c.post(PREFIX+'/services', headers=h, json=fields())
    assert response.status_code == 409 and response.json()['detail'] == 'model_storage_write_failed'
    assert SECRET not in response.text
    assert len(c.get(PREFIX+'/status').json()['model']['services']) == 1


def test_http_restart_keeps_selection_but_requires_fresh_validation_and_session(tmp_path):
    vault = Vault()
    path = tmp_path/'services.json'
    control = WebControl(tmp_path/'c.sqlite3', enabled=True, model=model(), model_store=ModelServiceStore(path, vault))
    c, _ = client(tmp_path, control); h = headers(c)
    saved = c.post(PREFIX+'/services', headers=h, json=fields(model='Qwen3-8B')).json()
    assert c.post(PREFIX+'/services/'+saved['id']+'/select', headers=h, json={}).status_code == 200
    second = WebControl(tmp_path/'c.sqlite3', enabled=True, model=WebModel(), model_store=ModelServiceStore(path, vault))
    restored, _ = client(tmp_path, second)
    status = restored.get(PREFIX+'/status').json()
    assert status['model']['model'] == 'Qwen3-8B' and not status['model']['verified']
    assert restored.post(PREFIX+'/services/'+saved['id']+'/select', headers=h, json={}).status_code == 403
    assert restored.post(PREFIX+'/jobs', headers=headers(restored), json={'strategy':'model'}).status_code == 409


@pytest.mark.skipif(os.name != 'nt', reason='Windows production wiring')
def test_production_app_factory_wires_persistence_and_reloads_it_without_legacy_key_reads(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from dashboard_api.api import create_app
    from dashboard_api.store import Store
    import dashboard_api.web_control as web_module
    import dashboard_api.model_service_store as storage_module
    vault = Vault()
    monkeypatch.setenv('REOPS_RESEARCHLOOP_WEB', '1')
    monkeypatch.setattr(web_module, 'existing_config', lambda: None)
    monkeypatch.setattr(storage_module, 'WindowsCredentials', lambda: vault)
    db = Store(tmp_path/'factory.sqlite3')
    app = create_app(store=db)
    c = TestClient(app, base_url='http://127.0.0.1:8020', client=('127.0.0.1', 50000))
    h = headers(c)
    added = c.post(PREFIX+'/services', headers=h, json=fields(model='Qwen3-8B')).json()
    assert c.post(PREFIX+'/services/'+added['id']+'/select', headers=h, json={}).status_code == 200
    restored_app = create_app(store=db)
    second = TestClient(restored_app, base_url='http://127.0.0.1:8020', client=('127.0.0.1', 50000))
    status = second.get(PREFIX+'/status').json()['model']
    assert status['model'] == 'Qwen3-8B' and status['storage'] == 'windows_credential_manager'
    assert not status['verified'] and (tmp_path/'model-services.json').is_file()


@pytest.mark.skipif(os.name != 'nt', reason='Windows Credential Manager only')
def test_native_windows_credential_survives_an_independent_process_without_a_key_file(tmp_path):
    store = ModelServiceStore(tmp_path/'native-services.json')
    registry = ModelRegistry(WebModel(), store)
    try:
        saved = registry.save(fields(model='Qwen3-8B'))
        registry.select(saved['id'])
        script = """import json,sys
from dashboard_api.model_registry import ModelRegistry
from dashboard_api.model_service_store import ModelServiceStore
from dashboard_api.web_model import WebModel
m=ModelRegistry(WebModel(),ModelServiceStore(sys.argv[1]))
s=m.status()
assert s['model']=='Qwen3-8B' and s['configured'] and not s['verified']
assert m.services[m.selected]['model'].config.api_key=='fixture-key-never-returned'
print(json.dumps({'restored':True,'verified':s['verified']}))
"""
        result = subprocess.run([sys.executable, '-c', script, str(store.path)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0
        assert json.loads(result.stdout) == {'restored': True, 'verified': False}
        assert SECRET not in result.stdout + result.stderr
        assert SECRET.encode() not in store.path.read_bytes()
    finally:
        if store.path.exists():
            value = json.loads(store.path.read_text(encoding='utf-8'))
            for item in value['services']:
                if item['credential_ref']:
                    store.credentials.delete(item['credential_ref'])
