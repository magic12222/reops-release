"""使用当前Windows用户已登记的ReOps调试签名构建；不输出签名材料。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from dashboard_api.model_service_store import WindowsCredentials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--studio', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    profile = root / 'harmony/build-profile.json5'
    original = profile.read_bytes()
    value = json.loads(original.decode('utf-8-sig'))
    if value['app'].get('signingConfigs'):
        raise ValueError('source_signing_config_must_be_empty')
    target = 'ReOps/HarmonySigning/' + hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()[:24]
    configs = json.loads(WindowsCredentials().get(target))
    if len(configs) != 1 or configs[0]['name'] != 'default':
        raise ValueError('signing_not_configured')
    for key in ('certpath', 'profile', 'storeFile'):
        if not Path(configs[0]['material'][key]).is_file():
            raise ValueError('signing_file_unavailable')
    value['app']['signingConfigs'] = configs
    for product in value['app']['products']:
        if product['name'] == 'default':
            product['signingConfig'] = 'default'
    temporary = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    try:
        profile.write_bytes(temporary)
        result = subprocess.run(['pwsh', '-NoProfile', '-File', str(root / 'harmony/scripts/build.ps1'),
                                 '-Studio', args.studio], cwd=root)
        return result.returncode
    finally:
        # Never overwrite a concurrent IDE edit. Such a case needs local review.
        if profile.read_bytes() == temporary:
            profile.write_bytes(original)
        else:
            print('构建配置被其他程序修改，请在本机核对；不要暂存签名配置。')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('签名构建未完成；未输出签名材料或原始异常。')
        raise SystemExit(1) from None
