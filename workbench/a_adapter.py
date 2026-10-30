"""A 的唯一接入槽。读取已存在的监控快照；不要在 GET 中启动采样或执行动作。"""

from .contracts import TargetFeed
import threading

_lock = threading.Lock()
_monitor = None


def install(monitor):
    """Explicit in-process hookup for the owner; no selection, thread or target action."""
    global _monitor
    with _lock:
        if _monitor is not None and _monitor is not monitor:
            raise RuntimeError("a_monitor_already_installed")
        _monitor = monitor


def uninstall(monitor):
    """Owner must close the monitor first in its application lifespan."""
    global _monitor
    with _lock:
        if _monitor is monitor:
            _monitor = None


def read_targets() -> TargetFeed:
    with _lock:
        monitor = _monitor
    return monitor.read_targets() if monitor is not None else TargetFeed(status="not_connected", targets=[])
