"""默认 pytest 全量回归禁止真实网络，避免 SDK 缓存或替身遗漏误触服务。"""

import socket
from threading import local
import pytest


@pytest.fixture(autouse=True)
def prohibit_real_network(monkeypatch):
    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair
    internal = local()
    def denied(*args, **kwargs):
        raise AssertionError("离线测试禁止真实网络连接")
    def guarded_connect(sock, address):
        # Windows asyncio 的 socketpair 自唤醒管道需要内部 loopback connect。
        if getattr(internal, "socketpair", False):
            return original_connect(sock, address)
        return denied(sock, address)
    def local_socketpair(*args, **kwargs):
        internal.socketpair = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            internal.socketpair = False
    monkeypatch.setattr(socket, "socketpair", local_socketpair)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
