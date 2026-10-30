"""Vikunja 真实边界的离线替身验证；绝不运行 Docker 或网络。"""
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from reops_agent.authorization import AuthorizationGate
from scripts.vikunja_baseline import BusinessSession
from workbench import vikunja_target as target
from workbench.a_docker import TargetError
from workbench.vikunja_actions import VikunjaRecoveryTool


IDENTITY = target.Identity("npipe:////./pipe/dockerDesktopLinuxEngine", "engine",
    "a" * 64, "b" * 64, "sha256:" + "c" * 64, "sha256:" + "d" * 64, "compose", "lock")


class Backend:
    def __init__(self, *, stopped=True):
        self.stopped = stopped
        self.started = 0
        self.identity = IDENTITY

    def inspect(self):
        return target.Inspection(self.identity, True, not self.stopped,
            "exited" if self.stopped else "running", "2026-10-27T00:00:00Z")

    def start(self, identity):
        assert identity == self.identity
        self.started += 1
        self.stopped = False


def active_monitor(*, code=500, stopped=True):
    backend = Backend(stopped=stopped)
    business = SimpleNamespace(project_id=1, task_id=2,
        read=lambda: (code, code == 200) if backend.stopped else (200, True))
    monitor = target.VikunjaMonitor(business, backend=backend)
    monitor._identity = IDENTITY
    monitor._watching = True
    monitor._thread = SimpleNamespace(is_alive=lambda: True)
    return monitor


def action():
    return {"schema_version": "1.0", "action_id": "vikunja-action-test", "incident_id": "incident-test",
        "trace_id": "trace-test", "diagnosis_id": "diagnosis-test", "timestamp": target.now(),
        "action": "start_service", "target": "postgres", "reason": "stopped database with real business failure",
        "expected_success": .8, "estimated_cost": .1, "risk": .1, "requires_approval": False, "parameters": {}}


def test_database_failure_preserves_live_app_and_real_business_failure():
    monitor = active_monitor()
    sample = monitor.observe("incident-test", "trace-test")
    assert sample["metrics"] == {"api_up": 1, "postgres_up": 0}
    assert sample["services"]["api"]["status"] == "healthy"
    assert target.stopped_database(sample)
    assert monitor.read_targets().targets[0].allowed_actions == ["start_service(postgres)"]


@pytest.mark.parametrize("failure,valid,stopped,allowed", [
    ("read_timeout", False, True, True),
    (None, None, True, False),
    ("connect_timeout", False, True, False),
    ("read_timeout", None, True, False),
    ("read_timeout", False, False, False),
])
def test_measured_timeout_requires_failed_business_and_confirmed_stopped_database(failure, valid, stopped, allowed):
    monitor = active_monitor(stopped=stopped)
    monitor.business.read_observation = lambda: (None, valid, failure)
    sample = monitor.observe("incident-test", "trace-test")
    assert target.stopped_database(sample) is allowed
    if allowed:
        assert VikunjaRecoveryTool(monitor).prepare(action())["action"]["target"] == "postgres"
    else:
        with pytest.raises(TargetError):
            VikunjaRecoveryTool(monitor).prepare(action())
    assert monitor.backend.started == 0


@pytest.mark.parametrize("code", [None, 200, 401, 403, 404])
def test_auth_or_unknown_response_does_not_authorize_recovery(code):
    monitor = active_monitor(code=code)
    with pytest.raises(TargetError):
        VikunjaRecoveryTool(monitor).prepare(action())
    assert monitor.backend.started == 0


@pytest.mark.parametrize("change", [
    {"action": "restart_service"}, {"target": "web"}, {"parameters": {"force": True}},
    {"parameters": {"nested": {"shell": "unsafe"}}}, {"risk": .3}, {"requires_approval": True},
])
def test_tool_rejects_other_actions_or_parameters(change):
    monitor = active_monitor()
    proposal = {**action(), **change}
    with pytest.raises((TargetError, ValueError)):
        VikunjaRecoveryTool(monitor).prepare(proposal)
    assert monitor.backend.started == 0


def test_scope_changes_fail_closed():
    monitor = active_monitor()
    monitor.backend.identity = target.Identity(**{**IDENTITY.__dict__, "postgres_id": "e" * 64})
    with pytest.raises(TargetError):
        VikunjaRecoveryTool(monitor).prepare(action())


def test_no_grant_no_mutation_then_single_original_gate_consumption(tmp_path):
    monitor = active_monitor()
    tool = VikunjaRecoveryTool(monitor)
    proposal = action()
    assert tool.execute(proposal)["execution_status"] == "rejected"
    assert monitor.backend.started == 0
    gate = AuthorizationGate(tmp_path / "grants.sqlite3", confirm=lambda _, challenge: challenge)
    grant = gate.request("recovery", tool.prepare(proposal))
    result = tool.execute(proposal, gate=gate, grant=grant)
    assert result["execution_status"] == "succeeded"
    assert result["target_id"] == "reops-vikunja-demo"
    assert monitor.backend.started == 1
    assert tool.execute(proposal, gate=gate, grant=grant)["execution_status"] == "rejected"
    assert monitor.backend.started == 1


def test_pause_and_stale_samples_offer_no_action():
    monitor = active_monitor()
    monitor.observe("incident-test", "trace-test")
    monitor._last_sample_monotonic -= 60
    assert monitor.read_targets().targets[0].health == "unknown"
    assert not monitor.read_targets().targets[0].allowed_actions
    monitor._watching = False
    with pytest.raises(TargetError):
        VikunjaRecoveryTool(monitor).prepare(action())


def test_live_backend_rejects_test_confirmation_adapter(tmp_path):
    monitor = active_monitor()
    class LiveLike(target.VikunjaDocker):
        def inspect(self):
            return target.Inspection(IDENTITY, True, False, "exited", "2026-10-27T00:00:00Z")
        def start(self, identity):
            raise AssertionError("must never mutate")
    monitor.backend = LiveLike()
    tool = VikunjaRecoveryTool(monitor)
    proposal = action()
    gate = AuthorizationGate(tmp_path / "grants.sqlite3", confirm=lambda _, challenge: challenge)
    grant = gate.request("recovery", tool.prepare(proposal))
    assert tool.execute(proposal, gate=gate, grant=grant)["execution_status"] == "rejected"


@pytest.mark.parametrize("wrong_field", ["port", "project", "image", "network", "state"])
def test_docker_identity_rejects_wrong_target(monkeypatch, tmp_path, wrong_field):
    lock = tmp_path / "images.lock.json"
    images = {name: {"digest": repo + "@sha256:" + character * 64}
        for name, repo, character in (("app", "ghcr.io/go-vikunja/vikunja", "1"), ("postgres", "postgres", "2"))}
    lock.write_text(json.dumps({"images": images}))
    monkeypatch.setattr(target, "LOCK", lock)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    class Docker(target.VikunjaDocker):
        def _run(self, args, **kwargs):
            if args[0] == "context": return IDENTITY.endpoint
            if args[0] == "info": return "engine"
            if args[0] == "ps": return ("a" if args[-1].endswith("app") else "b") * 64
            service = "app" if args[-1].startswith("a") else "postgres"
            labels = {"com.docker.compose.project": target.TARGET_ID,
                "com.docker.compose.service": service, "com.docker.compose.oneoff": "False",
                "com.docker.compose.project.working_dir": str(target.DIRECTORY),
                "com.docker.compose.project.config_files": str(target.COMPOSE)}
            ports = {"3456/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18110"}]} if service == "app" else {}
            networks = {target.TARGET_ID + "_database": {}}
            if service == "app": networks[target.TARGET_ID + "_entry"] = {}
            image = images[service]["digest"]
            status = "running"
            if service == "app":
                if wrong_field == "project": labels["com.docker.compose.project"] = "other"
                if wrong_field == "port": ports["3456/tcp"][0]["HostIp"] = "0.0.0.0"
                if wrong_field == "image": image = "unapproved:latest"
                if wrong_field == "network": networks["another_project_network"] = {}
                if wrong_field == "state": status = "restarting"
            return "\n".join([json.dumps(labels), json.dumps(ports), image, "sha256:" + "c" * 64,
                "true", status, "false", "false", "false", "2026-10-27T00:00:00Z", json.dumps(networks)])
    with pytest.raises(TargetError):
        Docker().inspect()


@pytest.mark.parametrize("existing_account", [False, True])
def test_business_session_uses_database_backed_endpoints_and_no_write_replay(existing_account):
    rows = {}
    requests = []
    def handle(request):
        requests.append(request.url.path)
        path = request.url.path
        if path.endswith("/register"): return httpx.Response(200, json={"id": 1})
        if path.endswith("/login"): return httpx.Response(200, json={"token": "test-secret-never-export"})
        if path == "/api/v1/projects": return httpx.Response(201, json={"id": 1})
        if request.method == "PUT":
            identifier = len(rows) + 1
            rows[identifier] = {"id": identifier, "project_id": 1, **json.loads(request.content)}
            return httpx.Response(201, json=rows[identifier])
        identifier = int(path.rsplit("/", 1)[1])
        if request.method == "POST": rows[identifier].update(json.loads(request.content))
        return httpx.Response(200, json=deepcopy(rows[identifier]))
    credentials = {"username": "existing-demo", "password": "offline-fixture"} if existing_account else {}
    session = BusinessSession(transport=httpx.MockTransport(handle), **credentials)
    try:
        assert session.read() == (200, True)
        assert session.update()
        assert session.write_probe() and session.read_probe()
        with pytest.raises(ValueError, match="already_attempted"):
            session.write_probe()
        assert requests.count("/api/v1/projects/1/tasks") == 2
        assert requests.count("/api/v1/register") == (0 if existing_account else 1)
        assert not hasattr(session, "password")
    finally:
        session.close()
    assert "Authorization" not in session.client.headers
