"""网页模型出口：HTTPS公共地址，DNS结果绑定到实际连接，禁止重定向/代理。"""
import ipaddress
import re
import socket
from urllib.parse import urlsplit

import httpcore
import httpx

from reops_agent.nexent_provider import NexentRCAProvider, WEB_TRANSPORT

DLUT = "http://aigw.dlut.edu.cn/v1"
TUN_DNS = ipaddress.ip_network("198.18.0.0/15")


def validate_endpoint(value):
    if not isinstance(value, str) or len(value) > 512 or re.search(r"[\s\\%]", value):
        raise ValueError("model_endpoint_invalid")
    value = value.rstrip("/")
    if value == DLUT:
        return value
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.port not in (None, 443)
                or url.username is not None or url.password is not None or url.query or url.fragment
                or not re.fullmatch(r"[a-zA-Z0-9.-]+", url.hostname) or "." not in url.hostname
                or any(part in ("", ".", "..") for part in url.hostname.split("."))
                or url.hostname.endswith((".local", ".localhost", ".internal"))
                or not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", url.path)):
            raise ValueError()
        try:
            ipaddress.ip_address(url.hostname)
        except ValueError:
            pass
        else:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("model_endpoint_invalid") from None
    return value


class PublicBackend:
    def __init__(self):
        self.backend = httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        host = host.decode("ascii") if isinstance(host, bytes) else host
        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            ips = [item[4][0] for item in addresses]
            def permitted(ip):
                address = ipaddress.ip_address(ip)
                # 本机TUN DNS使用benchmark地址池；HTTPS仍校验原域名证书，HTTP仅原大工例外。
                proxy_address = address.version == 4 and address in TUN_DNS and (
                    port == 443 or host == "aigw.dlut.edu.cn" and port == 80)
                return address.is_global or proxy_address
            if not ips or any(not permitted(ip) for ip in ips):
                raise ValueError()
        except Exception:
            raise httpcore.ConnectError("model_endpoint_network_rejected") from None
        # 连接解析得到的IP，TLS仍由httpcore按原URL主机名验证，避免二次DNS解析。
        return self.backend.connect_tcp(ips[0], port, timeout=timeout,
            local_address=local_address, socket_options=socket_options)

    def connect_unix_socket(self, *args, **kwargs):
        raise httpcore.ConnectError("model_endpoint_network_rejected")

    def sleep(self, seconds):
        return self.backend.sleep(seconds)


def public_transport():
    transport = httpx.HTTPTransport(retries=0, trust_env=False)
    transport._pool._network_backend = PublicBackend()
    return transport


class WebRCAProvider(NexentRCAProvider):
    def complete(self, *args, **kwargs):
        validate_endpoint(self.config.api_base)
        token = WEB_TRANSPORT.set(public_transport)
        try:
            return super().complete(*args, **kwargs)
        finally:
            WEB_TRANSPORT.reset(token)
