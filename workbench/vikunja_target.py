"""独立 Vikunja 双容器身份与真实任务观测；不改原 reops-lab 白名单。"""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from scripts.vikunja_baseline import BASE_URL
from .a_docker import DockerTarget, ROOT, TargetError
from .a_monitor import TargetMonitor, now, validate_shared
from .contracts import Component, Target, TargetFeed

DIRECTORY = ROOT / "integrations/vikunja"
COMPOSE = DIRECTORY / "compose.yml"
LOCK = DIRECTORY / "images.lock.json"
TARGET_ID = "reops-vikunja-demo"


@dataclass(frozen=True)
class Identity:
    endpoint: str
    engine_id: str
    app_id: str
    postgres_id: str
    app_image: str
    postgres_image: str
    compose_sha256: str
    lock_sha256: str

    def binding(self):
        return {**self.__dict__, "target_id": TARGET_ID, "project": TARGET_ID,
            "root": str(DIRECTORY), "compose_file": str(COMPOSE), "business_url": BASE_URL}


@dataclass(frozen=True)
class Inspection:
    identity: Identity
    running: bool
    postgres_running: bool
    postgres_status: str
    app_started_at: str


class VikunjaDocker(DockerTarget):
    def inspect(self):
        try:
            endpoint = os.environ.get("DOCKER_HOST") or self._run(
                ["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
            endpoint = endpoint.strip()
            if not (re.fullmatch(r"npipe:////\./pipe/[\w.-]+", endpoint)
                    or re.fullmatch(r"unix:///[^\s]+", endpoint)):
                raise TargetError("remote_docker_forbidden")
            engine = self._run(["info", "--format", "{{.ID}}"], endpoint=endpoint).strip()
            if not engine:
                raise TargetError("engine_identity_missing")
            locked = json.loads(LOCK.read_text(encoding="utf-8"))["images"]
            rows = {}
            for service in ("app", "postgres"):
                expected_image = locked[service]["digest"]
                prefix = "ghcr.io/go-vikunja/vikunja" if service == "app" else "postgres"
                registry_reference = re.fullmatch(re.escape(prefix) + r"@sha256:[a-f0-9]{64}", expected_image)
                verified_id = (service == "app" and locked[service].get("reference_type") == "verified_config_image_id"
                    and re.fullmatch(r"sha256:[a-f0-9]{64}", expected_image)
                    and re.fullmatch(re.escape(prefix) + r"@sha256:[a-f0-9]{64}", locked[service].get("registry_digest", "")))
                if not (registry_reference or verified_id):
                    raise TargetError("image_lock_invalid")
                ids = self._run(["ps", "-aq", "--no-trunc", "--filter",
                    "label=com.docker.compose.project=" + TARGET_ID, "--filter",
                    "label=com.docker.compose.service=" + service], endpoint=endpoint).split()
                if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]{64}", ids[0]):
                    raise TargetError("demo_container_missing_or_ambiguous")
                raw = self._run(["inspect", "--format",
                    '{{json .Config.Labels}}\n{{json .HostConfig.PortBindings}}\n{{.Config.Image}}\n'
                    '{{.Image}}\n{{json .State.Running}}\n{{.State.Status}}\n'
                    '{{json .State.Paused}}\n{{json .State.Restarting}}\n{{json .State.Dead}}\n'
                    '{{.State.StartedAt}}\n{{json .NetworkSettings.Networks}}', ids[0]], endpoint=endpoint)
                labels_raw, ports_raw, configured, image, running_raw, status, paused, restarting, dead, started, networks_raw = raw.strip().splitlines()
                labels, ports, running, networks = json.loads(labels_raw), json.loads(ports_raw), json.loads(running_raw), json.loads(networks_raw)
                files = labels.get("com.docker.compose.project.config_files", "").split(",")
                expected_ports = {"3456/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18110"}]}
                expected_networks = {TARGET_ID + "_database"} | ({TARGET_ID + "_entry"} if service == "app" else set())
                if (labels.get("com.docker.compose.project") != TARGET_ID
                    or labels.get("com.docker.compose.service") != service
                    or labels.get("com.docker.compose.oneoff", "").lower() != "false"
                    or Path(labels.get("com.docker.compose.project.working_dir", "")).resolve() != DIRECTORY
                    or len(files) != 1 or Path(files[0]).resolve() != COMPOSE
                    or (ports != expected_ports if service == "app" else ports not in ({}, None))
                    or configured != expected_image or set(networks) != expected_networks
                    or not re.fullmatch(r"sha256:[a-f0-9]{64}", image)):
                    raise TargetError("demo_identity_or_network_mismatch")
                if (type(running) is not bool or any(value != "false" for value in (paused, restarting, dead))
                    or (running, status) not in {(True, "running"), (False, "exited")}):
                    raise TargetError("demo_state_uncertain")
                rows[service] = (ids[0], image, running, status, started)
            app, pg = rows["app"], rows["postgres"]
            identity = Identity(endpoint, engine, app[0], pg[0], app[1], pg[1],
                sha256(COMPOSE.read_bytes()).hexdigest(), sha256(LOCK.read_bytes()).hexdigest())
            return Inspection(identity, app[2], pg[2], pg[3], app[4])
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            raise TargetError("vikunja_inspection_unavailable") from None

    def start(self, expected):
        # Same method name as the existing A boundary; scope only this database.
        current = self.inspect()
        if (current.identity != expected or not current.running or current.postgres_running
                or current.postgres_status != "exited"):
            raise TargetError("database_changed_or_not_stopped")
        self._run(["start", expected.postgres_id], endpoint=expected.endpoint, timeout=30)

    def sql_probe(self, expected):
        current = self.inspect()
        if current.identity != expected or not current.postgres_running:
            raise TargetError("database_scope_changed")
        result = self._run(["exec", expected.postgres_id, "psql", "-U", "reops_demo", "-d",
            "reops_vikunja_demo", "-Atc", "SELECT 1"], endpoint=expected.endpoint, timeout=5)
        return result.strip() == "1"

    def database_stop_time(self, expected):
        current = self.inspect()
        if current.identity != expected or current.postgres_running:
            raise TargetError("dependency_database_not_stopped")
        return self._run(["inspect", "--format", "{{.State.FinishedAt}}", expected.postgres_id],
                         endpoint=expected.endpoint).strip()

    def dependency_exit(self, expected, started_at, database_finished_at=None):
        """只接受同一应用在停库后非 OOM、exit 1 自退；外部停止/重启一律拒绝。"""
        current = self.inspect()
        if current.identity != expected or current.running or current.app_started_at != started_at:
            return False
        def state(container):
            return json.loads(self._run(["inspect", "--format",
                '{"exit":{{.State.ExitCode}},"oom":{{json .State.OOMKilled}},'
                '"finished":{{json .State.FinishedAt}}}', container], endpoint=expected.endpoint))
        app, pg = state(expected.app_id), state(expected.postgres_id)
        database_finished_at = database_finished_at or pg["finished"]
        parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
        if (app["exit"] != 1 or app["oom"] is not False
                or not parse(started_at) < parse(database_finished_at) < parse(app["finished"])):
            return False
        events = self._run(["events", "--since", database_finished_at, "--until", now(),
            "--filter", "container=" + expected.app_id, "--format", "{{.Action}}"], endpoint=expected.endpoint)
        actions = events.splitlines()
        if "die" in actions and not set(actions) & {"stop", "kill", "restart", "start", "destroy", "oom"}:
            return {"database_finished_at": database_finished_at, "app_finished_at": app["finished"],
                "source": "docker_state_and_events"}
        return False

    def start_dependency(self, expected, service, started_at, exit_evidence=None):
        """新方案专用固定启动；旧 start() 的范围不变。"""
        current = self.inspect()
        if current.identity != expected or current.app_started_at != started_at:
            raise TargetError("dependency_identity_changed")
        if service == "postgres":
            if current.postgres_running or (not current.running and not self.dependency_exit(expected, started_at)):
                raise TargetError("dependency_database_not_eligible")
            container = expected.postgres_id
        elif service == "app":
            if (current.running or not current.postgres_running or not exit_evidence
                    or self.dependency_exit(expected, started_at, exit_evidence["database_finished_at"]) != exit_evidence):
                raise TargetError("dependency_application_not_eligible")
            if not self.sql_probe(expected):
                raise TargetError("dependency_sql_not_ready")
            container = expected.app_id
        else:
            raise TargetError("dependency_service_forbidden")
        self._run(["start", container], endpoint=expected.endpoint, timeout=30)


def stopped_database(observation):
    request = observation.get("request", {})
    code = request.get("status_code")
    failed_request = ((type(code) is int and 500 <= code <= 599)
        or (code is None and request.get("failure_kind") == "read_timeout"))
    return (observation.get("target_health") == "unhealthy"
        and observation.get("sampling_error") is None
        and observation.get("services", {}).get("api", {}).get("status") == "healthy"
        and observation.get("services", {}).get("postgres") == {"status": "unhealthy", "message": "stopped"}
        and type(observation.get("metrics", {}).get("postgres_up")) is int
        and observation["metrics"]["postgres_up"] == 0
        and request.get("business_passed") is False and failed_request)


class VikunjaMonitor(TargetMonitor):
    target_id = TARGET_ID

    def __init__(self, business, backend=None, *, interval=2):
        super().__init__(backend=backend or VikunjaDocker(), interval=interval)
        self.business = business

    def _sample(self, identity, context):
        value = {"schema_version": "1.0", **context, "observation_id": "obs-vikunja-" + uuid4().hex,
            "timestamp": now(), "system": {"name": TARGET_ID, "environment": "isolated-demo", "target_id": TARGET_ID},
            "services": {name: {"status": "unknown"} for name in ("api", "postgres", "business")},
            "metrics": {"api_up": None, "postgres_up": None}, "logs": [],
            "request": {"method": "GET", "endpoint": "/api/v1/tasks/{task_id}",
                "status_code": None, "business_passed": None},
            "business": {"project_id": self.business.project_id, "task_id": self.business.task_id},
            "target_health": "unknown", "sampling_error": "sample_unavailable"}
        try:
            before = self.backend.inspect()
            if before.identity != identity:
                raise TargetError("selected_target_changed")
            read_error = None
            if before.running and hasattr(self.business, "read_observation"):
                code, valid, read_error = self.business.read_observation()
            else:
                code, valid = self.business.read() if before.running else (None, None)
            after = self.backend.inspect()
            if after != before:
                raise TargetError("target_changed_during_sample")
            value["metrics"].update(api_up=int(before.running), postgres_up=int(before.postgres_running))
            value["services"]["api"] = {"status": "healthy" if before.running else "unhealthy",
                "message": "container running" if before.running else "stopped"}
            value["services"]["postgres"] = {"status": "healthy" if before.postgres_running else "unhealthy",
                "message": "container running; SQL not checked" if before.postgres_running else "stopped"}
            value["services"]["business"] = {"status": "unknown" if valid is None else "healthy" if valid else "unhealthy"}
            value["request"].update(status_code=code, business_passed=valid)
            if read_error is not None:
                value["request"]["failure_kind"] = read_error
            if not before.running:
                value["request"].update(business_passed=False, failure_kind="container_stopped")
                value["services"]["business"] = {"status": "unhealthy", "message": "application container stopped; HTTP not attempted"}
            value["business"]["app_started_at"] = before.app_started_at
            value["target_health"] = ("unhealthy" if not before.running or not before.postgres_running or valid is False
                                      else "unknown" if valid is None else "healthy")
            value["sampling_error"] = (None if not before.running or code is not None or read_error == "read_timeout"
                                       else "business_request_unavailable")
        except Exception:
            pass
        value["sample_completed_at"] = now()
        validate_shared("observation", value)
        return value

    def read_targets(self):
        with self._condition:
            if self._identity is None:
                return TargetFeed(status="not_connected", targets=[])
            value = self._latest
            stale = value is None or time.monotonic() - self._last_sample_monotonic > self.interval + 22
            active = bool(self._watching and self._thread and self._thread.is_alive())
            return TargetFeed(status="ready", targets=[Target(id=TARGET_ID, name="Vikunja",
                runtime="docker", health="unknown" if stale else value["target_health"],
                monitoring="watching" if active else "paused", observed_at=value["timestamp"] if value else None,
                components=[Component(id=name, name=label,
                    health="unknown" if stale else value["services"][name]["status"])
                    for name, label in (("api", "Vikunja 应用"), ("postgres", "PostgreSQL 容器"), ("business", "真实任务读取"))],
                allowed_actions=["start_service(postgres)"] if active and not stale and stopped_database(value) else [])])
