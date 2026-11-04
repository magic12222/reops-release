"""Real simulator + HTTP contract fixtures. Never a real backend acceptance test."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = 'com.reops.mobile'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True)
    parser.add_argument('--section', choices=['all', 'core', 'pagination', 'detail', 'errors', 'race', 'auth'], default='all')
    parser.add_argument('--studio', default=os.environ.get('REOPS_DEVECO_HOME', 'D:/DevTools/Huawei/DevEcoStudio'))
    args = parser.parse_args()
    hdc = Path(args.studio) / 'sdk/default/openharmony/toolchains/hdc.exe'
    out = ROOT / 'artifacts' / time.strftime('contract-device-%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    server_dir = out / 'server'
    server_dir.mkdir()
    mode_file = server_dir / 'mode.txt'
    mode_file.write_text('valid', encoding='utf-8')
    test_token = secrets.token_urlsafe(40)
    bad_token = secrets.token_urlsafe(40)
    credentials = [test_token, bad_token]
    token_file = server_dir / 'ephemeral-read-credential.local.json'
    token_file.write_text(json.dumps({'value': test_token}), encoding='utf-8')
    checks, commands = [], []
    counter = 0
    viewport = [0, 0, 1280, 2832]
    completed = False
    server = None
    mapping = False
    server_log = (out / 'server.log').open('wb')

    def command(*parts):
        r = subprocess.run([str(hdc), '-t', args.target, *parts], capture_output=True, timeout=30)
        stdout = r.stdout.decode('utf-8', errors='replace')
        for value in credentials: stdout = stdout.replace(value, '[test credential omitted]')
        safe_parts = tuple('[test credential omitted]' if part in credentials else part for part in parts)
        commands.append(dict(args=safe_parts, exit_code=r.returncode, stdout=stdout,
                             stderr='[omitted]' if r.stderr else ''))
        assert r.returncode == 0 and '[Fail]' not in stdout, (safe_parts, stdout)
        return stdout

    def walk(tree):
        yield tree.get('attributes', {})
        for c in tree.get('children', []):
            yield from walk(c)

    def layout():
        nonlocal counter
        # dumpLayout can briefly return an empty tree during a frame transition.
        # Retry reads only; never send gestures until the ReOps window is verified.
        for attempt in range(3):
            counter += 1
            remote = '/data/local/tmp/reops-contract-layout.json'
            command('shell', 'uitest', 'dumpLayout', '-p', remote, '-b', BUNDLE)
            dest = out / f'layout-{counter}.json'
            command('file', 'recv', remote, str(dest))
            nodes = list(walk(json.loads(dest.read_text(encoding='utf-8'))))
            root_node = next((n for n in nodes if n.get('bundleName') == BUNDLE and n.get('type') == 'root'), None)
            if root_node is not None:
                viewport[:] = list(map(int, re.findall(r'-?\d+', root_node['bounds'])))
                return nodes
            time.sleep(.4)
        raise RuntimeError('ReOps window unavailable; stopped before sending any more UI input')

    def scroll(down=True, fast=False):
        x1, y1, x2, y2 = viewport
        x = str((x1 + x2) // 2)
        lower, upper = str(round(y1 + (y2-y1)*.77)), str(round(y1 + (y2-y1)*.42))
        command('shell', 'uitest', 'uiInput', 'fling' if fast else 'swipe', x, lower if down else upper, x, upper if down else lower, '10000' if fast else '1600')

    def find(predicate, timeout=8, scrolling=False, fast=False):
        deadline = time.monotonic() + timeout
        while True:
            nodes = layout()
            def in_window(n):
                bounds = list(map(int, re.findall(r'-?\d+', n.get('bounds', ''))))
                if len(bounds) != 4: return False
                x1, y1, x2, y2 = bounds
                return viewport[0] <= (x1+x2)//2 <= viewport[2] and viewport[1] <= (y1+y2)//2 <= viewport[3]
            match = next((n for n in nodes if predicate(n) and n.get('visible') == 'true' and in_window(n)), None)
            if match:
                return match
            if time.monotonic() >= deadline:
                raise AssertionError(f'UI assertion not met; last layout {counter}')
            if scrolling:
                scroll(fast=fast)
            time.sleep(.15)

    def click(node_id):
        n = find(lambda n: n.get('id') == node_id, timeout=70, scrolling=True, fast=node_id == 'loadMore')
        x1, y1, x2, y2 = map(int, re.findall(r'-?\d+', n['bounds']))
        command('shell', 'uitest', 'uiInput', 'click', str((x1+x2)//2), str((y1+y2)//2))

    def text(value, label, timeout=8, scrolling=False):
        find(lambda n: value in n.get('text', ''), timeout, scrolling)
        checks.append(label)
        print(f'PASS {label}', flush=True)

    def capture(label):
        remote = f'/data/local/tmp/reops-contract-{label}.png'
        command('shell', 'uitest', 'screenCap', '-p', remote)
        command('file', 'recv', remote, str(out / f'{label}.png'))

    def mode(value):
        mode_file.write_text(value, encoding='utf-8')

    def refresh():
        click('refreshData')
        click('tab1')

    try:
        assert 'tcp:18882' not in command('fport', 'ls'), 'Existing forwarding task: will not overwrite'
        server = subprocess.Popen([sys.executable, str(ROOT / 'tests/contract_server.py'), '--directory', str(server_dir)],
                                  stdout=server_log, stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        for attempt in range(30):
            assert server.poll() is None, 'Fixture server failed to start (port may be occupied)'
            try:
                request = urllib.request.Request('http://127.0.0.1:18882/api/v1/mobile/overview', headers={'Authorization': 'Bearer ' + test_token})
                with urllib.request.urlopen(request, timeout=1) as response:
                    assert json.load(response)['source'] == 'offline_fixture'
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('Fixture server not ready')
        command('rport', 'tcp:18882', 'tcp:18882')
        mapping = True
        hap = ROOT / 'entry/build/contractTest/outputs/default/entry-default-unsigned.hap'
        profile = ROOT / 'entry/build/contractTest/generated/profile/default/BuildProfile.ets'
        assert 'CONTRACT_TEST = true' in profile.read_text(encoding='utf-8'), 'Build -Product contractTest first'
        assert 'successfully' in command('install', str(hap))
        def restart(token=test_token):
            command('shell', 'aa', 'force-stop', BUNDLE)
            assert 'successfully' in command('shell', 'aa', 'start', '-a', 'EntryAbility', '-b', BUNDLE,
                                             '--ps', 'contractReadToken', token)
        if args.section in ['all', 'core']:
            mode('valid'); restart()
            text('测试环境 / FIXTURE', 'persistent test banner')
            text('当前监控未连接', 'monitor offline is explicit')
            text('未知', 'current health stays unknown')
            capture('overview')
            text('处理中 0 · 已恢复 1', 'persisted historical count', scrolling=True)
            text('TEST ONLY: business verification', 'recent event from mobile overview', scrolling=True)
            click('recent-fixture-verify')
            text('TEST ONLY: PostgreSQL incident', 'Overview event selects matching detail')
            text('fixture-trace-1', 'Incident Trace identity')
            text('fixture-run-distinct', 'Run reference uses distinct ID', scrolling=True)
            capture('detail-run')
            click('tab1'); click('openDiagnosis')
            text('AI Diagnosis', 'diagnosis navigation')
            text('未开始', 'zero calls is not model success', scrolling=True)
            text('TEST ONLY: root cause evidence', 'B diagnosis evidence', scrolling=True)
            capture('diagnosis-root')
            text('TEST ONLY: observation', 'observation remains readable offline', scrolling=True)
            text('TEST ONLY: linked experience', 'explicit knowledge references', scrolling=True)
            text('TEST ONLY: historical root cause', 'historical cause correctly labelled', scrolling=True)
            capture('diagnosis-experience')
            text('没有模型调用记录', 'missing model calls explicit', scrolling=True)
            text('TEST ONLY: recorded execution', 'recorded execution only', scrolling=True)
            text('TEST ONLY: business check passed', 'independent verification', scrolling=True)
            capture('diagnosis-verification')
            click('tab1'); click('backToList'); click('incident-fixture-incident-2')
            text('未导入', 'not_imported Run is not fabricated', scrolling=True)
            click('tab1'); click('openDiagnosis')
            text('根因分析记录不可用', 'unavailable RCA', scrolling=True)
            click('tab1'); click('backToList')
        if args.section in ['all', 'pagination']:
            mode('valid'); restart()
            click('tab1')
            mode('paged'); refresh()
            text('20 / 22', 'mobile pagination first page')
            click('loadMore')
            click('tab1')
            text('22 / 22', 'load more preserves all unique records')
            mode('empty'); refresh()
            text('暂无故障记录', 'empty history distinct from health')
            click('tab2'); text('尚未选择可用故障', 'no fabricated diagnosis on empty history')
        if args.section in ['all', 'detail']:
            mode('valid'); restart()
            click('tab1')
            mode('valid'); refresh(); click('incident-fixture-incident-1')
            mode('wrong-trace'); refresh()
            text('契约不一致', 'cross Trace Run reference rejected')
            mode('valid'); refresh()
            text('TEST ONLY: PostgreSQL incident', 'detail retry recovers')
            mode('detail-404'); refresh()
            text('HTTP 404', 'missing detail is explicit')
            assert not any(n.get('id') == 'incidentDetailTitle' for n in layout())
            checks.append('404 cannot retain old detail as current')
            mode('valid'); refresh(); click('backToList')
        if args.section in ['all', 'errors']:
            mode('valid'); restart()
            click('tab1')
            for value, expected in [('503', 'HTTP 503'), ('bad-json', '有效 JSON'), ('missing', '契约不一致'), ('timeout', '请求超时'), ('redirect', 'HTTP 302')]:
                mode(value); refresh()
                text(expected, f'native HTTP {value}', timeout=14)
                capture(f'error-{value}')
            assert not any(json.loads(line)['path'] == '/never-follow' for line in (server_dir / 'requests.jsonl').read_text().splitlines())
            checks.append('redirect not followed with Bearer')
        if args.section in ['all', 'race']:
            mode('valid'); restart()
            click('tab1')
            mode('slow'); refresh(); text('正在读取', 'loading state')
            mode('empty'); refresh(); text('暂无故障记录', 'newer empty response wins')
            time.sleep(5.3)
            assert not any(n.get('id') == 'incident-fixture-incident-1' for n in layout())
            checks.append('late response cannot restore stale history')
            mode('valid'); refresh(); text('TEST ONLY: PostgreSQL incident', 'successful refresh after errors', scrolling=True)
        if args.section in ['all', 'auth']:
            mode('valid'); restart()
            click('tab1')
            mode('403'); refresh(); text('HTTP 403', '403 permission denial distinct')
            assert not any(n.get('id') == 'refreshData' for n in layout())
            checks.append('403 clears session and protected data')
            mode('valid'); restart(bad_token); click('tab1')
            text('HTTP 401', 'wrong Bearer rejected on native HTTP')
            assert not any('TEST ONLY: PostgreSQL incident' in n.get('text', '') for n in layout())
            checks.append('401 cannot reuse old protected data')
            restart(); click('tab1'); text('TEST ONLY: PostgreSQL incident', 'new valid credential reconnects', scrolling=True)
            click('connectionSettings'); click('disconnectButton'); click('tab1')
            text('尚未配置', 'explicit disconnect clears session')
            restart(); click('tab1'); text('TEST ONLY: PostgreSQL incident', 'test session restored', scrolling=True)
            server.terminate(); server.wait(timeout=10)
            refresh(); text('无法连接服务', 'native network failure distinct')
        records = [json.loads(line) for line in (server_dir / 'requests.jsonl').read_text().splitlines()]
        assert all(row['path'].startswith('/api/v1/mobile/') for row in records)
        if args.section in ['all', 'auth']: assert any(not row['authorized'] for row in records)
        checks.append('only mobile-v1 routes, no legacy fallback')
        completed = True
    finally:
        if mapping:
            try:
                command('fport', 'rm', 'tcp:18882', 'tcp:18882')
            except Exception as error:
                commands.append(dict(cleanup_error=str(error)))
        if server and server.poll() is None:
            server.terminate(); server.wait(timeout=10)
        server_log.close()
        token_file.unlink(missing_ok=True)
        encoded = json.dumps(dict(completed=completed, checks_passed=checks, commands=commands, section=args.section,
            scope='API26 native mobile-v1 + offline_fixture HTTP + ephemeral test Bearer; NOT real deployment'), ensure_ascii=False, indent=2)
        assert all(value not in encoded for value in credentials)
        (out / 'report.json').write_text(encoded, encoding='utf-8')
        print(f'{len(checks)} checks; completed={completed}; report={out / "report.json"}', flush=True)


if __name__ == '__main__':
    main()
