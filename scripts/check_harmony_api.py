"""C 的只读联调：使用环境中的专用查询凭据，不执行模型、批准或恢复。"""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from workbench.b_privacy import redact


def check(client, *, incident_id=None):
    overview = client.get('/api/v1/mobile/overview')
    overview.raise_for_status()
    page = client.get('/api/v1/mobile/incidents', params={'limit': 5})
    page.raise_for_status()
    result = {'mode': 'readonly_http_check', 'overview': overview.json(), 'page': page.json(),
              'detail': None, 'cross_device_verified': False}
    if incident_id is None and result['page']['items']:
        incident_id = result['page']['items'][0]['id']
    if incident_id:
        detail = client.get('/api/v1/mobile/incidents/' + quote(incident_id, safe=''))
        detail.raise_for_status()
        result['detail'] = detail.json()
        if result['detail']['incident']['id'] != incident_id:
            raise ValueError('incident_correlation_mismatch')
    return redact(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=os.getenv('REOPS_API_BASE_URL', 'http://127.0.0.1:8021'))
    parser.add_argument('--incident-id')
    parser.add_argument('--output', default='runtime/harmony-b/http-check.json')
    parser.add_argument('--ca-file', help='受信私网CA公有证书；保持TLS校验')
    parser.add_argument('--saved-token', action='store_true', help='从当前Windows账户凭据管理器读取专用查询凭据')
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if (url.scheme not in {'https', 'http'} or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in {'', '/'}
            or url.scheme == 'http' and url.hostname not in {'localhost', '127.0.0.1', '::1'}):
        parser.error('Base URL 必须是 HTTPS 服务根地址；HTTP 仅允许本机回环')
    if args.saved_token:
        from dashboard_api.mobile_access import load_token
        credential = load_token()
    else:
        credential = os.getenv('REOPS_MOBILE_READ_TOKEN', '')
    if len(credential) < 32:
        parser.error('请在当前进程安全设置 REOPS_MOBILE_READ_TOKEN（至少32字符），不要放入命令行或文档')
    destination = Path(args.output).resolve()
    root = Path(__file__).resolve().parents[1]
    if not destination.is_relative_to(root / 'runtime'):
        parser.error('输出必须位于本项目 runtime 目录内')
    try:
        import ssl
        verification = ssl.create_default_context(cafile=args.ca_file) if args.ca_file else True
        with httpx.Client(base_url=args.base_url, follow_redirects=False, timeout=15, trust_env=False,
                          verify=verification, headers={'Authorization': 'Bearer ' + credential}) as client:
            result = check(client, incident_id=args.incident_id)
    except Exception:
        print('只读联调失败：检查入口、鉴权和数据源；未输出响应原文或凭据。')
        return 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('只读 API 查询通过；双端和真机验收仍需 C 核对。输出：' + str(destination))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
