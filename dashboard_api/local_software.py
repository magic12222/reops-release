"""仅本机同源的软件目录与基础监控选择；没有进程/容器控制入口。"""
import json
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


def install_catalog_routes(app, control):
    from .workbench_control import COOKIE, HOSTS, ORIGINS, PREFIX
    def guard(request, write=False):
        if (request.client is None or request.client.host not in {"127.0.0.1", "::1"}
                or request.headers.get("host") not in HOSTS
                or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
                or request.headers.get("origin") not in (None, *ORIGINS)):
            raise HTTPException(403, "local_same_origin_required")
        if write:
            if request.headers.get("origin") not in ORIGINS:
                raise HTTPException(403, "local_same_origin_required")
            try:
                control.require_session(request.cookies.get(COOKIE), request.headers.get("x-reops-monitor-token"))
            except ValueError:
                raise HTTPException(403, "monitor_session_invalid") from None
    def response():
        return JSONResponse(control.catalog.read(), headers={"Cache-Control":"no-store", "Pragma":"no-cache",
            "X-Content-Type-Options":"nosniff", "Cross-Origin-Resource-Policy":"same-origin"})

    @app.get(PREFIX + "/catalog")
    def read(request: Request):
        guard(request)
        return response()  # Never starts a scan, a monitor, or an executable here.

    @app.post(PREFIX + "/catalog/watch")
    async def watch(request: Request):
        guard(request, True)
        if request.headers.get("content-type", "").split(";",1)[0].strip().lower() != "application/json":
            raise HTTPException(415, "json_required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1024:
                raise HTTPException(413, "request_too_large")
        def unique(pairs):
            value = dict(pairs)
            if len(value) != len(pairs): raise ValueError()
            return value
        try:
            data = json.loads(raw, object_pairs_hook=unique)
            if (not isinstance(data, dict) or set(data) != {"software_id", "watching"}
                    or not isinstance(data["software_id"], str) or not 1 <= len(data["software_id"]) <= 128
                    or type(data["watching"]) is not bool):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(422, "fixed_basic_monitor_request_required") from None
        try:
            control.catalog.watch(data["software_id"], data["watching"])
        except ValueError:
            raise HTTPException(409, "software_state_changed_or_monitor_limit") from None
        return response()
