"""Exercise only com.reops.mobile on an explicitly selected HDC device.

Unconfigured production navigation only; does not input credentials or connect to
ReOps. Screenshots/layouts/reports stay in artifacts/.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = 'com.reops.mobile'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True)
    parser.add_argument('--studio', default=os.environ.get('REOPS_DEVECO_HOME', 'D:/DevTools/Huawei/DevEcoStudio'))
    args = parser.parse_args()
    hdc = Path(args.studio) / 'sdk/default/openharmony/toolchains/hdc.exe'
    output = ROOT / 'artifacts' / time.strftime('device-%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=False)
    checks = []
    commands = []
    completed = False

    def command(*parts):
        result = subprocess.run([str(hdc), '-t', args.target, *parts], capture_output=True, timeout=30)
        stdout = result.stdout.decode('utf-8', errors='replace')
        stderr = result.stderr.decode('utf-8', errors='replace')
        commands.append({'args': parts, 'exit_code': result.returncode, 'stdout': stdout, 'stderr': stderr})
        if result.returncode != 0:
            raise RuntimeError(f'HDC failed: {parts}')
        return stdout

    def nodes(tree):
        yield tree.get('attributes', {})
        for child in tree.get('children', []):
            yield from nodes(child)

    def layout(label):
        remote = f'/data/local/tmp/reops-mobile-{label}.json'
        command('shell', 'uitest', 'dumpLayout', '-p', remote, '-b', BUNDLE)
        local = output / f'{label}.json'
        command('file', 'recv', remote, str(local))
        return list(nodes(json.loads(local.read_text(encoding='utf-8'))))

    def find(node_id, label):
        for attempt in range(6):
            found = next((n for n in layout(f'{label}-{attempt}') if n.get('id') == node_id), None)
            if found:
                return found
            time.sleep(0.3)
        raise AssertionError(f'Not found: {node_id}')

    def point(node):
        x1, y1, x2, y2 = map(int, re.findall(r'-?\d+', node['bounds']))
        return str((x1 + x2) // 2), str((y1 + y2) // 2)

    def click(node_id, label):
        command('shell', 'uitest', 'uiInput', 'click', *point(find(node_id, label)))

    def capture(label):
        remote = f'/data/local/tmp/reops-mobile-{label}.png'
        command('shell', 'uitest', 'screenCap', '-p', remote)
        command('file', 'recv', remote, str(output / f'{label}.png'))

    def expect(node_id, label):
        node = find(node_id, label)
        assert node.get('visible') == 'true', node_id
        checks.append(label)

    try:
        command('shell', 'aa', 'force-stop', BUNDLE)
        assert 'successfully' in command('shell', 'aa', 'start', '-a', 'EntryAbility', '-b', BUNDLE)
        expect('overviewTitle', 'overview-unconfigured')
        capture('overview')
        for index, node_id, label in [(1, 'incidentsTitle', 'incidents'), (2, 'diagnosisTitle', 'diagnosis'), (0, 'overviewTitle', 'return-overview')]:
            click(f'tab{index}', f'click-{label}')
            expect(node_id, label)
            capture(label)
        click('tab2', 'diagnosis-again')
        click('chooseIncident', 'choose-incident')
        expect('incidentsTitle', 'choose-incident-navigation')
        click('connectionSettings', 'open-settings')
        expect('settingsTitle', 'connection-settings')
        click('connectButton', 'empty-connect')
        expect('configError', 'empty-config-validation')
        command('shell', 'aa', 'force-stop', BUNDLE)
        command('shell', 'aa', 'start', '-a', 'EntryAbility', '-b', BUNDLE)
        expect('overviewTitle', 'restart-overview')
        assert not any(n.get('id') == 'refreshData' for n in layout('restart-session'))
        checks.append('connection-addresses-not-persisted')
        completed = True
    finally:
        report = {'device': args.target, 'bundle': BUNDLE, 'completed': completed, 'checks_passed': checks, 'commands': commands,
                  'scope_of_configuration': 'unconfigured production; no credentials',
                  'scope': 'API26 unconfigured production UI; no backend/model/recovery calls'}
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'{len(checks)} checks passed; report={output / "report.json"}', flush=True)


if __name__ == '__main__':
    main()
