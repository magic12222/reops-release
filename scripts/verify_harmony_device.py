"""经已授权USB在真机执行TLS查询；不向设备发送查询令牌或关闭校验。"""
import argparse
from hashlib import sha256
import ipaddress
import json
from pathlib import Path
import re
import shlex
import subprocess

import httpx

from dashboard_api.mobile_access import load_token

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'runtime/harmony-access'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hdc', required=True, help='本机已有hdc可执行文件')
    parser.add_argument('--browser-confirmed', action='store_true', help='仅当持机者确认无证书警告且看到401时使用')
    args = parser.parse_args()
    hdc = Path(args.hdc).resolve()
    if not hdc.is_file():
        parser.error('hdc文件不存在')
    configured = json.loads((OUTPUT / 'access.json').read_text(encoding='utf-8'))
    address = ipaddress.IPv4Address(configured['lan_ip'])
    if not address.is_private or address.is_loopback or address.is_unspecified or address.is_link_local:
        parser.error('需要已配置的明确私网地址')
    def run(*parts):
        result = subprocess.run([str(hdc), *parts], capture_output=True, timeout=15)
        if result.returncode or b'[Fail]' in result.stdout:
            raise ValueError('device_operation_failed')
        return result.stdout + result.stderr
    targets = [row.split()[0] for row in run('list', 'targets', '-v').decode().splitlines()
               if len(row.split()) > 2 and row.split()[1:3] == ['USB', 'Connected']]
    if len(targets) != 1:
        raise ValueError('one_connected_usb_target_required')
    target = targets[0]
    ca = OUTPUT / 'root-ca.crt'
    remote = '/storage/media/100/local/files/Docs/Download/reops-hotspot-ca-' + sha256(ca.read_bytes()).hexdigest()[:12] + '.crt'
    # Absolute source avoids hdc reproducing relative source directories at destination.
    run('-t', target, 'file', 'send', str(ca.resolve()), remote)
    model = run('-t', target, 'shell', 'param', 'get', 'const.product.software.version').decode(errors='replace').strip()
    ping = run('-t', target, 'shell', 'ping', '-c', '1', '-W', '2', str(address))
    checks = {'device_hotspot_ping': b'1 received' in ping}
    instances = set()
    for name in ('overview', 'incidents', 'deployment'):
        request = 'GET /api/v1/mobile/' + name + ' HTTP/1.1\r\nHost: ' + str(address) + ':8443\r\nConnection: close\r\n\r\n'
        # Only a public GET without credentials enters shell arguments.
        command = 'printf %s ' + shlex.quote(request) + ' | openssl s_client -connect ' + str(address) + ':8443'
        command += ' -CAfile ' + shlex.quote(remote) + ' -verify_ip ' + str(address) + ' -verify_return_error -quiet'
        response = run('-t', target, 'shell', command).replace(b'\r', b'').decode(errors='replace')
        assert 'verify return:1' in response and 'HTTP/1.1 401' in response
        assert 'mobile_authentication_required' in response
        instance = re.search(r'x-reops-instance:\s*([^\s]+)', response, re.I)
        assert instance
        instances.add(instance.group(1))
        checks[name + '_device_tls_and_auth_boundary'] = True
    with httpx.Client(trust_env=False, timeout=10) as client:
        result = client.get('http://127.0.0.1:8021/api/v1/mobile/deployment',
            headers={'Authorization': 'Bearer ' + load_token()})
        result.raise_for_status()
        deployment = result.json()
    assert instances == {deployment['instance_id']}
    checks['same_backend_instance'] = True
    record = {'mode': 'physical_mate80_hotspot_tls', 'device_software': model,
        'base_url': configured['api_base_url'], 'checks': checks, 'deployment': deployment,
        'browser_verified_by_user': args.browser_confirmed, 'device_authenticated_app_query_verified': False,
        'new_model_calls': 0, 'recovery_actions': 0, 'ca_public_file_sha256': sha256(ca.read_bytes()).hexdigest()}
    (OUTPUT / 'device-verification.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'checks': checks, 'browser_verified_by_user': args.browser_confirmed}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('设备验证未通过：' + type(error).__name__ + '；未输出凭据或响应正文。')
        raise SystemExit(1) from None
