"""对已经启动的原入口做真实HTTP/TLS核对，不重启服务或调用模型。"""
from hashlib import sha256
import json
from pathlib import Path
import ssl

import httpx

from dashboard_api.mobile_access import load_token
from workbench.b_store import read_feed
from workbench.legacy_knowledge import read_legacy_knowledge

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'runtime/harmony-access'
SAMPLE = 'incident-vikunja-auto-ece1a7a790ba418f8c6fde29e2604790'


def main():
    import argparse
    import ipaddress
    parser = argparse.ArgumentParser(description=__doc__)
    config_path = OUTPUT / 'access.json'
    configured = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    parser.add_argument('--lan-ip', default=configured.get('lan_ip', '172.16.56.203'))
    args = parser.parse_args()
    address = ipaddress.IPv4Address(args.lan_ip)
    if not address.is_private or address.is_unspecified or address.is_loopback or address.is_link_local:
        parser.error('请提供已配置证书的明确私网IPv4地址')
    tls_base = 'https://' + str(address) + ':8443'
    sources = [ROOT / name for name in ('runtime/vikunja-b/state.sqlite3', 'runtime/dashboard-api.sqlite3',
        'runtime/vikunja-web/events.jsonl')]
    sources += [p for p in (ROOT / 'runtime').glob('*memory.jsonl') if p.is_file()]
    before = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in sources}
    feed, legacy = read_feed(sources[0]), read_legacy_knowledge(ROOT)
    expected = {i.id: i for i in [*feed.incidents, *legacy.incidents]}
    credential = load_token()
    headers = {'Authorization': 'Bearer ' + credential}
    checks, deployments = {}, {}
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        for name, base in [('workbench', 'http://127.0.0.1:8021'), ('web_proxy', 'http://127.0.0.1:5174')]:
            snapshot_response = client.get(base + '/api/v1/workbench/snapshot')
            snapshot_response.raise_for_status()
            snapshot = snapshot_response.json()
            r = client.get(base + '/api/v1/mobile/incidents?limit=100', headers=headers)
            r.raise_for_status()
            page = r.json()
            assert set(expected) == {i['id'] for i in snapshot['incidents']} == {i['id'] for i in page['items']}
            assert snapshot_response.headers['X-ReOps-Instance'] == r.headers['X-ReOps-Instance']
            checks[name + '_same_ids'] = len(expected)
            for item in snapshot['incidents']:
                detail = client.get(base + '/api/v1/mobile/incidents/' + item['id'], headers=headers)
                detail.raise_for_status()
                assert detail.json()['incident'] == item
                # Compare to persisted record with UTC normalization (legacy producer may use Z).
                from dashboard_api.mobile import stamp
                original = expected[item['id']].model_dump()
                original['started_at'] = stamp(original['started_at'])
                for event in original['events']:
                    event['timestamp'] = stamp(event['timestamp'])
                assert detail.json()['incident'] == original
            deployments[name] = client.get(base + '/api/v1/mobile/deployment', headers=headers).json()
        assert deployments['workbench'] == deployments['web_proxy']
        health = client.get('http://127.0.0.1:8020/api/v1/health')
        assert health.status_code == 200
        checks['dashboard_health'] = True
        assert client.get('http://127.0.0.1:5174/workbench?source=real').status_code == 200
        checks['web_html'] = True
    context = ssl.create_default_context(cafile=str(OUTPUT / 'root-ca.crt'))
    with httpx.Client(base_url=tls_base, verify=context, timeout=15,
                      trust_env=False, follow_redirects=False) as client:
        for path in ('overview', 'incidents', 'deployment'):
            r = client.get('/api/v1/mobile/' + path)
            assert r.status_code == 401 and r.headers.get('Cache-Control') == 'no-store'
            assert client.get('/api/v1/mobile/' + path, headers={'Authorization': 'Bearer incorrect'}).status_code == 401
        remote = client.get('/api/v1/mobile/deployment', headers=headers)
        remote.raise_for_status()
        assert remote.json() == deployments['workbench']
        for path in ('/api/v1/workbench/snapshot', '/api/v1/health', '/api/v1/runs', '/openapi.json', '/docs'):
            assert client.get(path, headers={**headers, 'X-Forwarded-For': '127.0.0.1'}).status_code == 404
        for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'):
            assert client.request(method, '/api/v1/mobile/overview', headers=headers).status_code == 404
        assert client.get('/api/v1/mobile/incidents?limit=0', headers=headers).status_code == 422
        assert client.get('/api/v1/mobile/incidents/not-a-record', headers=headers).status_code == 404
        detail = client.get('/api/v1/mobile/incidents/' + SAMPLE, headers=headers)
        detail.raise_for_status()
        sample = detail.json()
        assert sample['incident']['verification']['status'] == 'passed'
        assert sample['recovery']['outcome'] == 'verified' and sample['run_link_status'] == 'not_imported'
        assert len(sample['diagnosis']['calls']) == 3 and all(c['response'] for c in sample['diagnosis']['calls'])
        checks['tls_certificate_verified'] = True
        checks['authenticated_tls_same_instance_and_records'] = True
        checks['remote_management_and_writes_rejected'] = True
    # A trust failure must remain a failure; no verify=False fallback.
    try:
        with httpx.Client(trust_env=False, timeout=5) as client:
            client.get(tls_base + '/api/v1/mobile/overview')
    except httpx.ConnectError:
        checks['untrusted_certificate_rejected'] = True
    else:
        raise AssertionError('unexpected_global_certificate_trust')
    after = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in sources}
    assert before == after
    result = {'mode': 'real_local_http_and_private_interface_tls', 'checks': checks,
        'deployment': deployments['workbench'], 'source_hashes_unchanged': before,
        'sample': {'incident_id': SAMPLE, 'trace_id': sample['incident']['trace_id'],
            'run_link_status': sample['run_link_status'], 'model_call_ids': [c['id'] for c in sample['diagnosis']['calls']],
            'verification': sample['incident']['verification']},
        'physical_device_verified': False, 'other_computer_verified': False,
        'firewall_change_performed': False}
    (OUTPUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'incident_count': len(expected), 'checks': checks}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('历史HTTP/TLS核对失败：' + type(error).__name__ + '；未输出响应正文或凭据。')
        raise SystemExit(1) from None
