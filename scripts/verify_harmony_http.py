"""在原8020端口临时加载只读服务，核对真实HTTP/鉴权/持久数据后关闭本次子进程。"""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import httpx

from dashboard_api.mobile import stamp
from scripts.check_harmony_api import check
from workbench.b_privacy import redact
from workbench.b_store import read_feed

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'runtime/harmony-b/http'
BASE = 'http://127.0.0.1:8020'


def fingerprints(paths):
    return {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    # Do not reuse, terminate or change an unknown server, and do not choose another port.
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 8020)) == 0:
            print('8020已有服务，未启动或停止任何进程；请先核对原服务身份。')
            return 1
    paths = [ROOT / name for name in ('runtime/vikunja-b/state.sqlite3',
             'runtime/dashboard-api.sqlite3', 'runtime/vikunja-web/events.jsonl')]
    if not all(p.is_file() for p in paths):
        print('缺少本机既存数据源，未创建或初始化数据库。')
        return 1
    before = fingerprints(paths)
    feed = read_feed(paths[0])
    if feed.status != 'ready' or not feed.incidents:
        print('没有可核对的既存故障，未伪造样本。')
        return 1
    credential = secrets.token_urlsafe(40)
    env = {k: v for k, v in os.environ.items() if not k.startswith('REOPS_')}
    env.update(REOPS_B_STATE_DB=str(paths[0]), REOPS_C_DB_PATH=str(paths[1]),
               REOPS_MOBILE_READ_TOKEN=credential, PYTHONUTF8='1')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    process = None
    result = None
    try:
        with (OUTPUT / 'service.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, '-m', 'scripts.run_dashboard', '--mobile-read-only'],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            with httpx.Client(base_url=BASE, timeout=10, follow_redirects=False, trust_env=False) as client:
                deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('readonly_service_exited')
                    try:
                        status = client.get('/api/v1/health')
                        if status.status_code == 200 and status.json().get('mode') == 'mobile_read_only':
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError('readonly_service_not_ready')
                    time.sleep(.15)
                schema = client.get('/openapi.json').json()
                expected = {'/api/v1/health', '/api/v1/mobile/overview', '/api/v1/mobile/incidents',
                            '/api/v1/mobile/incidents/{incident_id}'}
                assert set(schema['paths']) == expected
                statuses = {}
                for path in ('/api/v1/mobile/overview', '/api/v1/mobile/incidents',
                             '/api/v1/mobile/incidents/' + feed.incidents[0].id):
                    assert client.get(path).status_code == 401
                assert client.get('/api/v1/mobile/overview', headers={'Authorization': 'Bearer incorrect'}).status_code == 401
                statuses['missing_and_invalid_auth'] = 401
                client.headers['Authorization'] = 'Bearer ' + credential
                result = check(client)
                assert result['overview']['total'] == len(feed.incidents)
                assert result['overview']['a_status'] == 'not_connected'
                assert result['overview']['target_health'] == 'unknown'
                assert sum(result['overview']['counts_by_status'].values()) == len(feed.incidents)
                records = []
                for item in feed.incidents:
                    response = client.get('/api/v1/mobile/incidents/' + item.id)
                    response.raise_for_status()
                    value = response.json()
                    assert value['incident']['id'] == item.id and value['incident']['trace_id'] == item.trace_id
                    assert value['incident']['status'] == item.status
                    assert value['diagnosis']['calls'] == redact([c.model_dump() for c in item.model_calls])
                    assert value['incident']['events'] == [
                        {**redact(e.model_dump()), 'timestamp': stamp(e.timestamp)} for e in item.events]
                    assert {e['id'] for e in value['knowledge']} == set(item.experience_ids)
                    assert value['recovery']['verification'] == item.verification.model_dump()
                    assert response.headers['cache-control'] == 'no-store'
                    records.append({'incident_id': item.id, 'trace_id': item.trace_id,
                                    'status': item.status, 'run_link_status': value['run_link_status']})
                assert client.get('/api/v1/mobile/incidents', params={'offset': 999999}).json()['items'] == []
                assert client.get('/api/v1/mobile/incidents/absent-record').status_code == 404
                for params in ({'limit': 0}, {'limit': 101}, {'offset': -1}, {'status': 'bad'}, {'since': ''}):
                    assert client.get('/api/v1/mobile/incidents', params=params).status_code == 422
                for state in ('recovered', 'failed'):
                    filtered = client.get('/api/v1/mobile/incidents', params={'status': state}).json()
                    assert filtered['total'] == sum(i.status == state for i in feed.incidents)
                for path in ('/api/v1/runs', '/api/v1/workbench/snapshot', '/api/v1/researchloop/control/status'):
                    assert client.get(path).status_code == 404
                # Confirmed allowlist contains no operation routes before sending negative probes.
                for path in ('/api/v1/experiments', '/api/v1/workbench/control/start', '/api/v1/researchloop/control/start'):
                    assert client.post(path, json={}).status_code == 404
                statuses.update(valid_query=200, missing_incident=404, invalid_parameter=422, legacy_route=404,
                                control_post=404)
                result.update(mode='real_loopback_http_readonly', verified_at=datetime.now(timezone.utc).isoformat(),
                    base_url=BASE, statuses=statuses, records_checked=records, model_calls_recorded=sum(len(i.model_calls) for i in feed.incidents),
                    monitored_service_probed=False, new_model_calls=0, recovery_operations=0,
                    external_network_verified=False, harmony_device_verified=False)
                (OUTPUT / 'openapi.json').write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as error:
        print('真实HTTP核对未通过：' + type(error).__name__ + '；未输出响应原文或凭据。')
        return 1
    finally:
        if process is not None and process.poll() is None:
            process.terminate()  # Only the read-only child created above; no pre-existing process is touched.
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    after = fingerprints(paths)
    if before != after:
        print('源数据指纹发生变化，不能认定只读核对完成；未尝试覆盖源数据。')
        return 1
    result.update(original_files_unchanged=True, fingerprints=after, temporary_service_stopped=True)
    (OUTPUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'real_http_verified': True, 'incidents': len(feed.incidents),
        'data_unchanged': True, 'temporary_service_stopped': True, 'output': str(OUTPUT / 'result.json')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
