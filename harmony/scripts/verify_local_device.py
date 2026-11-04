"""在ReOps验证演示缓存清理后实际检测失败、自动重建与读回。"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hdc', required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    out = ROOT / 'artifacts' / ('local-device-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    def run(*parts):
        result = subprocess.run([args.hdc, '-t', args.target, *parts], capture_output=True, timeout=25)
        if result.returncode or b'[Fail]' in result.stdout:
            raise ValueError('device_operation_failed')
        return result.stdout
    def walk(node):
        yield node.get('attributes', {})
        for child in node.get('children', []):
            yield from walk(child)
    def layout(label):
        remote = '/data/local/tmp/reops-local-check.json'
        run('shell', 'uitest', 'dumpLayout', '-p', remote, '-b', 'com.reops.mobile')
        raw = run('shell', 'cat', remote)
        nodes = list(walk(json.loads(raw)))
        if not any(n.get('bundleName') == 'com.reops.mobile' for n in nodes):
            raise ValueError('reops_not_foreground')
        if any(n.get('id') == 'readToken' for n in nodes):
            raise ValueError('configuration_page_not_allowed')
        (out / (label + '.json')).write_bytes(raw)
        return nodes
    def click(ident, label):
        nodes = layout(label + '-before')
        node = next(n for n in nodes if n.get('id') == ident and n.get('bounds') != '[0,0][0,0]')
        assert node.get('enabled') == 'true'
        x1, y1, x2, y2 = map(int, re.findall(r'-?\d+', node['bounds']))
        run('shell', 'uitest', 'uiInput', 'click', str((x1+x2)//2), str((y1+y2)//2))
        time.sleep(.8)
        return layout(label + '-after')
    def status(nodes):
        return next(n['text'] for n in nodes if n.get('id') == 'localProbeStatus')
    def picture(label):
        remote = '/data/local/tmp/reops-local-check.jpeg'
        run('shell', 'snapshot_display', '-f', remote)
        run('file', 'recv', remote, str(out / (label + '.jpeg')))
    checks = {}
    nodes = click('tab3', 'open-local-monitor')
    assert any(n.get('id') == 'localMonitorTitle' for n in nodes)
    if any(n.get('id') == 'localPrepare' for n in nodes):
        nodes = click('localPrepare', 'prepare')
    assert status(nodes) in ('正常', '恢复通过')
    checks['initial_actual_read_healthy'] = True
    picture('normal')
    nodes = click('localInjectFault', 'inject-missing')
    assert status(nodes) == '发现故障'
    assert any('测试缓存不存在' in n.get('text', '') for n in nodes)
    checks['deleted_cache_read_failed'] = True
    picture('fault')
    for index in range(8):
        time.sleep(.8)
        nodes = layout('automatic-repair-' + str(index))
        if status(nodes) == '恢复通过':
            break
    assert status(nodes) == '恢复通过'
    assert any('重新读取并逐字比对：通过' in n.get('text', '') for n in nodes)
    checks['rebuild_and_readback_verified'] = True
    checks['automatic_repair_without_manual_action'] = True
    time.sleep(1.2)
    assert status(layout('recovery-persisted')) == '恢复通过'
    picture('recovered')
    # Leave a healthy, freshly checked initial page ready for the user's recording.
    click('tab0', 'leave-local-monitor')
    nodes = click('tab3', 'ready-for-recording')
    assert status(nodes) == '正常'
    picture('ready-for-recording')
    hap = ROOT / 'entry/build/default/outputs/default/entry-default-signed.hap'
    report = {'completed': True, 'timestamp': datetime.now(timezone.utc).isoformat(),
              'hap_sha256': sha256(hap.read_bytes()).hexdigest(), 'checks': checks,
              'scope': 'ReOps_dedicated_phone_cache_only', 'model_calls': 0, 'remote_recovery': False}
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'completed': True, 'checks': checks, 'output': str(out)}, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import traceback
        line = traceback.extract_tb(error.__traceback__)[-1].lineno
        print('本机缓存真机验收未完成：' + type(error).__name__ + '，检查行' + str(line))
        raise SystemExit(1) from None
