"""Vikunja 网页明确点击批准与持续固定规则恢复；无通用执行接口。"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import time
from pathlib import Path
from threading import RLock, Thread
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from reops_agent.contracts import PROJECT_ROOT
from workbench.vikunja_automation import VikunjaAutomation
from workbench.vikunja_authorization import VikunjaBrowserRunGate
from .web_control import BrowserConfirmation
from .workbench_control import COOKIE, HOSTS, ORIGINS, PREFIX, MonitorControl

RECOVERY = PREFIX + "/vikunja"


class VikunjaWebControl:
    def __init__(self, monitor, directory=None, *, runner=None):
        self.monitor = monitor
        self.directory = Path(directory) if directory else PROJECT_ROOT / "runtime/vikunja-web"
        self.automation = VikunjaAutomation(monitor, self.directory)
        self.runner = runner
        self.lock = RLock()
        self.jobs = {}
        self.active = None
        self.closed = False
        self.b_store = None
        self.monitor_offers = {}

    def monitoring_offer(self, owner):
        if not owner or self.closed or self.active or self.automation.active or self.automation.inflight:
            return None
        with self.monitor.control:
            m = self.monitor
            identity = m._identity
            if identity is None or m._closed:
                return None
            binding = (identity.binding(), m._generation, m.business.project_id, m.business.task_id)
            previous = self.monitor_offers.get(owner)
            if previous and previous['binding'] == binding and time.monotonic() < previous['deadline']:
                return previous['id']
            current = m.backend.inspect()
            if current.identity != identity or not current.running or not current.postgres_running:
                return None
            if len(self.monitor_offers) >= 128:
                self.monitor_offers.clear()
            value = {'id':uuid4().hex, 'binding':binding, 'epoch':current.app_started_at,
                     'deadline':time.monotonic()+300}
            self.monitor_offers[owner] = value
            return value['id']

    def start_automatic_monitoring(self, owner, offer_id):
        """One explicit scoped click; original policy grant and action ledger remain authoritative."""
        with self.lock, self.monitor.control:
            m, a = self.monitor, self.automation
            offer = self.monitor_offers.get(owner)
            if (self.closed or self.active or a.active or a.inflight or not offer
                    or offer['id'] != offer_id or time.monotonic() >= offer['deadline']):
                raise ValueError('monitoring_offer_invalid')
            identity = m._identity
            current = m.backend.inspect()
            binding = (identity.binding() if identity else None, m._generation, m.business.project_id, m.business.task_id)
            if binding != offer['binding'] or current.identity != identity or current.app_started_at != offer['epoch']:
                raise ValueError('monitoring_binding_changed')
            self.monitor_offers.pop(owner)  # A failed or uncertain submission is never replayed.
            m.start()
            generation = m._generation
            sample = m.observe('incident-monitoring-readiness', 'trace-monitoring-readiness')
            after = m.backend.inspect()
            if (sample.get('target_health') != 'healthy' or after.identity != identity
                    or after.app_started_at != offer['epoch'] or not after.running or not after.postgres_running
                    or m._generation != generation or (m.business.project_id,m.business.task_id) != binding[2:]
                    or m.backend.sql_probe(identity) is not True):
                raise ValueError('monitoring_readiness_not_confirmed')
            dependency = a.status(owner)['dependency_offer_id']
            if not dependency:
                raise ValueError('monitoring_readiness_not_confirmed')
            from workbench.vikunja_dependency import PLAN
            a.enable(owner, dependency, plan_id=PLAN)

    def status(self, owner):
        with self.lock:
            job = self.jobs.get(self.active)
            if job is None or job["owner"] != owner:
                job = next((v for v in reversed(list(self.jobs.values())) if v["owner"] == owner), None)
            public = None
            if job:
                pending = job["confirmation"].status()
                if pending:
                    pending.pop("challenge", None)
                public = {"id": job["id"], "state": job["state"], "pending": pending,
                          "result": deepcopy(job.get("result"))}
            try:
                monitor_offer = self.monitoring_offer(owner)
            except Exception:
                monitor_offer = None
            return {"automation": self.automation.status(owner), "monitor_offer_id": monitor_offer, "demo": public,
                    "demo_busy": self.active is not None, "available": not self.closed}

    def start_demo(self, owner):
        with self.lock:
            if self.closed or self.active or self.automation.active or self.automation.inflight:
                raise ValueError("demo_requires_observe_mode_and_idle")
            if len(self.jobs) >= 20:
                self.jobs.pop(next(iter(self.jobs)))
            identifier = "demo-vikunja-" + uuid4().hex
            job = {"id": identifier, "owner": owner, "state": "preparing",
                   "confirmation": BrowserConfirmation(), "result": None}
            self.jobs[identifier], self.active = job, identifier

            def run():
                try:
                    from scripts.run_vikunja_acceptance import run_acceptance
                    gate = VikunjaBrowserRunGate(self.directory / "authorizations.sqlite3",
                                                confirm=job["confirmation"])
                    job["state"] = "running"
                    if self.runner is not None:
                        result = self.runner(backend=self.monitor.backend, gate=gate)
                    else:
                        result = run_acceptance(backend=self.monitor.backend, gate=gate, b_store=self.b_store)
                    job["result"] = {key: result.get(key) for key in (
                        "passed", "fault_injection_attempted", "recovery_verified", "cleanup_extra_starts",
                        "model_calls", "b_agent_closed_loop", "evidence_directory", "final_business_healthy")}
                    for key in ("diagnosis_source", "memory_written", "experience_ids", "b_profile"):
                        if key in result:
                            job["result"][key] = deepcopy(result[key])
                except BaseException:
                    job["result"] = {"passed": False, "error": "demo_not_completed_check_evidence"}
                finally:
                    with self.lock:
                        job["state"] = ("cancelled" if job.get("cancel_requested")
                            and job.get("result", {}).get("fault_injection_attempted") is False else "finished")
                        self.active = None

            job["thread"] = Thread(target=run, name="vikunja-web-demo", daemon=True)
            job["thread"].start()
            return identifier

    def approve_demo(self, owner, identifier, confirmation):
        with self.lock:
            job = self.jobs.get(identifier)
            if job is None or job["owner"] != owner or self.active != identifier:
                raise ValueError("demo_owner_or_state_invalid")
            job["confirmation"].approve_run(confirmation)

    def cancel_demo(self, owner, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if job is None or job["owner"] != owner or self.active != identifier:
                raise ValueError("demo_owner_or_state_invalid")
            job["cancel_requested"] = True
            job["confirmation"].cancel()

    def enable(self, owner, offer, *, dependency=False):
        with self.lock:
            if self.closed or self.active:
                raise ValueError("demo_in_progress")
            from workbench.vikunja_dependency import PLAN
            self.automation.enable(owner, offer, plan_id=PLAN if dependency else "database_only")

    def close(self):
        with self.lock:
            self.closed = True
            jobs = list(self.jobs.values())
            for job in jobs:
                job["confirmation"].cancel()
        self.automation.disable("service_closed")
        for job in jobs:
            job["thread"].join(timeout=120)


class VikunjaMonitorControl(MonitorControl):
    def __init__(self, monitor, *, directory=None, runner=None, agent=False, discovery=False):
        b_directory = Path(directory) / "b-agent" if directory else PROJECT_ROOT / "runtime/vikunja-b"
        super().__init__(monitor, enabled=True, agent=agent, directory=b_directory, discovery=discovery)
        self.recovery = VikunjaWebControl(monitor, directory, runner=runner)
        self.records_state = "not_loaded"

    def status(self):
        return {**super().status(), "recovery_available": True, "unified_monitoring": True, "dependency_records": self.records_state}

    @asynccontextmanager
    async def lifespan(self):
        async with super().lifespan():
            from workbench import b_adapter
            from workbench.b_store import BStore
            from workbench.dependency_records import sync_dependency_records
            store = self.agent_host.store if self.agent_host else BStore(self.directory / "state.sqlite3")
            b_adapter.install(store, archives=True)
            def sync_records():
                try:
                    sync_dependency_records(store, self.recovery.directory / "events.jsonl")
                    self.records_state = "ready"
                except Exception:
                    # Projection errors cannot revoke or broaden an existing execution approval.
                    self.records_state = "conflict_or_unavailable"
            await asyncio.to_thread(sync_records)
            self.recovery.automation.on_record = sync_records
            if self.agent_host is not None:
                self.agent_host.suspended = lambda: self.recovery.active is not None or self.recovery.automation.active or self.recovery.automation.inflight
                self.recovery.b_store = self.agent_host.store
            stop = asyncio.Event()
            async def follow():
                while not stop.is_set():
                    try:
                        await asyncio.to_thread(self.recovery.automation.tick)
                    except Exception:
                        await asyncio.to_thread(self.recovery.automation.disable, "worker_error")
                    await asyncio.to_thread(sync_records)
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=.3)
                    except asyncio.TimeoutError:
                        pass
            worker = asyncio.create_task(follow())
            try:
                yield
            finally:
                stop.set()
                await worker
                self.recovery.automation.on_record = None
                await asyncio.to_thread(self.recovery.close)
                if self.agent_host is None:
                    b_adapter.uninstall(store)


def install_vikunja_routes(app, control):
    def response(value):
        return JSONResponse(value, headers={"Cache-Control": "no-store", "Pragma": "no-cache",
            "Vary": "Cookie", "X-Content-Type-Options": "nosniff", "Cross-Origin-Resource-Policy": "same-origin"})

    def guard(request, write=False):
        if (request.client is None or request.client.host not in {"127.0.0.1", "::1"}
                or request.headers.get("host") not in HOSTS
                or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
                or request.headers.get("origin") not in (None, *ORIGINS)):
            raise HTTPException(403, "local_same_origin_required")
        owner = request.cookies.get(COOKIE)
        if write:
            if request.headers.get("origin") not in ORIGINS:
                raise HTTPException(403, "local_same_origin_required")
            try:
                control.require_session(owner, request.headers.get("x-reops-monitor-token"))
            except ValueError:
                raise HTTPException(403, "monitor_session_invalid") from None
        return owner

    @app.get(RECOVERY + "/status")
    def status(request: Request):
        return response(control.recovery.status(guard(request)))

    @app.post(RECOVERY + "/{operation}")
    async def command(operation: str, request: Request):
        owner = guard(request, True)
        if operation not in {"enable", "enable-dependency", "start-automatic", "disable", "demo", "approve", "cancel"}:
            raise HTTPException(404, "vikunja_operation_not_found")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(415, "json_required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1024:
                raise HTTPException(413, "request_too_large")
        try:
            data = json.loads(raw)
            expected = {"enable": {"approved", "offer_id"}, "enable-dependency": {"approved", "offer_id", "plan_id"}, "start-automatic":{"approved","offer_id","plan_id"}, "disable": set(), "demo": set(),
                        "approve": {"approved", "job_id", "confirmation_id"}, "cancel": {"job_id"}}[operation]
            if (not isinstance(data, dict) or set(data) != expected
                    or ("approved" in expected and data["approved"] is not True)
                    or any(not isinstance(data[k], str) or not 1 <= len(data[k]) <= 200
                           for k in expected - {"approved"})):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(422, "explicit_fixed_scope_request_required") from None
        try:
            if operation == 'start-automatic':
                if data['plan_id'] != 'vikunja_dependency_v1':
                    raise ValueError('policy_plan_invalid')
                await asyncio.to_thread(control.recovery.start_automatic_monitoring,owner,data['offer_id'])
            elif operation in {"enable", "enable-dependency"}:
                if operation == "enable-dependency" and data["plan_id"] != "vikunja_dependency_v1":
                    raise ValueError("policy_plan_invalid")
                await asyncio.to_thread(control.recovery.enable, owner, data["offer_id"], dependency=operation == "enable-dependency")
            elif operation == "disable":
                await asyncio.to_thread(control.recovery.automation.disable)
            elif operation == "demo":
                await asyncio.to_thread(control.recovery.start_demo, owner)
            elif operation == "approve":
                control.recovery.approve_demo(owner, data["job_id"], data["confirmation_id"])
            else:
                control.recovery.cancel_demo(owner, data["job_id"])
        except Exception:
            raise HTTPException(409, "vikunja_state_changed_refresh_required") from None
        return response(control.recovery.status(owner))
