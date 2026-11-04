"""同一工作台进程提供回环Web查询和受限私网TLS移动查询。"""
import asyncio
import ipaddress
import os
from pathlib import Path
import secrets
import socket
import ssl
import tempfile

import uvicorn

from dashboard_api.history_access import ROOT, create_history_app
from dashboard_api.mobile_access import credential_target, load_token
from dashboard_api.model_service_store import WindowsCredentials
from scripts.configure_mobile_access import DIRECTORY


def tls_context(address):
    from cryptography.hazmat.primitives import serialization
    raw = WindowsCredentials().get(credential_target() + '/TLS/' + address)
    key = serialization.load_pem_private_key(raw.encode(), password=None)
    password = secrets.token_urlsafe(40).encode()
    encrypted = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password))
    # SSLContext accepts a filename. Only an encrypted temporary key is ever written;
    # its random password remains in memory, and the file is removed before listen.
    descriptor, name = tempfile.mkstemp(prefix='tls-encrypted-', suffix='.pem', dir=DIRECTORY)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encrypted)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(DIRECTORY / 'server.crt'), name, password=password)
        return context
    finally:
        Path(name).unlink(missing_ok=True)


def serve(*, lan_ip=None, lan_cidr=None, usb_access=False, live_monitoring=False):
    addresses = [('127.0.0.1', 8021)]
    if lan_ip:
        ip = ipaddress.ip_address(lan_ip)
        if not ip.is_private or ip.is_unspecified or ip.is_loopback or ip.is_link_local:
            raise ValueError('specific_private_lan_address_required')
        network = ipaddress.ip_network(lan_cidr, strict=True)
        if ip not in network or not network.is_private or network.num_addresses > 4096:
            raise ValueError('explicit_private_lan_subnet_maximum_4096_addresses_required')
        addresses.append((str(ip), 8443))
        if usb_access:
            addresses.append(('127.0.0.1', 8443))
    elif lan_cidr:
        raise ValueError('lan_ip_required')
    elif usb_access:
        raise ValueError('usb_access_requires_configured_tls_address')
    # Reserve every socket before serving either. Never kill or reuse unknown listeners.
    listeners = []
    monitor = business = None
    try:
        for host, port in addresses:
            listener = socket.socket()
            listeners.append(listener)
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((host, port))
            listener.listen(128)
            listener.setblocking(False)
        if live_monitoring:
            from scripts.vikunja_baseline import BusinessSession, baseline
            from workbench.vikunja_target import VikunjaMonitor
            business = BusinessSession()
            report = baseline(business)
            if not report['passed']:
                raise ValueError('business_baseline_failed')
            monitor = VikunjaMonitor(business)
            monitor.select()
            monitor.start()
            print('独立任务读写基线通过，持续监控已启动；未构造模型或恢复执行器。', flush=True)
        app = create_history_app(b_path=os.getenv('REOPS_B_STATE_DB', str(ROOT / 'runtime/vikunja-b/state.sqlite3')),
            dashboard_path=os.getenv('REOPS_C_DB_PATH', str(ROOT / 'runtime/dashboard-api.sqlite3')),
            token=load_token(), archives=True, monitor=monitor)
        if lan_ip:
            from fastapi.responses import JSONResponse
            @app.middleware('http')
            async def subnet(request, call_next):
                peer = ipaddress.ip_address(request.client.host)
                if not peer.is_loopback and peer not in network:
                    return JSONResponse({'detail': 'network_not_allowed'}, status_code=403)
                return await call_next(request)
        servers = []
        for index, (host, port) in enumerate(addresses):
            config = uvicorn.Config(app, host=host, port=port, workers=1, proxy_headers=False,
                access_log=False, log_level='warning', lifespan='off')
            config.load()
            if index:
                config.ssl = tls_context(lan_ip)
            servers.append(uvicorn.Server(config))
        async def run():
            tasks = [asyncio.create_task(server.serve(sockets=[listener])) for server, listener in zip(servers, listeners)]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for server in servers:
                    server.should_exit = True
                await asyncio.gather(*tasks)
        print('实时监控与历史查询模式；仅监控，无模型或恢复。' if live_monitoring else
              '历史查询模式：Web本机 http://127.0.0.1:8021；不创建业务数据，不启动监控或恢复。', flush=True)
        if lan_ip:
            print('移动只读入口：https://' + lan_ip + ':8443；仅指定子网、GET与专用Bearer。', flush=True)
        asyncio.run(run())
    finally:
        for listener in listeners:
            listener.close()
        if monitor is not None:
            monitor.close()
        if business is not None:
            business.close()
