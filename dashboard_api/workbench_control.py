"""工作台监控控制：仅选择、采样、暂停；不开放故障、模型或恢复动作。"""
import asyncio
from contextlib import asynccontextmanager
import json
import secrets
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from workbench import a_adapter
from workbench.a_monitor import TargetMonitor

PREFIX = "/api/v1/workbench/control"
COOKIE = "reops_workbench_ui"
ORIGINS = {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in (5173, 5174, 8020, 8021)}
HOSTS = {origin.removeprefix("http://") for origin in ORIGINS}


class MonitorControl:
    def __init__(self, monitor=None, *, enabled=False, agent=False, directory=None, discovery=False, catalog=None):
        if agent and not enabled:
            raise ValueError("agent_requires_monitoring")
        self.monitor = monitor or TargetMonitor()
        self.enabled = enabled
        self.agent_enabled = agent
        self.directory = Path(directory) if directory is not None else Path(__file__).resolve().parents[1] / "runtime/workbench-b"
        self.agent_host = None
        self.agent_state = "disabled"
        self.sessions = {}
        self.session_lock = threading.Lock()
        self.operations = threading.Lock()
        self.last_command = None
        from workbench.local_software import LocalSoftwareCatalog
        self.catalog = catalog if catalog is not None else LocalSoftwareCatalog(enabled=enabled and discovery)

    @asynccontextmanager
    async def lifespan(self):
        stop = asyncio.Event()
        worker = None
        try:
            self.catalog.start()
            if self.agent_enabled:
                from workbench.b_service import WorkbenchHost
                self.agent_host = WorkbenchHost(self.directory, monitor=self.monitor)
                # Connecting the webpage remains the only source of target selection.
                await asyncio.to_thread(self.agent_host.start, select=False)
                self.agent_state = "ready"

                def tick():
                    # Serialize with pause/select. This host cannot call a model or tool.
                    with self.monitor.control:
                        self.agent_host.tick()

                async def follow():
                    while not stop.is_set():
                        try:
                            await asyncio.to_thread(tick)
                            self.agent_state = "ready"
                        except Exception:
                            self.agent_state = "error"
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=.2)
                        except asyncio.TimeoutError:
                            pass

                worker = asyncio.create_task(follow())
            elif self.enabled:
                a_adapter.install(self.monitor)
            yield
        finally:
            stop.set()
            await asyncio.to_thread(self.catalog.close)
            if worker is not None:
                await worker
            if self.agent_host is not None:
                await asyncio.to_thread(self.agent_host.close)
                self.agent_host = None
                self.agent_state = "disabled"
            elif self.enabled:
                await asyncio.to_thread(self.monitor.close)
                a_adapter.uninstall(self.monitor)

    def session(self, session_id=None):
        with self.session_lock:
            now = time.monotonic()
            self.sessions = {key: value for key, value in self.sessions.items() if now - value[1] < 7200}
            if session_id not in self.sessions:
                if len(self.sessions) >= 128:
                    raise ValueError("monitor_sessions_full")
                session_id = secrets.token_urlsafe(24)
                self.sessions[session_id] = (secrets.token_urlsafe(32), now)
            token = self.sessions[session_id][0]
            self.sessions[session_id] = (token, now)
            return session_id, token

    def require_session(self, session_id, token):
        with self.session_lock:
            value = self.sessions.get(session_id)
            if (value is None or time.monotonic() - value[1] >= 7200 or not isinstance(token, str)
                    or not token.isascii() or not secrets.compare_digest(value[0], token)):
                raise ValueError("monitor_session_invalid")
            self.sessions[session_id] = (value[0], time.monotonic())

    def status(self):
        return {"enabled": self.enabled, "busy": self.operations.locked(),
                "target_id": getattr(self.monitor, "target_id", "reops-lab-api"), "feed": self.monitor.read_targets().model_dump(mode="json"),
                "operations": ["select", "start", "pause"] if self.enabled else [],
                "agent": {"enabled": self.agent_enabled, "state": self.agent_state,
                          "execution_enabled": False, "model_enabled": False}}

    def command(self, operation):
        if not self.enabled or operation not in {"select", "start", "pause"}:
            raise ValueError("monitor_operations_disabled")
        if not self.operations.acquire(blocking=False):
            raise ValueError("monitor_operation_busy")
        try:
            now = time.monotonic()
            if operation != "pause" and self.last_command is not None and now - self.last_command < 1:
                raise ValueError("monitor_rate_limited")
            self.last_command = now
            # No caller URL, PID, action, or command can enter this dispatcher.
            getattr(self.monitor, operation)()
            return self.status()
        finally:
            self.operations.release()


def install_monitor_routes(app, control):
    def response(value):
        return JSONResponse(value, headers={"Cache-Control": "no-store", "Pragma": "no-cache",
            "Vary": "Cookie", "X-Content-Type-Options": "nosniff", "Cross-Origin-Resource-Policy": "same-origin"})

    def guard(request, *, write=False):
        if (request.client is None or request.client.host not in {"127.0.0.1", "::1"}
                or request.headers.get("host") not in HOSTS
                or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
                or request.headers.get("origin") not in (None, *ORIGINS)):
            raise HTTPException(403, "local_same_origin_required")
        if write:
            if not control.enabled:
                raise HTTPException(403, "monitor_operations_disabled")
            if request.headers.get("origin") not in ORIGINS:
                raise HTTPException(403, "local_same_origin_required")
            try:
                control.require_session(request.cookies.get(COOKIE), request.headers.get("x-reops-monitor-token"))
            except ValueError:
                raise HTTPException(403, "monitor_session_invalid") from None

    @app.get(PREFIX + "/status")
    def status(request: Request):
        guard(request)
        try:
            session, token = control.session(request.cookies.get(COOKIE))
        except ValueError:
            raise HTTPException(429, "monitor_sessions_full") from None
        result = response({**control.status(), "csrf": token})
        result.set_cookie(COOKIE, session, httponly=True, samesite="strict", path=PREFIX)
        return result

    @app.post(PREFIX + "/{operation}")
    async def command(operation: str, request: Request):
        guard(request, write=True)
        if operation not in {"select", "start", "pause"}:
            raise HTTPException(404, "monitor_operation_not_found")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(415, "json_required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 128:
                raise HTTPException(413, "request_too_large")
        try:
            if json.loads(raw) != {}:
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(422, "empty_monitor_request_required") from None
        try:
            value = await asyncio.to_thread(control.command, operation)
        except Exception as exc:
            allowed = {"monitor_operation_busy", "monitor_rate_limited", "monitor_operations_disabled"}
            code = str(exc) if isinstance(exc, ValueError) and str(exc) in allowed else "monitor_target_unavailable"
            raise HTTPException(409, code) from None
        # The operation lock has been released; return the current cache, never sample here.
        return response({**value, "busy": False})

    from .local_software import install_catalog_routes
    install_catalog_routes(app, control)
