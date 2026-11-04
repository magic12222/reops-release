"""配置专用查询凭据及私网测试证书；不输出凭据或私钥。"""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path

from dashboard_api.mobile_access import credential_target, provision_token, load_token
from dashboard_api.model_service_store import WindowsCredentials

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'runtime/harmony-access'


def provision_tls(address, *, credentials=None, directory=DIRECTORY, renew=False):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    ip = ipaddress.ip_address(address)
    if not ip.is_private or ip.is_unspecified or ip.is_loopback or ip.is_link_local:
        raise ValueError('specific_private_lan_address_required')
    vault = credentials or WindowsCredentials()
    directory = Path(directory)
    cert_path, ca_path = directory / 'server.crt', directory / 'root-ca.crt'
    target = credential_target() + '/TLS/' + str(ip)
    # Reuse a valid, matching certificate; never silently rotate a trust anchor.
    if (cert_path.exists() or ca_path.exists()) and not renew:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        if ip not in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress):
            raise ValueError('certificate_address_changed_reconfigure_required')
        if cert.not_valid_after_utc <= datetime.now(timezone.utc):
            raise ValueError('certificate_expired_reconfigure_required')
        key = serialization.load_pem_private_key(vault.get(target).encode(), password=None)
        if key.public_key().public_numbers() != cert.public_key().public_numbers():
            raise ValueError('certificate_key_mismatch')
        return cert_path, ca_path
    now = datetime.now(timezone.utc)
    ca_target = credential_target() + '/TLS-CA'
    try:
        saved_ca_key = vault.get(ca_target)
    except ValueError:
        saved_ca_key = None
    if ca_path.is_file() and saved_ca_key:
        ca_key = serialization.load_pem_private_key(saved_ca_key.encode(), password=None)
        ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
        if ca_key.public_key().public_numbers() != ca.public_key().public_numbers() or ca.not_valid_after_utc <= now:
            raise ValueError('certificate_authority_invalid')
        ca_name = ca.subject
    else:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'ReOps local development CA')])
        ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365)).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False), critical=True).sign(ca_key, hashes.SHA256()))
        # Retain the signing key only in the OS vault so DHCP changes can reuse trust.
        vault.put(ca_target, ca_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
        if ca_path.is_file():
            previous = ca_path.read_bytes()
            from hashlib import sha256
            ca_path.with_name('previous-ca-' + sha256(previous).hexdigest()[:12] + '.crt').write_bytes(previous)
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(ip))]))
        .issuer_name(ca_name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip), x509.IPAddress(ipaddress.ip_address('127.0.0.1')),
            x509.DNSName('localhost')]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256()))
    # Both private keys only enter the OS vault; public files contain certificates.
    vault.put(target, leaf_key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    directory.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    return cert_path, ca_path


def copy_token():
    import tkinter as tk
    window = tk.Tk()
    window.title('ReOps 移动查询凭据安全交接')
    window.geometry('520x160')
    tk.Label(window, text='点击后复制专用只读凭据；请仅粘贴到受信设备的凭据输入框。\n不要粘贴到聊天、文档、地址栏或代码。60秒后清理本窗口写入的剪贴板。', wraplength=490).pack(pady=15)
    value = load_token()
    def clear():
        try:
            if window.clipboard_get() == value:
                window.clipboard_clear()
        except tk.TclError:
            pass
    def copy():
        window.clipboard_clear()
        window.clipboard_append(value)
        button.config(text='已复制；请在60秒内完成受信设备配置', state='disabled')
        window.after(60000, clear)
    button = tk.Button(window, text='复制专用查询凭据', command=copy)
    button.pack()
    window.protocol('WM_DELETE_WINDOW', lambda: (clear(), window.destroy()))
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lan-ip')
    parser.add_argument('--rotate-token', action='store_true')
    parser.add_argument('--renew-certificate', action='store_true', help='为当前地址重新签发叶证书；已有签发Key时保持CA不变')
    parser.add_argument('--copy-token', action='store_true')
    args = parser.parse_args()
    if args.copy_token:
        if args.lan_ip or args.rotate_token or args.renew_certificate:
            parser.error('复制与配置请分别执行')
        copy_token()
        return 0
    if args.renew_certificate and not args.lan_ip:
        parser.error('--renew-certificate requires --lan-ip')
    provision_token(rotate=args.rotate_token)
    if args.lan_ip:
        _, ca = provision_tls(args.lan_ip, renew=args.renew_certificate)
        import json
        (DIRECTORY / 'access.json').write_text(json.dumps({'lan_ip': args.lan_ip,
            'api_base_url': 'https://' + args.lan_ip + ':8443'}, indent=2), encoding='utf-8')
        print('测试证书已配置；仅公有根证书可交给手机安装：' + str(ca))
    print('专用查询凭据已保存至当前Windows账户凭据管理器；未输出凭据。')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('配置失败；未输出凭据、私钥或原异常。请检查Windows凭据服务、证书有效期和地址配置。')
        raise SystemExit(1) from None
