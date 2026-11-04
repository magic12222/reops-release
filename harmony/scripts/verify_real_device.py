"""核对已连接的ReOps真机业务页；不配置/传送凭据，不访问控制接口。"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import httpx
from dashboard_api.mobile_access import load_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hdc', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--diagnosis-only', action='store_true', help='已选择样本时继续诊断页，不重复列表检查')
    parser.add_argument('--frontend', action='store_true', help='核对新版概览/详情/模型回复优先布局')
    args = parser.parse_args()
    out = ROOT / 'harmony/artifacts' / ('real-device-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    checks = {}
    def run(*parts):
        r = subprocess.run([args.hdc, '-t', args.target, *parts], capture_output=True, timeout=25)
        if r.returncode or b'[Fail]' in r.stdout:
            raise ValueError('device_operation_failed')
        return r.stdout
    def walk(tree):
        yield tree.get('attributes', {})
        for child in tree.get('children', []):
            yield from walk(child)
    counter = 0
    def layout(label):
        nonlocal counter
        counter += 1
        remote = '/data/local/tmp/reops-business-check.json'
        local = out / f'{counter:03d}-{label}.json'
        run('shell', 'uitest', 'dumpLayout', '-p', remote, '-b', 'com.reops.mobile')
        raw = run('shell', 'cat', remote)
        nodes = list(walk(json.loads(raw)))
        # Never retain a configuration, scanner or foreign-app layout.
        if any(n.get('id') in ('readToken', 'settingsTitle') for n in nodes):
            raise ValueError('configuration_page_not_allowed')
        if not any(n.get('bundleName') == 'com.reops.mobile' for n in nodes):
            raise ValueError('reops_not_foreground')
        if load_token().encode() in raw:
            raise ValueError('credential_in_layout')
        local.write_bytes(raw)
        return nodes
    def texts(nodes):
        return '\n'.join(n.get('text', '') for n in nodes)
    def click(ident, label):
        nodes = layout(label)
        n = next(n for n in nodes if n.get('id') == ident and n.get('visible') == 'true')
        x1, y1, x2, y2 = map(int, re.findall(r'-?\d+', n['bounds']))
        assert 0 <= y1 < y2 <= 2832
        run('shell', 'uitest', 'uiInput', 'click', str((x1+x2)//2), str((y1+y2)//2))
        time.sleep(.5)
        return layout(label + '-after')
    def swipe(label):
        run('shell', 'uitest', 'uiInput', 'swipe', '640', '2200', '640', '700', '500')
        time.sleep(.25)
        return layout(label)
    def top(marker):
        nodes = layout('top-check')
        for k in range(60):
            expected_page = 'incidentsTitle' if marker == 'incidentDetailTitle' else marker
            page_ids = {'overviewTitle', 'incidentsTitle', 'diagnosisTitle', 'localMonitorTitle'}
            if any(n.get('id') in page_ids and n.get('id') != expected_page and
                   n.get('bounds') != '[0,0][0,0]' for n in nodes):
                raise ValueError('active_page_changed_during_verification')
            if any(n.get('id') == marker and n.get('visible') == 'true' and
                   n.get('bounds') != '[0,0][0,0]' for n in nodes):
                return nodes
            run('shell', 'uitest', 'uiInput', 'swipe', '640', '800', '640', '2200', '500')
            time.sleep(.3)
            nodes = layout('top-scroll')
        raise ValueError('page_top_unavailable')
    def screenshot(label):
        layout('before-' + label)
        remote = '/data/local/tmp/reops-business-check.jpeg'
        run('shell', 'snapshot_display', '-f', remote)
        run('file', 'recv', remote, str(out / (label + '.jpeg')))

    with httpx.Client(base_url='http://127.0.0.1:8021', trust_env=False, timeout=15,
                      headers={'Authorization': 'Bearer ' + load_token()}) as client:
        overview = client.get('/api/v1/mobile/overview').json()
        page = client.get('/api/v1/mobile/incidents?limit=100').json()
        sample = page['items'][0]
        detail = client.get('/api/v1/mobile/incidents/' + sample['id']).json()
        deployment = client.get('/api/v1/mobile/deployment').json()
        snapshot = client.get('/api/v1/workbench/snapshot').json()
    assert detail['incident'] == next(i for i in snapshot['incidents'] if i['id'] == sample['id'])
    checks['same_web_snapshot_incident'] = True
    if args.frontend:
        click('tab0', 'frontend-overview')
        nodes = top('overviewTitle')
        expected_health = {'healthy': '健康', 'unhealthy': '异常', 'unknown': '未知'}[overview['target_health']]
        assert next(n['text'] for n in nodes if n.get('id') == 'overviewHealth') == expected_health
        assert str(overview['total']) in [n.get('text') for n in nodes]
        assert '电脑端业务监控' in texts(nodes)
        checks['native_overview_actual_health_and_history_count'] = True
        screenshot('frontend-overview')
        click('tab1', 'frontend-incidents')
        nodes = top('incidentsTitle')
        if any(n.get('id') == 'backToList' and n.get('bounds') != '[0,0][0,0]' for n in nodes):
            click('backToList', 'frontend-close-detail')
            nodes = top('incidentsTitle')
        assert f"20 / {page['total']}" in texts(nodes)
        screenshot('frontend-list')
        click('incident-' + sample['id'], 'frontend-detail')
        nodes = top('incidentDetailTitle')
        assert any(n.get('id') == 'openDiagnosis' for n in nodes)
        assert f"{len(detail['incident']['events'])} 个事件" in texts(nodes)
        assert 'Run：未导入' in texts(nodes)
        screenshot('frontend-detail')
        nodes = click('toggleIncidentSource', 'frontend-source')
        assert sample['id'] in texts(nodes) and sample['trace_id'] in texts(nodes)
        checks['native_exact_source_retained_in_disclosure'] = True
        click('tab2', 'frontend-diagnosis')
        nodes = top('diagnosisTitle')
        assert '历史诊断记录' in texts(nodes) and '执行来源：规则' in texts(nodes)
        first = detail['diagnosis']['calls'][0]
        assert first['model'] in texts(nodes) and first['response'][:60] in texts(nodes)
        checks['native_saved_model_reply_visible_before_long_evidence'] = True
        screenshot('frontend-diagnosis')
        report = {'completed': True, 'scope': 'native_frontend_layout', 'checks': checks,
                  'incident_id': sample['id'], 'trace_id': sample['trace_id'],
                  'deployment': deployment, 'new_model_or_recovery': False}
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'completed': True, 'checks': checks, 'output': str(out)}, ensure_ascii=True))
        return
    if not args.diagnosis_only:
        click('tab0', 'overview')
        nodes = top('overviewTitle')
        assert str(overview['total']) in [n.get('text') for n in nodes]
        assert '当前监控未连接' in texts(nodes) and overview['target_health'] == 'unknown'
        checks['native_overview_total_and_unknown_health'] = overview['total']
        screenshot('overview')
        click('tab1', 'incidents')
        nodes = top('incidentsTitle')
        if any(n.get('id') == 'backToList' for n in nodes):
            click('backToList', 'close-existing-detail')
            nodes = top('incidentsTitle')
        assert f"20 / {page['total']}" in texts(nodes)
        checks['native_first_page_20_of_total'] = True
        nodes = click('incident-' + sample['id'], 'detail')
        nodes = top('incidentDetailTitle')
        assert sample['id'] in texts(nodes) and sample['trace_id'] in texts(nodes)
        checks['native_exact_incident_and_trace'] = True
        screenshot('detail')
    click('tab2', 'diagnosis')
    nodes = top('diagnosisTitle')
    assert sample['id'] in texts(nodes) and sample['trace_id'] in texts(nodes)
    all_text = texts(nodes)
    screenshot('diagnosis-top')
    for k in range(60):
        nodes = swipe('diagnosis-scroll')
        all_text += '\n' + texts(nodes)
        calls_present = all(c['id'] in all_text and c['response'] and c['response'][:60] in all_text
                            for c in detail['diagnosis']['calls'])
        knowledge_present = all(e['id'] in all_text for e in detail['knowledge'])
        if calls_present and knowledge_present and '独立恢复验证' in all_text and all(
                c in all_text for c in detail['recovery']['verification']['checks']):
            break
    for call in detail['diagnosis']['calls']:
        assert call['id'] in all_text and call['model'] in all_text
        assert call['response'] and call['response'][:60] in all_text
    for item in detail['knowledge']:
        assert item['id'] in all_text
    assert '恢复策略来源：规则' in all_text
    assert '独立恢复验证' in all_text and detail['recovery']['verification']['status'] == 'passed'
    for check in detail['recovery']['verification']['checks']:
        assert check in all_text
    checks['native_model_ids_and_reply_prefixes'] = len(detail['diagnosis']['calls'])
    checks['native_exact_experience_references'] = len(detail['knowledge'])
    checks['native_rule_source_and_independent_verification'] = True
    screenshot('diagnosis-verification')
    click('tab0', 'return-overview')
    hap = ROOT / 'harmony/entry/build/default/outputs/default/entry-default-signed.hap'
    report = {'completed': True, 'timestamp': datetime.now(timezone.utc).isoformat(),
              'scope': 'diagnosis_only' if args.diagnosis_only else 'overview_list_and_diagnosis',
              'hap_sha256': sha256(hap.read_bytes()).hexdigest(), 'checks': checks,
              'incident_id': sample['id'], 'trace_id': sample['trace_id'],
              'event_count': len(detail['incident']['events']), 'run_link_status': detail['run_link_status'],
              'deployment': deployment, 'historical_read_only': True, 'new_model_or_recovery': False}
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'completed': True, 'checks': checks, 'output': str(out)}, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import traceback
        frame = traceback.extract_tb(error.__traceback__)[-1]
        print('真机业务验收未完成：' + type(error).__name__ + '，检查行' + str(frame.lineno) + '；未输出凭据或原始异常。')
        raise SystemExit(1) from None
