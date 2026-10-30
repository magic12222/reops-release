"""Read-only C FastAPI facade. Run with: uvicorn dashboard_api.api:create_app --factory."""

import os
import asyncio
import json
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .models import SOURCES
from .live import DashboardEventSink, JournalFollower
from .store import Store
from .system import SystemProbe
from .experiments import ExperimentLedger, SCENARIO
from .benchmark import BenchmarkStore
from .evidence import evidence_page

DEFAULT_DB = Path(__file__).resolve().parents[1] / "runtime" / "dashboard-api.sqlite3"


def _snapshot_frame(run, events, feed_state: str):
    payload = {"run": run.to_dict(), "events": [event.to_dict() for event in events],
               "feed_state": feed_state}
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
    return body, f"retry: 1500\nid: {len(events)}-{run.status}\nevent: snapshot\ndata: {body}\n\n"


async def _stream_snapshots(request: Request, store: Store, run_id: str, source: str,
                            poll_seconds: float = 0.5,
                            feed_state: Callable[[], str] = lambda: "unconfigured"):
    """Full committed snapshots make reconnect safe even after missed events."""
    previous = None
    quiet = 0.0
    while not await request.is_disconnected():
        snapshot = store.snapshot(run_id)
        if snapshot is None or snapshot[0].source != source:
            yield "event: gone\ndata: {}\n\n"
            return
        body, frame = _snapshot_frame(*snapshot, feed_state())
        if body != previous:
            yield frame
            previous = body
            quiet = 0.0
        elif quiet >= 15:
            yield ": keepalive\n\n"
            quiet = 0.0
        await asyncio.sleep(poll_seconds)
        quiet += poll_seconds


def create_app(store: Store | None = None, probe: SystemProbe | None = None,
               follower: JournalFollower | None = None,
               experiments: ExperimentLedger | None = None, web_control=None, workbench_control=None) -> FastAPI:
    store = store or Store(os.getenv("REOPS_C_DB_PATH", str(DEFAULT_DB)))
    experiments = experiments or ExperimentLedger(store.path)
    if Path(experiments.path).resolve() != Path(store.path).resolve():
        raise ValueError("experiment_and_http_database_mismatch")
    benchmarks = BenchmarkStore(store.path)
    probe = probe or SystemProbe()
    if follower is None:
        journal_path = os.getenv("REOPS_C_JOURNAL_PATH")
        journal_source = os.getenv("REOPS_C_JOURNAL_SOURCE")
        if bool(journal_path) != bool(journal_source):
            raise ValueError("both REOPS_C_JOURNAL_PATH and REOPS_C_JOURNAL_SOURCE are required")
        if journal_path:
            follower = JournalFollower(DashboardEventSink(store, source=journal_source), journal_path)

    from .workbench_control import MonitorControl, install_monitor_routes
    workbench_control = workbench_control or MonitorControl(
        enabled=os.getenv("REOPS_WORKBENCH_MONITORING") == "1",
        agent=os.getenv("REOPS_WORKBENCH_AGENT") == "1", discovery=os.getenv("REOPS_WORKBENCH_DISCOVERY") == "1")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def follow():
            while True:
                try:
                    await asyncio.to_thread(follower.poll)
                    app.state.live_state = "ready" if follower.path.exists() else "waiting_for_journal"
                except (OSError, ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
                    app.state.live_state = "error"
                await asyncio.sleep(0.5)

        async with workbench_control.lifespan():
            task = asyncio.create_task(follow()) if follower else None
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

    app = FastAPI(title="ReOps C dashboard read API", lifespan=lifespan)
    app.state.live_state = "waiting_for_journal" if follower else "unconfigured"
    from .web_control import WebControl
    from .web_routes import install_web_routes
    if web_control is None:
        enabled = os.getenv("REOPS_RESEARCHLOOP_WEB") == "1"
        model_store = None
        if enabled and os.name == 'nt':
            from .model_service_store import ModelServiceStore
            model_store = ModelServiceStore(Path(store.path).parent / 'model-services.json')
        web_control = WebControl(store.path, enabled=enabled, model_store=model_store)
    install_web_routes(app, web_control)
    from .workbench import install_workbench_routes
    install_workbench_routes(app)
    install_monitor_routes(app, workbench_control)
    app.state.workbench_control = workbench_control

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "component": "dashboard_api"}

    @app.get("/api/v1/researchloop/experiments")
    def researchloop_experiments():
        from .researchloop import read_records
        return {"scenario": "researchloop_stopped_postgres", "execution": "operator_terminal_or_browser_confirmation"
                if web_control.enabled else "operator_terminal_only",
                "experiments": read_records(store.path)}

    @app.get("/api/v1/system/status")
    def system_status():
        return probe.snapshot()

    @app.get("/api/v1/live/status")
    def live_status():
        return {"state": app.state.live_state,
                "source": follower.sink.source if follower else None}

    @app.get("/api/v1/evaluation-evidence")
    def evaluation_evidence(source: str = Query(...), limit: int = Query(50, ge=1, le=500),
                            offset: int = Query(0, ge=0)):
        if source not in SOURCES:
            raise HTTPException(422, "invalid source")
        return evidence_page(store, source, limit, offset)

    @app.get("/api/v1/benchmarks")
    def list_benchmarks(source: str = Query(...)):
        if source not in SOURCES:
            raise HTTPException(422, "invalid source")
        return {"source": source, "items": benchmarks.list(source),
                "last_import_error": benchmarks.last_import_error(source)}

    @app.get("/api/v1/benchmarks/{report_id}")
    def get_benchmark(report_id: str, source: str = Query(...)):
        if source not in SOURCES:
            raise HTTPException(422, "invalid source")
        result = benchmarks.evaluation(report_id, source)
        if result is None:
            raise HTTPException(404, "benchmark report not found")
        return result

    @app.get("/api/v1/experiments/capabilities")
    def experiment_capabilities():
        return {"entry": "B Phase 8 terminal authorization", "scenarios": [SCENARIO],
                "request_enabled": os.getenv("REOPS_C_EXPERIMENT_REQUESTS") == "1",
                "request_blocked": experiments.has_hold(),
                "execution": "operator_terminal_only"}

    @app.get("/api/v1/experiments")
    def list_experiments():
        return {"items": experiments.list()}

    @app.get("/api/v1/experiments/{experiment_id}")
    def get_experiment(experiment_id: str):
        record = experiments.get(experiment_id)
        if record is None:
            raise HTTPException(404, "experiment not found")
        return record

    @app.post("/api/v1/experiments", status_code=202)
    async def request_experiment(request: Request):
        if os.getenv("REOPS_C_EXPERIMENT_REQUESTS") != "1":
            raise HTTPException(403, "experiment requests disabled")
        if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
            raise HTTPException(403, "loopback experiment requests only")
        allowed_origins = {str(request.base_url).rstrip("/")}
        configured_origin = os.getenv("REOPS_C_REQUEST_ORIGIN")
        if configured_origin:
            allowed_origins.add(configured_origin.rstrip("/"))
        if (request.headers.get("origin") not in (None, *allowed_origins)
                or request.headers.get("sec-fetch-site") == "cross-site"):
            raise HTTPException(403, "same-origin request required")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(415, "application/json required")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1024:
                raise HTTPException(413, "experiment request too large")
        def unique_fields(pairs):
            body = {}
            for key, value in pairs:
                if key in body:
                    raise ValueError("duplicate request field")
                body[key] = value
            return body
        try:
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite value")))
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(422, "invalid experiment request") from None
        if not isinstance(body, dict):
            raise HTTPException(422, "invalid experiment request")
        if set(body) != {"scenario"} or body["scenario"] != SCENARIO:
            raise HTTPException(422, "unsupported experiment scenario")
        try:
            return experiments.queue(body["scenario"])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/v1/runs")
    def list_runs(source: str | None = None, limit: int = Query(50, ge=1, le=500),
                  offset: int = Query(0, ge=0)):
        if source is not None and source not in SOURCES:
            raise HTTPException(422, "invalid source")
        items, total = store.list_runs(source=source, limit=limit, offset=offset)
        return {"items": [item.to_dict() for item in items], "total": total,
                "limit": limit, "offset": offset}

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str):
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return run.to_dict()

    @app.get("/api/v1/runs/{run_id}/events")
    def get_events(run_id: str):
        if store.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        events = store.list_events(run_id)
        return {"run_id": run_id, "items": [item.to_dict() for item in events],
                "total": len(events)}

    @app.get("/api/v1/runs/{run_id}/stream")
    async def stream_run(run_id: str, request: Request, source: str = Query(...)):
        if source not in SOURCES:
            raise HTTPException(422, "invalid source")
        run = store.get_run(run_id)
        if run is None or run.source != source:
            raise HTTPException(404, "run not found")
        return StreamingResponse(_stream_snapshots(request, store, run_id, source,
                                                  feed_state=lambda: app.state.live_state
                                                  if follower and follower.sink.source == source
                                                  else "unconfigured"),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store",
                                          "X-Accel-Buffering": "no"})

    return app
