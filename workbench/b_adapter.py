"""B 的唯一接入槽。读取诊断/经验存储；不要在 GET 中调用模型或恢复。"""

import os
from pathlib import Path
from threading import Lock

from .contracts import AgentFeed
from .b_store import read_feed

_lock = Lock()
_store = None
_archives = False


def install(store, *, archives=False):
    """Bind the host's existing store; no runtime initialization or monitoring."""
    global _store, _archives
    with _lock:
        if _store is not None and _store is not store:
            raise RuntimeError("b_store_already_installed")
        _store = store
        _archives = archives


def uninstall(store):
    global _store, _archives
    with _lock:
        if _store is store:
            _store = None
            _archives = False


def read_agent() -> AgentFeed:
    with _lock:
        store = _store
        archives = _archives
    if store is not None:
        feed = read_feed(store.path)
        if archives:
            from reops_agent.contracts import PROJECT_ROOT
            from .legacy_knowledge import read_legacy_knowledge
            legacy = read_legacy_knowledge(PROJECT_ROOT)
            return AgentFeed(status=feed.status,incidents=[*feed.incidents,*legacy.incidents],experiences=[*feed.experiences,*legacy.experiences])
        return feed
    configured = os.environ.get("REOPS_B_STATE_DB")
    if not configured:
        return AgentFeed(status="not_connected", incidents=[], experiences=[])
    return read_feed(Path(configured))
