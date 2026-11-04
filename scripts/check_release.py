"""核对源码清单、秘密及隔离离线 API；不启动服务或连接真实目标。"""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import tempfile
from threading import local

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / 'release-manifest.json').read_text(encoding='utf-8'))
    findings = []
    patterns = {
        'api_key': re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b'),
        'github_token': re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b'),
        'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    }
    secret_values = {v for k, v in os.environ.items() if len(v) >= 8 and k.endswith(('_API_KEY', '_TOKEN', '_PASSWORD', '_SECRET'))}
    for name, expected in manifest['files'].items():
        path = ROOT / name
        if not path.resolve().is_relative_to(ROOT) or path.is_symlink():
            findings.append({'file': name, 'rule': 'path_boundary'})
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            findings.append({'file': name, 'rule': 'checksum'})
        if (any(p in {'runtime', 'node_modules', '__pycache__', '.git', 'dev-log', 'docs'} for p in Path(name).parts)
                or name.endswith(('.sqlite3', '.db', '.env', '.pem', '.key', '.p12', '.p7b', '.hap', '.hsp'))
                or name.startswith('integrations/researchloop/') or name == 'handoff.md'):
            findings.append({'file': name, 'rule': 'forbidden_file'})
        if name == 'harmony/build-profile.json5':
            profile = json.loads(data)
            if profile['app']['signingConfigs']:
                findings.append({'file': name, 'rule': 'signing_configuration'})
            product = next(p for p in profile['app']['products'] if p['name'] == 'default')
            if product['buildOption']['arkOptions']['buildProfileFields']['CONTRACT_TEST'] is not False:
                findings.append({'file': name, 'rule': 'production_contract_test'})
        if b'\0' not in data:
            for number, line in enumerate(data.decode('utf-8', errors='replace').splitlines(), 1):
                for rule, pattern in patterns.items():
                    if pattern.search(line):
                        findings.append({'file': name, 'line': number, 'rule': rule})
                if any(secret in line for secret in secret_values):
                    findings.append({'file': name, 'line': number, 'rule': 'environment_secret'})
    print(json.dumps({'manifest_files': len(manifest['files']), 'findings': findings}, ensure_ascii=False))
    if findings:
        return 1
    # 不允许任何被遗漏的测试逻辑连接网络，包括当前作者机器的已有服务。
    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair
    internal = local()
    def denied(*args, **kwargs):
        raise AssertionError('release_check_network_forbidden')
    def guarded_connect(sock, address):
        if getattr(internal, 'socketpair', False):
            return original_connect(sock, address)
        return denied(sock, address)
    def local_socketpair(*args, **kwargs):
        internal.socketpair = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            internal.socketpair = False
    socket.socket.connect = guarded_connect
    socket.socketpair = local_socketpair
    try:
        import httpx
        import asyncio
        from dashboard_api.api import create_app
        from dashboard_api.store import Store
        from dashboard_api.web_control import WebControl
        from dashboard_api.web_model import WebModel
        from scripts.run_workbench_preview import create_app as workbench_app
        from dashboard_api.history_access import create_history_app
        from workbench.b_store import BStore
        import secrets
        (ROOT / 'runtime').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='release-check-', dir=ROOT / 'runtime') as temp:
            db = Path(temp) / 'empty.sqlite3'
            app = create_app(store=Store(db), web_control=WebControl(db, model=WebModel()))
            b_path = Path(temp) / 'b.sqlite3'
            BStore(b_path)
            token = secrets.token_urlsafe(40)
            mobile_app = create_history_app(b_path=b_path, dashboard_path=db, token=token, archives=False)
            async def verify():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8020') as client:
                    response = await client.get('/api/v1/health')
                    assert response.status_code == 200
                    response = await client.get('/api/v1/runs?source=real')
                    assert response.status_code == 200
                    assert response.json().get('items') == []
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=workbench_app()), base_url='http://127.0.0.1:8021') as client:
                    response = await client.get('/api/v1/workbench/snapshot')
                    assert response.status_code == 200
                    assert response.json()['source'] == 'real'
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mobile_app),
                        base_url='https://127.0.0.1:8443') as client:
                    assert (await client.get('/api/v1/mobile/overview')).status_code == 401
                    headers = {'Authorization': 'Bearer ' + token}
                    response = await client.get('/api/v1/mobile/overview', headers=headers)
                    assert response.status_code == 200
                    assert response.json()['total'] == 0
                    assert response.json()['target_health'] == 'unknown'
                    response = await client.get('/api/v1/mobile/deployment', headers=headers)
                    assert response.status_code == 200
                    assert len(response.json()['loaded_code_sha256']) == 64
            asyncio.run(verify())
        print(json.dumps({'offline_api': 'passed', 'real_network_calls': 0, 'model_calls': 0, 'recovery_actions': 0}))
    finally:
        socket.socket.connect = original_connect
        socket.socketpair = original_socketpair
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
