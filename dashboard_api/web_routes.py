"""仅本机同源的ResearchLoop网页操作接口；不修改原C4路由。"""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

COOKIE = "reops_researchloop_ui"
PREFIX = "/api/v1/researchloop/control"
ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173",
           "http://127.0.0.1:5174", "http://localhost:5174",
           "http://127.0.0.1:8020", "http://localhost:8020"}
HOSTS = {"127.0.0.1:5173", "localhost:5173", "127.0.0.1:5174", "localhost:5174", "127.0.0.1:8020", "localhost:8020"}


def install_web_routes(app, control):
    router = APIRouter(prefix=PREFIX)
    from .dependency_diagnosis import DependencyDiagnosis
    dependency = DependencyDiagnosis(control)
    app.state.dependency_diagnosis = dependency
    from .live_conversation import LiveConversation
    conversation = LiveConversation(dependency)
    app.state.live_conversation = conversation

    def guard(request, *, write=False):
        if (request.client is None or request.client.host not in {"127.0.0.1", "::1"}
                or request.headers.get("host") not in HOSTS
                or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
                or request.headers.get("origin") not in (None, *ORIGINS)):
            raise HTTPException(403, "local_same_origin_required")
        if write:
            if not control.enabled:
                raise HTTPException(403, "web_operations_disabled")
            if request.headers.get("origin") not in ORIGINS:
                raise HTTPException(403, "local_same_origin_required")
            try:
                control.require_session(request.cookies.get(COOKIE), request.headers.get("x-reops-ui-token"))
            except ValueError:
                raise HTTPException(403, "browser_session_invalid") from None

    async def body(request, fields, optional=()):
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(415, "json_required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 4096:
                raise HTTPException(413, "request_too_large")
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError()
                value[key] = item
            return value
        try:
            value = json.loads(raw, object_pairs_hook=unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if (not isinstance(value, dict) or not set(fields).issubset(value)
                    or set(value) - set(fields) - set(optional)):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            # 不使用包含input字段的自动验证错误，防止原始Key被回显。
            raise HTTPException(422, "invalid_control_request") from None
        return value

    def response(value):
        return JSONResponse(value, headers={"Cache-Control": "no-store", "Pragma": "no-cache",
            "Vary": "Cookie", "X-Content-Type-Options": "nosniff", "Cross-Origin-Resource-Policy": "same-origin"})

    def error(exc):
        allowed = {"experiment_busy", "model_key_invalid_format", "model_key_missing",
            "model_connection_not_verified", "model_authentication_rejected", "model_gateway_rejected",
            "model_gateway_unavailable", "model_not_available", "unsupported_database_strategy",
            "experiment_start_rate_limited", "web_worker_unavailable", "web_job_not_found",
            "web_job_already_finished", "confirmation_expired_or_consumed", "confirmation_text_mismatch",
            "model_endpoint_invalid", "model_service_invalid", "model_service_limit", "model_service_not_found",
            "model_endpoint_requires_key"}
        allowed.add('model_service_revision_conflict')
        allowed.update({'model_storage_unavailable', 'model_storage_invalid', 'model_storage_conflict',
            'model_storage_write_failed', 'model_storage_busy', 'model_storage_restore_failed'})
        reason = str(exc) if str(exc) in allowed else "web_control_rejected"
        return HTTPException(409, reason)

    @router.get("/status")
    def status(request: Request):
        guard(request)
        session_id, csrf = control.session(request.cookies.get(COOKIE))
        result = response({**control.status(session_id), "csrf": csrf})
        result.set_cookie(COOKIE, session_id, httponly=True, samesite="strict", path=PREFIX)
        return result

    @router.put("/model")
    async def configure(request: Request):
        guard(request, write=True)
        value = await body(request, {"api_key"})
        try:
            control.configure(value["api_key"])
        except ValueError as exc:
            raise error(exc) from None
        return response(control.model.status())

    @router.get("/dependency-diagnosis/status")
    def dependency_status(request: Request):
        guard(request)
        return response({"available": True, "profile": "dependency-audit-v1", "advisory_only": True,
                         "store_ready": dependency.path.is_file(), "automatic_conversation": True,
                         "live_conversation": True, "max_live_rounds": 3})

    @router.get("/dependency-diagnosis/knowledge/{identifier}")
    def dependency_knowledge(identifier: str, request: Request):
        guard(request)
        if not 1 <= len(identifier) <= 128:
            raise HTTPException(422, "invalid_control_request")
        try:
            from .knowledge_retrieval import retrieve_experiences
            incident = dependency._incident(identifier, allow_live=True)
            return response(retrieve_experiences(dependency.path, incident))
        except ValueError:
            raise HTTPException(409, "knowledge_source_unavailable") from None

    @router.post("/dependency-diagnosis/live")
    async def start_live_conversation(request: Request):
        guard(request, write=True)
        value = await body(request, {"incident_id"})
        if not isinstance(value["incident_id"], str) or not 1 <= len(value["incident_id"]) <= 128:
            raise HTTPException(422, "invalid_control_request")
        try:
            return response(await asyncio.to_thread(conversation.start, request.cookies[COOKIE], value["incident_id"]))
        except ValueError as exc:
            allowed = {"experiment_busy", "model_connection_not_verified", "dependency_diagnosis_in_progress",
                "dependency_diagnosis_record_unavailable", "live_conversation_requires_active_incident"}
            raise HTTPException(409, str(exc) if str(exc) in allowed else "live_conversation_unavailable") from None

    @router.post("/dependency-diagnosis/analyze")
    async def analyze_dependency(request: Request):
        guard(request, write=True)
        value = await body(request, {"incident_id"})
        if not isinstance(value["incident_id"], str) or not 1 <= len(value["incident_id"]) <= 128:
            raise HTTPException(422, "invalid_control_request")
        try:
            return response(await asyncio.to_thread(dependency.analyze, request.cookies[COOKIE], value["incident_id"]))
        except ValueError as exc:
            allowed = {"experiment_busy", "model_connection_not_verified", "dependency_diagnosis_in_progress",
                "dependency_diagnosis_record_unavailable", "dependency_diagnosis_requires_finished_record"}
            raise HTTPException(409, str(exc) if str(exc) in allowed else "dependency_diagnosis_unavailable") from None

    @router.post("/dependency-diagnosis/prepare")
    async def prepare_dependency(request: Request):
        guard(request, write=True)
        value = await body(request, {"incident_id"})
        if not isinstance(value["incident_id"], str) or len(value["incident_id"]) > 128:
            raise HTTPException(422, "invalid_control_request")
        try:
            return response(await asyncio.to_thread(dependency.prepare, request.cookies[COOKIE], value["incident_id"]))
        except Exception:
            raise HTTPException(409, "dependency_diagnosis_requires_finished_record_and_verified_model") from None

    @router.post("/dependency-diagnosis/approve")
    async def approve_dependency(request: Request):
        guard(request, write=True)
        value = await body(request, {"offer_id", "approved"})
        if value["approved"] is not True or not isinstance(value["offer_id"], str) or len(value["offer_id"]) > 128:
            raise HTTPException(422, "explicit_model_approval_required")
        try:
            return response(await asyncio.to_thread(dependency.approve, request.cookies[COOKIE], value["offer_id"]))
        except Exception:
            raise HTTPException(409, "dependency_diagnosis_stale_or_budget_consumed") from None

    @router.post("/model/verify")
    async def verify(request: Request):
        guard(request, write=True)
        await body(request, set())
        try:
            value = await asyncio.to_thread(control.verify)
        except ValueError as exc:
            raise error(exc) from None
        return response(value)

    @router.post("/jobs")
    async def start(request: Request):
        guard(request, write=True)
        value = await body(request, {"strategy"})
        if type(value["strategy"]) is not str:
            raise HTTPException(422, "invalid_control_request")
        try:
            value = control.start(request.cookies[COOKIE], value["strategy"])
        except ValueError as exc:
            raise error(exc) from None
        return response(value)

    @router.post("/runs")
    async def start_run(request: Request):
        guard(request, write=True)
        value = await body(request, {"strategy"})
        if type(value["strategy"]) is not str:
            raise HTTPException(422, "invalid_control_request")
        try:
            return response(control.start(request.cookies[COOKIE], value["strategy"], single_run=True))
        except ValueError as exc:
            raise error(exc) from None

    @router.post("/runs/{job_id}/approve")
    async def approve_run(job_id: str, request: Request):
        guard(request, write=True)
        value = await body(request, {"confirmation_id", "approved"})
        if type(value["confirmation_id"]) is not str or value["approved"] is not True:
            raise HTTPException(422, "invalid_control_request")
        try:
            control.approve_run(request.cookies[COOKIE], job_id, value["confirmation_id"])
        except ValueError as exc:
            raise error(exc) from None
        return response({"accepted": True})

    async def save_service(request, service_id=None):
        guard(request, write=True)
        value = await body(request, {"name", "provider", "model", "endpoint", "api_key"},
                           {'expected_revision','as_candidate'} if service_id else set())
        if 'as_candidate' in value and type(value['as_candidate']) is not bool:
            raise HTTPException(422,'invalid_control_request')
        if 'expected_revision' in value and (not isinstance(value['expected_revision'], str)
                or not 1 <= len(value['expected_revision']) <= 128):
            raise HTTPException(422,'invalid_control_request')
        try:
            return response(control.save_service(value, service_id))
        except ValueError as exc:
            raise error(exc) from None

    @router.post("/services")
    async def add_service(request: Request):
        return await save_service(request)

    @router.put("/services/{service_id}")
    async def edit_service(service_id: str, request: Request):
        return await save_service(request, service_id)

    @router.post("/services/{service_id}/verify")
    async def verify_service(service_id: str, request: Request):
        guard(request, write=True)
        await body(request, set())
        try:
            return response(await asyncio.to_thread(control.verify, service_id))
        except ValueError as exc:
            raise error(exc) from None

    @router.post("/services/{service_id}/select")
    async def select_service(service_id: str, request: Request):
        guard(request, write=True)
        await body(request, set())
        try:
            return response(control.select_service(service_id))
        except ValueError as exc:
            raise error(exc) from None

    @router.post("/jobs/{job_id}/confirmation")
    async def confirm(job_id: str, request: Request):
        guard(request, write=True)
        value = await body(request, {"confirmation_id", "answer"})
        if not isinstance(value["confirmation_id"], str) or not isinstance(value["answer"], str):
            raise HTTPException(422, "invalid_control_request")
        try:
            control.respond(request.cookies[COOKIE], job_id, value["confirmation_id"], value["answer"])
        except ValueError as exc:
            raise error(exc) from None
        return response({"accepted": True})

    @router.post("/jobs/{job_id}/cancel")
    async def cancel(job_id: str, request: Request):
        guard(request, write=True)
        await body(request, set())
        try:
            control.cancel(request.cookies[COOKIE], job_id)
        except ValueError as exc:
            raise error(exc) from None
        return response({"cancel_requested": True, "cleanup_must_finish": True})

    app.include_router(router)
