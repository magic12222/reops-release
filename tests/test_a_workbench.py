"""A workbench boundaries, lifecycle and shared contract tests. All I/O is fake."""

from copy import deepcopy
from dataclasses import replace
import json
import subprocess
import threading
from types import SimpleNamespace

import httpx
import pytest

from reops_agent.authorization import AuthorizationGate
from workbench import a_adapter
from workbench.a_actions import RecoveryTool
from workbench.a_docker import DockerTarget, Identity, Inspection, ROOT, TargetError
from workbench.a_monitor import HttpProbe, TargetMonitor, validate_shared

IDENTITY = Identity("unix:///var/run/docker.sock", "engine-1", "a" * 64, "sha256:" + "b" * 64, "c" * 64)


class Backend:
    def __init__(self):
        self.current = Inspection(IDENTITY, True, "running")
        self.failure = False
        self.calls = 0
        self.starts = 0
        self.start_failure = False

    def inspect(self):
        self.calls += 1
        if self.failure:
            raise RuntimeError("secret-sentinel")
        return self.current

    def stop_externally(self):
        self.current = replace(self.current, running=False, status="exited")

    def start(self, expected):
        assert self.current.identity == expected and not self.current.running
        self.starts += 1
        if self.start_failure:
            raise TargetError("secret-sentinel")
        self.current = replace(self.current, running=True, status="running")


class Probe:
    def __init__(self):
        self.result = (True, 200, True, 1.0)
        self.calls = 0

    def read(self, trace_id):
        self.calls += 1
        return self.result


@pytest.fixture
def setup():
    backend, probe = Backend(), Probe()
    monitor = TargetMonitor(backend, probe, interval=0.1)
    yield monitor, backend, probe
    monitor.close()
    a_adapter.uninstall(monitor)


def wait_sample(monitor):
    with monitor._condition:
        assert monitor._condition.wait_for(lambda: monitor._latest is not None, timeout=2)


def active(monitor):
    monitor.select()
    monitor.start()
    wait_sample(monitor)


def action():
    value = json.loads((ROOT / "shared/examples/recovery_action.example.json").read_text())
    value.update(action="start_service", target="web", case_id=None)
    return value


def test_default_and_get_never_select_sample_or_start(setup):
    monitor, backend, probe = setup
    a_adapter.install(monitor)
    for _ in range(3):
        assert a_adapter.read_targets().model_dump() == {"status": "not_connected", "targets": []}
    assert backend.calls == probe.calls == backend.starts == 0
    assert monitor._thread is None


def test_select_requires_running_and_keeps_paused(setup):
    monitor, backend, _ = setup
    backend.stop_externally()
    with pytest.raises(TargetError):
        monitor.select()
    assert monitor.read_targets().status == "not_connected"
    backend.current = Inspection(IDENTITY, True, "running")
    target = monitor.select().targets[0]
    assert target.monitoring == "paused" and target.health == "healthy"
    assert target.allowed_actions == []
    assert monitor._thread is None


def test_business_error_does_not_claim_process_exit(setup):
    monitor, _, probe = setup
    probe.result = (True, 503, False, 1)
    target = monitor.select().targets[0]
    value = monitor.latest_observation()
    validate_shared("observation", value)
    assert target.health == "unhealthy" and target.components[0].health == "healthy"
    assert value["services"]["api"]["status"] == "healthy" and value["metrics"]["api_up"] == 1
    assert value["request"]["status_code"] == 503


def test_failed_sample_replaces_old_health_with_unknown(setup):
    monitor, backend, _ = setup
    monitor.select()
    previous = monitor.latest_observation()
    backend.failure = True
    value = monitor.observe("i", "t")
    assert value["observation_id"] != previous["observation_id"]
    assert monitor.read_targets().targets[0].health == "unknown"
    assert value["request"]["status_code"] is None and value["metrics"]["api_up"] is None
    assert "secret-sentinel" not in json.dumps(value)


def test_external_stop_discovered_by_worker_without_get_or_injection(setup):
    monitor, backend, _ = setup
    active(monitor)
    backend.stop_externally()
    with monitor._condition:
        assert monitor._condition.wait_for(lambda: monitor._latest["metrics"]["api_up"] == 0, timeout=2)
    target = monitor.read_targets().targets[0]
    assert target.health == "unhealthy" and target.monitoring == "watching"
    assert target.allowed_actions == ["start_service(web)"]
    assert backend.starts == 0


def test_recreated_container_keeps_target_id_but_blocks_observation_and_recovery(setup):
    monitor, backend, _ = setup
    active(monitor)
    original_id = monitor.read_targets().targets[0].id
    backend.current = replace(backend.current, identity=replace(IDENTITY, container_id="d" * 64))
    value = monitor.observe("i", "t")
    assert value["sampling_error"] and monitor.read_targets().targets[0].health == "unknown"
    backend.stop_externally()
    assert RecoveryTool(monitor).execute(action())["execution_status"] == "rejected"
    assert backend.starts == 0
    monitor.pause()
    backend.current = replace(backend.current, running=True, status="running")
    assert monitor.select().targets[0].id == original_id


def test_pause_discards_inflight_sample_and_resume_uses_one_worker(setup):
    monitor, _, probe = setup
    monitor.select()
    entered, release = threading.Event(), threading.Event()
    def blocked(trace_id):
        entered.set()
        assert release.wait(2)
        return True, 200, True, 1
    probe.read = blocked
    monitor.start()
    worker = monitor._thread
    assert entered.wait(2)
    monitor.pause()
    assert monitor.read_targets().targets[0].monitoring == "paused"
    assert monitor.latest_observation() is None
    release.set()
    probe.read = lambda trace_id: (True, 200, True, 1)
    monitor.start()
    wait_sample(monitor)
    assert monitor._thread is worker and worker.is_alive()


def test_explicit_fresh_observation_context_and_read_copies(setup):
    monitor, _, _ = setup
    monitor.select()
    value = monitor.observe("incident-b", "trace-b", "case-b")
    assert (value["incident_id"], value["trace_id"], value["case_id"]) == ("incident-b", "trace-b", "case-b")
    value["services"]["api"]["status"] = "unknown"
    assert monitor.get_observation(value["observation_id"])["services"]["api"]["status"] == "healthy"
    cached = monitor.latest_observation()
    cached["metrics"]["api_up"] = 100
    assert monitor.latest_observation()["metrics"]["api_up"] == 1


def test_installed_get_uses_cache_without_sampling_or_control_routes(setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from dashboard_api.workbench import install_workbench_routes
    monitor, backend, probe = setup
    monitor.select()
    a_adapter.install(monitor)
    counts = backend.calls, probe.calls
    app = FastAPI()
    install_workbench_routes(app)
    with TestClient(app) as client:
        response = client.get("/api/v1/workbench/snapshot")
        assert response.status_code == 200
        assert response.json()["a_status"] == "ready"
        assert response.json()["targets"][0]["monitoring"] == "paused"
        assert client.post("/api/v1/workbench/snapshot", json={}).status_code == 405
    assert (backend.calls, probe.calls) == counts and backend.starts == 0


def test_stale_sample_and_http_timeout_never_reuse_healthy_business(setup):
    monitor, _, probe = setup
    monitor.select()
    monitor._last_sample_monotonic -= 100
    target = monitor.read_targets().targets[0]
    assert target.health == "unknown" and all(c.health == "unknown" for c in target.components)
    probe.result = (True, None, None, 2)
    value = monitor.observe("i", "t")
    assert value["target_health"] == "unknown" and value["metrics"]["api_up"] == 1
    assert value["request"]["business_passed"] is None


@pytest.mark.parametrize("result", [(True, 200, False, 1), (True, None, None, 2), (True, 503, False, 1)])
def test_existing_b_verify_cannot_treat_invalid_or_unknown_business_as_recovered(setup, result):
    from reops_agent.verification import verify
    monitor, _, probe = setup
    probe.result = result
    monitor.select()
    _, _, recovered = verify(monitor.latest_observation())
    assert recovered is False


def test_authorized_start_returns_real_result_and_fresh_post_observation(setup, tmp_path):
    monitor, backend, _ = setup
    active(monitor)
    backend.stop_externally()
    tool, request = RecoveryTool(monitor), action()
    gate = AuthorizationGate(tmp_path / "gate.sqlite3", confirm=lambda request, challenge: challenge)
    grant = gate.request("recovery", tool.prepare(request))
    result = tool.execute(request, gate=gate, grant=grant)
    validate_shared("recovery_result", result)
    assert result["execution_status"] == "succeeded" and result["exit_code"] == 0 and backend.starts == 1
    post = monitor.get_observation(result["post_observation_id"])
    assert post["incident_id"] == request["incident_id"] and post["trace_id"] == request["trace_id"]
    assert result["verification"]["business_request_passed"] is True
    assert result["verification"]["fault_cleared"] is None
    backend.stop_externally()
    assert tool.execute(request, gate=gate, grant=grant)["execution_status"] == "rejected"
    assert backend.starts == 1
    # A fresh Gate/grant with the same persistent action ID also cannot replay.
    gate2 = AuthorizationGate(tmp_path / "gate.sqlite3", confirm=lambda request, challenge: challenge)
    grant2 = gate2.request("recovery", tool.prepare(request))
    assert tool.execute(request, gate=gate2, grant=grant2)["execution_status"] == "rejected"
    assert backend.starts == 1


@pytest.mark.parametrize("change", ["pause", "changed_action", "changed_container", "expired", "missing"])
def test_grant_cannot_override_pause_binding_identity_or_expiration(setup, tmp_path, change):
    monitor, backend, _ = setup
    active(monitor)
    backend.stop_externally()
    tool, request, clock = RecoveryTool(monitor), action(), [100.0]
    gate = AuthorizationGate(tmp_path / "gate.sqlite3", confirm=lambda request, challenge: challenge,
                             clock=lambda: clock[0], ttl=1)
    grant = gate.request("recovery", tool.prepare(request))
    if change == "pause":
        monitor.pause()
    elif change == "changed_action":
        request["trace_id"] = "different"
    elif change == "changed_container":
        backend.current = replace(backend.current, identity=replace(IDENTITY, container_id="d" * 64))
    elif change == "expired":
        clock[0] = 102
    else:
        grant = None
    assert tool.execute(request, gate=gate, grant=grant)["execution_status"] == "rejected"
    assert backend.starts == 0


@pytest.mark.parametrize("update", [dict(target="postgres"), dict(target="api"), dict(action="restart_service"),
    dict(parameters={"shell": "whoami"}), dict(extension={"nested": {"COMMAND": "whoami"}}),
    dict(risk=0.8), dict(requires_approval=True), dict(risk=float("nan"))])
def test_whitelist_and_finite_schema_rejection_before_mutation(setup, update):
    monitor, backend, _ = setup
    active(monitor)
    backend.stop_externally()
    request = {**action(), **update}
    try:
        result = RecoveryTool(monitor).execute(request)
        assert result["execution_status"] == "rejected"
    except ValueError as exc:
        assert "invalid_shared_recovery_action" in str(exc)
    assert backend.starts == 0


def test_failed_start_and_successful_command_do_not_fabricate_business_recovery(setup, tmp_path):
    monitor, backend, probe = setup
    active(monitor)
    backend.stop_externally()
    backend.start_failure = True
    tool, request = RecoveryTool(monitor), action()
    gate = AuthorizationGate(tmp_path / "gate.sqlite3", confirm=lambda request, challenge: challenge)
    grant = gate.request("recovery", tool.prepare(request))
    result = tool.execute(request, gate=gate, grant=grant)
    assert result["execution_status"] == "failed" and result["verification"]["status"] != "recovered"
    assert "secret-sentinel" not in json.dumps(result)
    backend.start_failure = False
    probe.result = (True, 503, False, 1)
    request["action_id"] = "new-action"
    grant = gate.request("recovery", tool.prepare(request))
    result = tool.execute(request, gate=gate, grant=grant)
    assert result["execution_status"] == "succeeded" and result["verification"]["status"] == "not_recovered"


def docker_runner(mutations=None):
    labels = {"com.docker.compose.project": "reops-lab", "com.docker.compose.service": "api",
              "com.docker.compose.oneoff": "False", "com.docker.compose.project.working_dir": str(ROOT),
              "com.docker.compose.project.config_files": str(ROOT / "docker-compose.yml")}
    ports = {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18000"}]}
    state = dict(endpoint="unix:///var/run/docker.sock", labels=labels, ports=ports, ids="a" * 64,
                 image="sha256:" + "b" * 64, running="false", status="exited")
    if mutations:
        mutations(state)
    calls = []
    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs["shell"] is False
        command = argv[3:] if argv[1] == "--host" else argv[1:]
        if command[0] == "context":
            stdout = state["endpoint"]
        elif command[0] == "info":
            stdout = "engine-1"
        elif command[0] == "ps":
            stdout = state["ids"]
        elif command[0] == "inspect":
            stdout = "\n".join([json.dumps(state["labels"]), json.dumps(state["ports"]), state["image"],
                                state["running"], state["status"], "false", "false", "false"])
        else:
            assert command == ["start", "a" * 64]
            stdout = "secret-sentinel"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="secret-sentinel")
    return runner, calls


@pytest.fixture
def docker_env(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr("workbench.a_docker.find_docker", lambda: "docker")


def test_docker_start_pins_endpoint_identity_and_fixed_argv_without_logs(docker_env):
    runner, calls = docker_runner()
    backend = DockerTarget(runner)
    identity = backend.inspect().identity
    backend.start(identity)
    assert calls[-1][0] == ["docker", "--host", "unix:///var/run/docker.sock", "start", "a" * 64]
    commands = json.dumps([call[0] for call in calls])
    assert "Config.Env" not in commands and "Health" not in commands and "logs" not in commands
    assert "Cmd" not in commands and "Config.Labels" in commands


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(endpoint="tcp://127.0.0.1:2375"),
    lambda s: s.update(ids="a" * 64 + "\n" + "b" * 64),
    lambda s: s["labels"].update({"com.docker.compose.project.working_dir": str(ROOT.parent)}),
    lambda s: s["labels"].update({"com.docker.compose.project.config_files": str(ROOT / "other.yml")}),
    lambda s: s["labels"].update({"com.docker.compose.oneoff": "True"}),
    lambda s: s.update(ports={"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18000"}]}),
    lambda s: s.update(running="true", status="exited"),
])
def test_docker_rejects_wrong_or_ambiguous_ownership(docker_env, mutate):
    runner, calls = docker_runner(mutate)
    with pytest.raises(TargetError):
        DockerTarget(runner).inspect()
    assert all("start" not in call[0] for call in calls)


def test_docker_timeout_never_propagates_raw_output(docker_env):
    def runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 2, output="secret-sentinel")
    with pytest.raises(TargetError, match="docker_timeout_state_uncertain") as exc:
        DockerTarget(runner).inspect()
    assert "secret-sentinel" not in str(exc.value)


def test_docker_rechecks_exact_container_before_start(docker_env):
    runner, calls = docker_runner()
    backend = DockerTarget(runner)
    expected = backend.inspect().identity
    with pytest.raises(TargetError, match="target_changed_or_not_stopped"):
        backend.start(replace(expected, container_id="d" * 64))
    assert all("start" not in call[0] for call in calls)


def test_offline_delivery_examples_have_valid_shared_contracts_and_links():
    examples = json.loads((ROOT / "workbench/a_examples.json").read_text(encoding="utf-8"))
    assert examples["mode"] == "offline_fixture" and examples["real_execution"] is False
    for value in examples["observations"].values():
        validate_shared("observation", value)
        assert value["source"] == "offline_fixture" and value["real_observation"] is False
    validate_shared("recovery_action", examples["recovery_action"])
    for value in examples["recovery_results"].values():
        validate_shared("recovery_result", value)
        assert value["real_execution"] is False
    assert (examples["recovery_results"]["success"]["post_observation_id"] ==
            examples["observations"]["post_recovery"]["observation_id"])


def test_live_docker_boundary_rejects_injected_confirmation_adapter(setup, docker_env, tmp_path):
    monitor, _, _ = setup
    running, calls = docker_runner(lambda state: state.update(running="true", status="running"))
    monitor.backend = DockerTarget(running)
    active(monitor)
    stopped, stopped_calls = docker_runner()
    monitor.backend = DockerTarget(stopped)
    tool, request = RecoveryTool(monitor), action()
    gate = AuthorizationGate(tmp_path / "gate.sqlite3", confirm=lambda request, challenge: challenge)
    grant = gate.request("recovery", tool.prepare(request))
    assert tool.execute(request, gate=gate, grant=grant)["execution_status"] == "rejected"
    assert all("start" not in call[0] for call in calls + stopped_calls)


@pytest.mark.parametrize("mode", ["healthy", "business_503", "invalid_200", "timeout", "redirect", "oversize"])
def test_real_http_probe_logic_with_mock_transport(mode):
    calls = []
    def reply(code, body=None, *, headers=None, content=None):
        return httpx.Response(code, headers=headers,
                              stream=httpx.ByteStream(json.dumps(body).encode() if content is None else content))
    def handler(request):
        calls.append(request)
        assert request.url.host == "127.0.0.1" and request.url.port == 18000
        if request.url.path == "/health/live":
            return reply(200, {"status": "healthy"})
        if mode == "timeout":
            raise httpx.ReadTimeout("secret-sentinel")
        if mode == "redirect":
            return reply(302, headers={"Location": "https://example.com"})
        if mode == "business_503":
            return reply(503, {"secret-sentinel": "do not propagate"})
        if mode == "invalid_200":
            return reply(200, {"wrong": True})
        if mode == "oversize":
            return reply(200, content=b"x" * 20000)
        return reply(200, {"users": [{"id": 1, "name": "demo"}]})
    result = HttpProbe(httpx.MockTransport(handler)).read("trace-test")
    assert len(calls) == 2 and result[0] is True
    assert result[2] is (True if mode == "healthy" else None if mode == "timeout" else False)
    assert "secret-sentinel" not in str(result)
