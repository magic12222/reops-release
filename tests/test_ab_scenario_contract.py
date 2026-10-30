"""接手 A-02 的离线跨模块回归；无 Docker/HTTP 网络或真实模型。"""

import json
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from infra.monitoring.observer import Observer
from reops_agent import MockRCAProvider, RecoveryMemory, recover
from reops_agent.advisory import structured_observation
from reops_agent.contracts import validate
from reops_agent.pipeline import diagnose
from reops_agent.planner import plan_recovery
from reops_agent.rca import RCAAgent
from reops_agent.safety import check_action
from reops_agent.strategies import plan_candidates, check_offline_action
from reops_agent.verification import verify
from tools.system_tools import ROOT, SystemTools


class FixtureTools:
    def __init__(self, running=None, transitions=None):
        self.running = {name: 1 for name in ("api", "postgres", "redis")} if running is None else running
        self.transitions = transitions or {}
        self.samples = {}

    def get_logs(self, name, tail):
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    def get_service_liveness(self, name):
        count = self.samples.get(name, 0)
        self.samples[name] = count + 1
        up = self.transitions.get(name, self.running.get(name)) if count else self.running.get(name)
        return {"up": up, "source": "docker_state", "identity_confirmed": up is not None,
                "container_id": {"api": "a", "postgres": "b", "redis": "c"}[name] * 64}


def observe(*, tools=None, dependencies=None, live=200, users=200, fail=None, malformed=None):
    dependencies = {"postgres": "healthy", "redis": "healthy"} if dependencies is None else dependencies
    def handle(request):
        if request.url.path == fail or fail == "all":
            raise httpx.ConnectError("offline fixture", request=request)
        if request.url.path == "/health/live":
            return httpx.Response(live)
        if request.url.path == "/health":
            return httpx.Response(200, json=malformed if malformed is not None else {"services": {
                name: {"status": status, "message": "stopped"} for name, status in dependencies.items()}})
        return httpx.Response(users, json={"step": "database_query", "error_type": "OperationalError"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        value = Observer(tools or FixtureTools(), client=client).observe("incident-ab", "trace-ab", "case-ab")
    validate("observation", value)
    return value


def test_password_failure_is_not_postgres_stop_or_configuration_recovery():
    value = observe(dependencies={"postgres": "degraded", "redis": "healthy"}, users=503)
    assert value["metrics"]["postgres_up"] == 1
    diagnosis = diagnose(value)
    assert diagnosis["failure_type"] == "health_check_failure"
    assert diagnosis["root_cause"] != "postgres_service_down"
    assert plan_recovery(diagnosis, observation=value)["action"] == "no_action"
    rca = RCAAgent(MockRCAProvider()).analyze(value, diagnosis, [])
    selected = plan_candidates(diagnosis, value, rca=rca, mode="reops")
    assert selected["action"] not in {"start_service", "reconfigure"}
    # 即便离线模型给建议，健康探针不构成该模型根因成立的证明。
    assert value["services"]["postgres"]["message"] != "stopped"


@pytest.mark.parametrize("tools", (FixtureTools(running={}), SimpleNamespace(
    get_logs=lambda *args, **kwargs: {"exit_code": 0, "stdout": "", "stderr": ""})))
def test_probe_only_unreachable_does_not_make_stop_evidence(tools):
    value = observe(tools=tools, fail="all")
    assert all(value["metrics"][name + "_up"] is None for name in ("api", "postgres", "redis"))
    assert value["services"]["postgres"]["status"] == "unknown"
    assert diagnose(value)["root_cause"] != "api_service_down"


@pytest.mark.parametrize("component", ("api", "postgres", "redis"))
def test_confirmed_target_stop_requires_independent_samples(component):
    running = {name: int(name != component) for name in ("api", "postgres", "redis")}
    tools = FixtureTools(running)
    value = observe(tools=tools, fail="all" if component == "api" else None,
        dependencies={"postgres": "unhealthy" if component == "postgres" else "healthy",
                      "redis": "unhealthy" if component == "redis" else "healthy"}, users=503)
    assert value["metrics"][component + "_up"] == 0
    assert diagnose(value)["root_cause"] == component + "_service_down"
    assert tools.samples == {"api": 2, "postgres": 2, "redis": 2}


@pytest.mark.parametrize("malformed", ([], {"services": []}, {"services": {"postgres": None}},
    {"services": {"postgres": {"status": "stopped"}}}, {"services": {"postgres": {"status": []}}}))
def test_invalid_dependency_probe_stays_unknown(malformed):
    value = observe(malformed=malformed, users=503)
    assert value["services"]["postgres"]["status"] == "unknown"
    assert value["metrics"]["postgres_up"] == 1  # 存活仍由独立 Docker 替身给出。


def test_dependency_unavailable_does_not_erase_successful_live_probe():
    value = observe(fail="/health", users=503)
    assert value["services"]["api"]["status"] == "healthy"
    assert value["services"]["postgres"]["status"] == "unknown"
    assert diagnose(value)["root_cause"] == "request_failed_cause_unknown"


@pytest.mark.parametrize("up", (True, False, 2, "0"))
def test_invalid_liveness_does_not_become_zero(up):
    tools = FixtureTools()
    tools.get_service_liveness = lambda name: {"up": up, "source": "docker_state",
        "identity_confirmed": True, "container_id": "a" * 64}
    value = observe(tools=tools, fail="all")
    assert all(value["metrics"][name + "_up"] is None for name in ("api", "postgres", "redis"))


def test_container_replacement_is_a_conflict_even_if_running_stays_true():
    tools = FixtureTools()
    original = tools.get_service_liveness
    def sample(name):
        value = original(name)
        if name == "api" and tools.samples[name] == 2:
            value["container_id"] = "d" * 64
        return value
    tools.get_service_liveness = sample
    value = observe(tools=tools)
    assert value["metrics"]["api_up"] is None
    assert value["observation_conflicts"] == ["api:liveness_samples_disagree"]


def test_probe_authentication_failure_is_not_stop_evidence():
    value = observe(tools=FixtureTools(running={}), live=401, users=401)
    assert value["metrics"]["api_up"] is None
    assert diagnose(value)["root_cause"] != "api_service_down"


def test_conflicting_healthy_observation_cannot_execute_generic_recover(tmp_path):
    value = observe(tools=FixtureTools(running={"api": 0, "postgres": 1, "redis": 1}))
    def forbidden(*args, **kwargs):
        raise AssertionError("conflict must not execute")
    result = recover(value, executor=forbidden, rca_agent=RCAAgent(MockRCAProvider()),
                     memory=RecoveryMemory(tmp_path / "memory.jsonl"))
    assert result["recovery_action"]["action"] == "no_action"
    assert result["recovered"] is False


@pytest.mark.parametrize("changes", (
    {"live": 500},
    {"tools": FixtureTools(running={"api": 0, "postgres": 1, "redis": 1})},
    {"tools": FixtureTools(transitions={"api": 0})},
))
def test_conflicts_survive_bounding_and_block_planner_safety_verify(changes):
    value = observe(**changes)
    assert value["observation_conflicts"]
    if changes.get("tools"):
        assert value["metrics"]["api_up"] is None
    bounded = structured_observation(value)
    assert bounded["observation_conflicts"]
    for snapshot in (value, bounded):
        diagnosis = diagnose(snapshot)
        assert diagnosis["root_cause"] == "observation_conflict_reobserve_required"
        rca = RCAAgent(MockRCAProvider()).analyze(snapshot, diagnosis, [])
        action = plan_recovery(diagnosis, observation=snapshot, rca_result=rca["result"])
        assert action["action"] == "no_action"
        action.update(action="restart_service", target="web", expected_success=.8, risk=.2)
        assert check_action(action, snapshot)["reason"] == "observation_conflict"
        assert check_offline_action(action, snapshot)["reason"] == "observation_conflict"
        action.update(action="start_service")
        assert not check_offline_action(action, snapshot)["allowed"]
        action.update(action="reconfigure", target="api", parameters={"profile": "normal"})
        assert not check_offline_action(action, snapshot)["allowed"]
        assert verify(snapshot)[2] is False
        chosen = plan_candidates(diagnosis, snapshot, rca=rca, mode="reops")
        assert chosen["action"] == "retry"


def state_payload(**updates):
    value = {"id": "a" * 64, "project": "reops-lab", "service": "api", "oneoff": "False",
             "directory": str(ROOT), "config": str(ROOT / "docker-compose.yml"),
             "running": True, "status": "running"}
    value.update(updates)
    return value


def make_tools(monkeypatch, payload=None, ids=None, endpoint="npipe:////./pipe/docker_engine", failure=None):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr("tools.system_tools.find_docker", lambda: "offline-docker")
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        assert kwargs["shell"] is False and kwargs["cwd"] == ROOT
        assert command[1] in {"context", "ps", "inspect"}
        if failure:
            raise failure
        stdout = endpoint if command[1] == "context" else ("a" * 64 if ids is None else ids) if command[1] == "ps" else json.dumps(payload or state_payload())
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return SystemTools(runner), calls


@pytest.mark.parametrize("running,status,expected", ((True,"running",1), (False,"exited",0),
    (False,"dead",0), (False,"created",None), (True,"restarting",None), (True,"paused",None),
    (0,"exited",None), (1,"running",None), (True,"exited",None)))
def test_docker_state_types_and_transitional_states(monkeypatch, running, status, expected):
    tools, calls = make_tools(monkeypatch, state_payload(running=running,status=status))
    value = tools.get_service_liveness("api")
    assert value["up"] == expected and value["identity_confirmed"] is True
    assert len(calls) == 3 and ".Config.Env" not in calls[-1][3]


@pytest.mark.parametrize("updates", ({"id":"b"*64}, {"project":"other"}, {"service":"postgres"},
    {"oneoff":"True"}, {"directory":str(ROOT.parent)}, {"directory":""},
    {"config":str(ROOT.parent/"docker-compose.yml")}, {"config":"one,two"}, {"config":""}))
def test_same_name_foreign_container_is_not_liveness_evidence(monkeypatch, updates):
    tools, _ = make_tools(monkeypatch, state_payload(**updates))
    value = tools.get_service_liveness("api")
    assert value["up"] is None and value["identity_confirmed"] is False
    assert value["reason"] == "target_identity_mismatch"


@pytest.mark.parametrize("ids", ("", "a"*12, "a"*64+"\n"+"b"*64, "not-an-id"))
def test_missing_ambiguous_or_short_ids_are_unknown(monkeypatch, ids):
    tools, calls = make_tools(monkeypatch, ids=ids)
    assert tools.get_service_liveness("api")["up"] is None and len(calls)==2


@pytest.mark.parametrize("endpoint", ("tcp://127.0.0.1:2375", "npipe:////remote/pipe/docker_engine"))
def test_remote_engine_never_provides_target_liveness(monkeypatch, endpoint):
    tools, calls = make_tools(monkeypatch, endpoint=endpoint)
    assert tools.get_service_liveness("api")["reason"] == "remote_docker_forbidden"
    assert len(calls)==1
    monkeypatch.setenv("DOCKER_HOST", endpoint)
    tools.get_service_liveness("api")
    assert len(calls)==1


@pytest.mark.parametrize("failure", (OSError("must-not-escape"), subprocess.TimeoutExpired("fixture",10)))
def test_missing_engine_and_timeout_preserve_null_without_error_text(monkeypatch, failure):
    tools, _ = make_tools(monkeypatch, failure=failure)
    value=tools.get_service_liveness("api")
    assert value["up"] is None and "must-not-escape" not in json.dumps(value)


def test_no_docker_cli_is_unknown_and_never_starts_process(monkeypatch):
    tools, calls = make_tools(monkeypatch)
    monkeypatch.setattr("tools.system_tools.find_docker", lambda: None)
    assert tools.get_service_liveness("api")["up"] is None and not calls
