"""Explicit lifecycle and fresh shared 1.0 observations for one fixed HTTP target."""

from copy import deepcopy
from collections import OrderedDict
from datetime import datetime, timezone
import json
import math
import threading
import time
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from .a_docker import BASE_URL, ROOT, TARGET_ID, DockerTarget, TargetError
from .contracts import Component, Target, TargetFeed
from reops_agent.b_clock import utc_now


def now():
    return utc_now().isoformat()


def validate_shared(name, value):
    try:
        json.dumps(value, allow_nan=False)
        schema = json.loads((ROOT / "shared" / (name + ".schema.json")).read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except Exception:
        raise ValueError("invalid_shared_" + name) from None


class HttpProbe:
    def __init__(self, transport=None):
        self.transport = transport

    @staticmethod
    def _json(client, path, trace_id):
        # Bound response size and wall time; never return workload bodies or credentials.
        started = time.monotonic()
        with client.stream("GET", BASE_URL + path, headers={"X-Trace-ID": trace_id,
                                                          "Accept-Encoding": "identity"}) as response:
            body = bytearray()
            if response.headers.get("Content-Encoding", "identity") != "identity":
                return response.status_code, None
            for chunk in response.iter_raw():
                body.extend(chunk)
                if len(body) > 16384 or time.monotonic() - started > 2:
                    return response.status_code, None
            try:
                return response.status_code, json.loads(body)
            except (ValueError, UnicodeError):
                return response.status_code, None

    def read(self, trace_id):
        with httpx.Client(transport=self.transport, timeout=2, trust_env=False,
                          follow_redirects=False) as client:
            try:
                live_code, live_body = self._json(client, "/health/live", trace_id)
                alive = live_code == 200 and live_body == {"status": "healthy"}
            except httpx.HTTPError:
                alive = None
            started = time.monotonic()
            try:
                code, body = self._json(client, "/users", trace_id)
                valid = (code == 200 and isinstance(body, dict) and isinstance(body.get("users"), list)
                         and bool(body["users"]) and all(
                             isinstance(row, dict) and type(row.get("id")) is int
                             and isinstance(row.get("name"), str) for row in body["users"]))
            except httpx.HTTPError:
                code, valid = None, None
            latency = round((time.monotonic() - started) * 1000, 2)
        return alive, code, valid, latency


class TargetMonitor:
    def __init__(self, backend=None, probe=None, *, interval=2):
        if type(interval) not in (int, float) or not math.isfinite(interval) or not 0.1 <= interval <= 60:
            raise ValueError("interval_must_be_0.1_to_60_seconds")
        self.backend, self.probe = backend or DockerTarget(), probe or HttpProbe()
        self.interval = interval
        self.control = threading.RLock()
        self._condition = threading.Condition(threading.RLock())
        self._sampling = threading.Lock()
        self._identity = None
        self._latest = None
        self._last_sample_monotonic = None
        self._watching = False
        self._closed = False
        self._generation = 0
        self._thread = None
        self._observations = OrderedDict()

    def select(self):
        """Explicit read-only discovery. Selection never starts a container or monitoring."""
        with self.control:
            with self._condition:
                if self._closed or self._watching:
                    raise TargetError("pause_before_selection")
            current = self.backend.inspect()
            if not current.running:
                raise TargetError("selection_requires_running_target")
            with self._condition:
                self._identity = current.identity
                self._latest = None
                self._generation += 1
            self.observe("incident-a-selection", "trace-a-selection")
            return self.read_targets()

    def start(self):
        with self.control, self._condition:
            if self._closed or self._identity is None:
                raise TargetError("target_not_selected_or_closed")
            if self._watching:
                return
            self._generation += 1
            self._latest = None
            self._watching = True
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="reops-a-monitor", daemon=True)
                self._thread.start()
            self._condition.notify_all()

    def pause(self):
        # Serializes with actions: once pause returns, no action may start.
        with self.control, self._condition:
            self._watching = False
            self._generation += 1
            self._condition.notify_all()

    def close(self):
        with self.control, self._condition:
            self._watching = False
            self._closed = True
            self._generation += 1
            self._condition.notify_all()
        if self._thread:
            self._thread.join(timeout=25)
            if self._thread.is_alive():
                raise TargetError("monitor_shutdown_pending")

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._watching)
                if self._closed:
                    return
                generation = self._generation
            try:
                self.observe("incident-a-monitor", "trace-a-" + uuid4().hex)
            except TargetError:
                # Pause/reselection invalidates the in-flight generation, not the worker.
                pass
            except Exception:
                with self._condition:
                    self._latest = None
            with self._condition:
                self._condition.wait_for(
                    lambda: self._closed or not self._watching or self._generation != generation,
                    timeout=self.interval)

    def _sample(self, identity, context):
        value = {"schema_version": "1.0", "observation_id": "obs-a-" + uuid4().hex,
                 **context, "timestamp": now(),
                 "system": {"name": "reops-lab", "environment": "docker-local", "target_id": TARGET_ID},
                 "services": {"api": {"status": "unknown"}, "business": {"status": "unknown"}}, "logs": [],
                 "metrics": {"api_up": None},
                 "request": {"method": "GET", "endpoint": "/users", "status_code": None,
                             "latency_ms": None, "business_passed": None},
                 "target_health": "unknown", "sampling_error": None}
        try:
            before = self.backend.inspect()
            if before.identity != identity:
                raise TargetError("selected_target_changed")
            if before.running:
                alive, code, valid, latency = self.probe.read(context["trace_id"])
            else:
                alive, code, valid, latency = False, None, None, None
            after = self.backend.inspect()
            if after != before:
                raise TargetError("target_changed_during_sample")
            value["metrics"]["api_up"] = int(before.running)
            value["services"]["api"] = {
                "status": "unknown" if alive is None else "healthy" if alive else "unhealthy",
                "message": "running" if before.running else "stopped"}
            value["request"].update(status_code=code, latency_ms=latency, business_passed=valid)
            value["services"]["business"] = {
                "status": "unknown" if valid is None else "healthy" if valid else "unhealthy",
                "message": "GET /users payload validation"}
            value["target_health"] = ("unhealthy" if not before.running or alive is False or valid is False
                                      else "unknown" if alive is None or valid is None else "healthy")
            if before.running and (alive is None or valid is None):
                value["sampling_error"] = "http_probe_unavailable"
        except Exception:
            # No raw backend exception, container output or old healthy state is reused.
            value["sampling_error"] = "target_sample_unavailable"
        value["sample_completed_at"] = now()
        validate_shared("observation", value)
        return value

    def observe(self, incident_id, trace_id, case_id=None):
        for identifier in (incident_id, trace_id):
            if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 128:
                raise ValueError("invalid_observation_context")
        if case_id is not None and (not isinstance(case_id, str) or len(case_id) > 128):
            raise ValueError("invalid_observation_context")
        context = dict(incident_id=incident_id, trace_id=trace_id, case_id=case_id)
        with self._condition:
            identity, generation = self._identity, self._generation
            if identity is None or self._closed:
                raise TargetError("target_not_selected_or_closed")
        with self._sampling:
            with self._condition:
                if generation != self._generation or self._closed:
                    raise TargetError("monitor_state_changed_during_sample")
            value = self._sample(identity, context)
            with self._condition:
                if generation != self._generation or self._closed:
                    raise TargetError("monitor_state_changed_during_sample")
                self._latest = deepcopy(value)
                self._last_sample_monotonic = time.monotonic()
                self._observations[value["observation_id"]] = deepcopy(value)
                while len(self._observations) > 128:
                    self._observations.popitem(last=False)
                self._condition.notify_all()
        return value

    def get_observation(self, observation_id):
        with self._condition:
            return deepcopy(self._observations.get(observation_id))

    def latest_observation(self):
        """Pure cache read, not a fresh verification. Caller must check timestamp."""
        with self._condition:
            return deepcopy(self._latest)

    def action_scope(self):
        with self._condition:
            if (not self._watching or self._identity is None or self._closed
                    or self._thread is None or not self._thread.is_alive()):
                raise TargetError("monitoring_not_active")
            return self._identity, self._generation

    def begin_action(self, expected_generation):
        """Caller holds control; invalidate samples started before this authorized action."""
        with self._condition:
            identity, generation = self.action_scope()
            if generation != expected_generation:
                raise TargetError("monitor_state_changed")
            self._generation += 1
            self._latest = None
            self._condition.notify_all()
            return identity

    def read_targets(self):
        """GET path: no I/O, workers, probes, authorization, or recovery."""
        with self._condition:
            if self._identity is None:
                return TargetFeed(status="not_connected", targets=[])
            value = self._latest
            # Stale observations are never displayed as current health after worker failure.
            stale = value is None or time.monotonic() - self._last_sample_monotonic > self.interval + 22
            active = bool(self._watching and self._thread and self._thread.is_alive())
            health = "unknown" if stale else value["target_health"]
            api_health = "unknown" if stale else value["services"]["api"]["status"]
            business = None if stale else value["request"]["business_passed"]
            return TargetFeed(status="ready", targets=[Target(
                id=TARGET_ID, name="ReOps local HTTP API", runtime="docker", health=health,
                monitoring="watching" if active else "paused",
                observed_at=value["timestamp"] if value else None,
                components=[Component(id="api", name="HTTP service", health=api_health),
                            Component(id="business", name="GET /users", health="unknown" if business is None
                                      else "healthy" if business else "unhealthy")],
                allowed_actions=["start_service(web)"] if active and not stale
                    and value["metrics"]["api_up"] == 0 else [])])
