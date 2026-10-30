"""ResearchLoop独立网页输入通道：真人原挑战、原Gate、原DB编排。"""
from copy import deepcopy
import json
from pathlib import Path
import secrets
from threading import Condition, RLock, Thread
import time
from uuid import uuid4

from reops_agent.authorization import AuthorizationGate
from reops_agent.contracts import PROJECT_ROOT
from reops_agent.credential_handling import redact_persistent
from reops_agent.memory import RecoveryMemory
from .model_endpoints import WebRCAProvider as NexentRCAProvider
from .model_registry import ModelRegistry
from reops_agent.researchloop_backend import ResearchLoopBackend, healthy
from reops_agent.researchloop_recovery import run_database
from reops_agent.trace_journal import TraceJournal
from scripts.researchloop_baseline import BusinessSession
from scripts.run_researchloop_recovery import write_new
from .experiments import ExperimentLedger
from .researchloop import DatabaseLedger
from .live import DashboardEventSink, JournalFollower
from .store import Store
from .web_model import WebModel, existing_config
from .run_authorization import RunGate
from reops_agent.authorization import digest


class BrowserConfirmation:
    def __init__(self, *, timeout=120):
        self.condition = Condition()
        self.pending = None
        self.answer = None
        self.cancelled = False
        self.timeout = timeout

    def __call__(self, request, challenge):
        with self.condition:
            if self.cancelled:
                return None
            self.answer = None
            self.pending = {"id": "confirmation-" + uuid4().hex, "request": redact_persistent(request),
                            "challenge": challenge, "expires_at": time.time() + self.timeout}
            deadline = time.monotonic() + self.timeout
            while self.answer is None and not self.cancelled:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)
            answer = self.answer
            self.pending = self.answer = None
            return answer

    def status(self):
        with self.condition:
            return deepcopy(self.pending)

    def respond(self, confirmation_id, answer):
        with self.condition:
            if (self.cancelled or self.pending is None or self.answer is not None
                    or self.pending["id"] != confirmation_id or time.time() >= self.pending["expires_at"]):
                raise ValueError("confirmation_expired_or_consumed")
            if not isinstance(answer, str) or not answer.isascii() or not secrets.compare_digest(answer, self.pending["challenge"]):
                raise ValueError("confirmation_text_mismatch")
            # 原样交付真人输入，不能根据点击生成或替换成服务端持有的challenge。
            self.answer = answer
            self.condition.notify_all()

    def cancel(self):
        with self.condition:
            self.cancelled = True
            self.condition.notify_all()

    def approve_run(self, confirmation_id):
        with self.condition:
            if (self.cancelled or self.pending is None or self.answer is not None
                    or self.pending["id"] != confirmation_id
                    or self.pending["request"].get("authorization_mode") != "single_run"
                    or time.time() >= self.pending["expires_at"]):
                raise ValueError("confirmation_expired_or_consumed")
            # 新的明确点击批准协议；不将点击伪称为人工输入原挑战。
            self.answer = self.pending["challenge"]
            self.condition.notify_all()


class BrowserGate(AuthorizationGate):
    def consume(self, *args, **kwargs):
        proof = super().consume(*args, **kwargs)
        proof["source"] = "interactive_browser_confirmation"
        return proof


class WebControl:
    def __init__(self, db_path, *, enabled=False, model=None, runner=None, model_store=None):
        self.db_path = Path(db_path)
        self.enabled = enabled
        self.model = ModelRegistry(model or WebModel(existing_config() if enabled else None), store=model_store)
        self.runner = runner or self._run_real
        self.lock = RLock()
        self.sessions, self.jobs = {}, {}
        self.active = None
        self.last_start = None

    def session(self, session_id):
        with self.lock:
            if session_id not in self.sessions:
                if len(self.sessions) >= 128:
                    active_owner = self.jobs[self.active]["owner"] if self.active else None
                    candidates = [key for key in self.sessions if key != active_owner]
                    if candidates:
                        del self.sessions[min(candidates, key=lambda key: self.sessions[key]["last_seen"])]
                session_id = secrets.token_urlsafe(32)
                self.sessions[session_id] = {"csrf": secrets.token_urlsafe(32), "last_seen": time.monotonic()}
            self.sessions[session_id]["last_seen"] = time.monotonic()
            # 仅清理没有运行中任务的过期会话；不因关闭网页杀死正在验证/善后的任务。
            active_owner = self.jobs[self.active]["owner"] if self.active else None
            for key, value in list(self.sessions.items()):
                if key != session_id and key != active_owner and time.monotonic() - value["last_seen"] > 7200:
                    del self.sessions[key]
            return session_id, self.sessions[session_id]["csrf"]

    def require_session(self, session_id, csrf):
        with self.lock:
            value = self.sessions.get(session_id)
            if (value is None or not isinstance(csrf, str) or not csrf.isascii() or not secrets.compare_digest(value["csrf"], csrf)):
                raise ValueError("browser_session_invalid")
            value["last_seen"] = time.monotonic()

    def _job_status(self, job):
        return {key: deepcopy(job[key]) for key in ("id", "strategy", "state", "incident_id", "trace_id",
            "experiment_id", "result", "error", "cancel_requested")} | {"confirmation": job["confirm"].status()}

    def status(self, owner):
        with self.lock:
            own = [job for job in self.jobs.values() if job["owner"] == owner]
            return {"enabled": self.enabled, "busy": self.active is not None, "model": self.model.status(),
                "job": self._job_status(own[-1]) if own else None}

    def configure(self, key):
        with self.lock:
            if self.active:
                raise ValueError("experiment_busy")
            self.model.set_key(key)

    def save_service(self, fields, service_id=None):
        with self.lock:
            if self.active:
                raise ValueError("experiment_busy")
            # The API management page edits a candidate, never the active model snapshot.
            return self.model.save(fields, service_id, preserve_active=fields.get('as_candidate', False),
                                   expected_revision=fields.get('expected_revision'))

    def select_service(self, service_id):
        with self.lock:
            if self.active:
                raise ValueError("experiment_busy")
            return self.model.select(service_id)

    def verify(self, service_id=None):
        with self.lock:
            if self.active:
                raise ValueError("experiment_busy")
            return self.model.verify(service_id)

    def start(self, owner, strategy, *, single_run=False):
        if strategy not in {"model", "experience"}:
            raise ValueError("unsupported_database_strategy")
        with self.lock:
            if not self.enabled:
                raise ValueError("web_operations_disabled")
            if self.active:
                job = self.jobs[self.active]
                if job["owner"] == owner and job["strategy"] == strategy and job.get("single_run", False) == single_run:
                    return self._job_status(job)
                raise ValueError("experiment_busy")
            config = self.model.for_run()
            if self.last_start is not None and time.monotonic() - self.last_start < 30:
                raise ValueError("experiment_start_rate_limited")
            job = {"id": "web-job-" + uuid4().hex, "owner": owner, "strategy": strategy, "state": "running",
                "model_binding": self.model.binding(), "single_run": single_run,
                "incident_id": "incident-researchloop-" + uuid4().hex,
                "trace_id": "trace-researchloop-" + uuid4().hex, "experiment_id": None,
                "result": None, "error": None, "cancel_requested": False, "confirm": BrowserConfirmation(timeout=300 if single_run else 120)}
            self.jobs[job["id"]] = job
            self.active, self.last_start = job["id"], time.monotonic()
            try:
                Thread(target=self._work, args=(job, config), daemon=True).start()
            except Exception:
                job.update(state="finished", error="web_worker_unavailable", result="unknown")
                self.active = None
                raise ValueError("web_worker_unavailable") from None
            return self._job_status(job)

    def _owned(self, owner, job_id):
        job = self.jobs.get(job_id)
        if job is None or job["owner"] != owner:
            raise ValueError("web_job_not_found")
        return job

    def respond(self, owner, job_id, confirmation_id, answer):
        with self.lock:
            job = self._owned(owner, job_id)
            if job["state"] != "running":
                raise ValueError("web_job_already_finished")
            job["confirm"].respond(confirmation_id, answer)

    def cancel(self, owner, job_id):
        with self.lock:
            job = self._owned(owner, job_id)
            if job["state"] != "running":
                raise ValueError("web_job_already_finished")
            job["cancel_requested"] = True
            job["confirm"].cancel()

    def approve_run(self, owner, job_id, confirmation_id):
        with self.lock:
            job = self._owned(owner, job_id)
            if job["state"] != "running" or not job.get("single_run"):
                raise ValueError("web_job_already_finished")
            job["confirm"].approve_run(confirmation_id)

    def _work(self, job, config):
        try:
            result = self.runner(job, config)
            with self.lock:
                job.update(state="finished", result=result["result"])
        except Exception:
            with self.lock:
                job.update(state="finished", result="unknown", error="web_run_failed_inspect_evidence")
        finally:
            with self.lock:
                self.active = None

    def _run_real(self, job, config):
        c4 = ExperimentLedger(self.db_path)
        if c4.has_hold() or any(item["state"] != "finished" for item in c4.list()):
            raise ValueError("c4_experiment_pending_or_blocked")
        ledger = DatabaseLedger(self.db_path)
        if any(item.get("state") != "finished" or item.get("review_required") is not False for item in ledger.list()):
            raise ValueError("database_experiment_requires_operator_inspection")
        context = {key: job[key] for key in ("incident_id", "trace_id")}
        directory = PROJECT_ROOT / "runtime/researchloop-evidence" / job["trace_id"]
        directory.mkdir(parents=True, exist_ok=False)
        write_new(directory / "request.json", {**context, "scenario": "researchloop_stopped_postgres",
            "authorization_channel": "single_run_browser_approval" if job.get("single_run") else "browser_manual_challenge", "model_service": job["model_binding"], "max_model_calls": 1, "max_output_tokens": 512,
            "experience_fast_path_requested": job["strategy"] == "experience"})
        business = BusinessSession()
        try:
            backend = ResearchLoopBackend(business)
            baseline = backend.observe({"schema_version": "1.0", **context})
            if not healthy(baseline):
                raise ValueError("database_baseline_not_healthy")
            record = ledger.claim_new(context)
            with self.lock:
                job["experiment_id"] = record["id"]
            sink = DashboardEventSink(Store(self.db_path), source="real")
            class PublishingJournal(TraceJournal):
                def record(self, *args, **kwargs):
                    event = super().record(*args, **kwargs)
                    sink.publish(event)
                    return event
            journal = PublishingJournal(context, PROJECT_ROOT / "runtime/researchloop-audit.jsonl")
            ledger_path = PROJECT_ROOT / "runtime/researchloop-authorizations.sqlite3"
            gate = RunGate(ledger_path, confirm=job["confirm"], context=context,
                model_digest=digest(json.dumps(job["model_binding"], sort_keys=True))) if job.get("single_run") else BrowserGate(ledger_path, confirm=job["confirm"])
            report = run_database(backend, NexentRCAProvider(config), gate=gate,
                journal=journal, memory=RecoveryMemory(PROJECT_ROOT / "runtime/researchloop-memory.jsonl"),
                model_identifier=json.dumps(job["model_binding"], sort_keys=True), execute=True, fast_path=job["strategy"] == "experience")
            saved = False
            try:
                write_new(directory / "report.json", report)
                JournalFollower(sink, journal.path).poll()
                saved = True
            finally:
                finished = ledger.finish(record["id"], report, saved=saved)
            return finished
        finally:
            business.close()
