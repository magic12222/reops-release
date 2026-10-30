"""网页授权、持续策略与恢复编排离线测试；不访问真实应用或 Docker。"""
import time
import json

from fastapi.testclient import TestClient
import pytest

from dashboard_api.vikunja_control import RECOVERY, VikunjaMonitorControl, install_vikunja_routes
from scripts.run_workbench_preview import create_app
from workbench.vikunja_automation import VikunjaAutomation
from workbench.vikunja_authorization import VikunjaPolicyGate
from reops_agent.authorization import AuthorizationError
from test_vikunja import active_monitor, action
from test_vikunja_authorization import binding
from test_workbench_control import headers


def healthy_monitor():
    monitor = active_monitor(stopped=False)
    monitor._thread.join = lambda timeout=None: None
    monitor._thread.is_alive = lambda: not monitor._closed
    monitor._generation = 1
    monitor.backend.sql_probe = lambda identity: True
    monitor.observe("incident-test", "trace-test")
    return monitor


def test_automatic_policy_requires_click_then_two_fresh_failures_and_deduplicates(tmp_path):
    monitor = healthy_monitor()
    automation = VikunjaAutomation(monitor, tmp_path)
    monitor.backend.stopped = True
    for _ in range(2):
        monitor.observe("incident-test", "trace-test")
        automation.tick()
    assert monitor.backend.started == 0
    monitor.backend.stopped = False
    monitor.observe("incident-test", "trace-test")
    offer = automation.status("owner")["offer_id"]
    with pytest.raises(ValueError):
        automation.enable("other", offer)
    automation.enable("owner", offer)
    monitor.backend.stopped = True
    monitor.observe("incident-test", "trace-test")
    automation.tick(); automation.tick()
    assert monitor.backend.started == 0
    monitor.observe("incident-test", "trace-test")
    automation.tick()
    assert monitor.backend.started == 1
    assert automation.actions == 1 and automation.active
    assert automation.events[-1]["event"] == "recovery_verified"
    names = [event["event"] for event in automation.events]
    stages = ["fault_confirmed", "recovery_started", "database_started", "verification_started", "recovery_verified"]
    assert [names.index(stage) for stage in stages] == sorted(names.index(stage) for stage in stages)
    checks = [event for event in automation.events if event["event"] == "verification_passed"]
    assert [event["check"] for event in checks] == [1, 2]
    assert len({event["observation_id"] for event in checks}) == 2
    automation.tick()
    assert monitor.backend.started == 1
    assert "target_policy_browser_approval" not in str(automation.status())  # 不暴露能力或Grant。


@pytest.mark.parametrize("reason", ["expired", "paused", "scope_changed", "budget"])
def test_policy_bounds_prevent_automatic_mutation(tmp_path, reason):
    clock = [0.0]
    monitor = healthy_monitor()
    automation = VikunjaAutomation(monitor, tmp_path, clock=lambda: clock[0])
    automation.enable("owner", automation.status("owner")["offer_id"])
    if reason == "expired": clock[0] = 8 * 3600 + 1
    elif reason == "paused": monitor._watching = False
    elif reason == "scope_changed": monitor._generation += 1
    else: automation.actions = 3
    monitor.backend.stopped = True
    for _ in range(2):
        monitor.observe("incident-test", "trace-test")
        automation.tick()
    assert monitor.backend.started == 0 and not automation.active


def test_policy_never_grants_fault_injection_or_models(tmp_path):
    monitor = healthy_monitor()
    gate = VikunjaPolicyGate(tmp_path / "auth.sqlite3", VikunjaAutomation(monitor, tmp_path))
    for purpose in ("experiment", "model"):
        with pytest.raises(AuthorizationError): gate.request(purpose, {})


def test_last_budgeted_recovery_verifies_then_disables_policy(tmp_path):
    monitor = healthy_monitor()
    automation = VikunjaAutomation(monitor, tmp_path)
    automation.enable("owner", automation.status("owner")["offer_id"])
    automation.actions = 2
    monitor.backend.stopped = True
    for _ in range(2):
        monitor.observe("incident-test", "trace-test")
        automation.tick()
    assert monitor.backend.started == 1 and automation.actions == 3
    assert not automation.active and automation.state == "budget_exhausted"
    assert automation.events[-2]["event"] == "recovery_verified"


def test_failed_verify_disables_policy_without_repeated_recovery(tmp_path):
    monitor = healthy_monitor()
    automation = VikunjaAutomation(monitor, tmp_path)
    automation.enable("owner", automation.status("owner")["offer_id"])
    monitor.backend.sql_probe = lambda identity: False
    monitor.backend.stopped = True
    for _ in range(3):
        monitor.observe("incident-test", "trace-test")
        automation.tick()
    assert monitor.backend.started == 1
    assert not automation.active and automation.state == "attention"
    assert "recovery_verified" not in [event["event"] for event in automation.events]
    assert "verification_passed" not in [event["event"] for event in automation.events]


@pytest.fixture
def web(tmp_path):
    monitor = healthy_monitor()
    # The worker has no policy approval, so it performs no recovery in these route tests.
    def runner(*, backend, gate):
        data = binding()
        grant = gate.request("experiment", data)
        proof = gate.consume(grant, "experiment", data, operation_id="fixture-stop")
        assert proof["source"] == "single_run_browser_approval"
        return {"passed": True, "fault_injection_attempted": False, "model_calls": 0}
    control = VikunjaMonitorControl(monitor, directory=tmp_path, runner=runner)
    app = create_app(control=control)
    install_vikunja_routes(app, control)
    with TestClient(app, base_url="http://127.0.0.1:8021", client=("127.0.0.1",1234)) as client:
        yield client, control, monitor


def wait_pending(client):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        state = client.get(RECOVERY + "/status").json()
        if state["demo"] and state["demo"]["pending"]:
            return state["demo"]
        time.sleep(.01)
    raise AssertionError("no pending confirmation")


def test_browser_demo_needs_one_click_not_typed_challenge_and_is_session_bound(web):
    client, control, monitor = web
    h = headers(client)
    assert client.post(RECOVERY + "/demo", headers=h, json={}).status_code == 200
    job = wait_pending(client)
    assert "challenge" not in job["pending"]
    assert job["pending"]["request"]["authorization_mode"] == "single_run"
    assert monitor.backend.started == 0
    payload = {"approved": True, "job_id": job["id"], "confirmation_id": job["pending"]["id"]}
    assert client.post(RECOVERY + "/approve", headers=h, json=payload | {"approved": False}).status_code == 422
    client.cookies.clear()
    other = headers(client)
    assert client.post(RECOVERY + "/approve", headers=other, json=payload).status_code == 409
    # Restore the original browser session, not a transferable approval.
    owner = control.recovery.jobs[job["id"]]["owner"]
    client.cookies.set("reops_workbench_ui", owner, path="/api/v1/workbench/control")
    assert client.post(RECOVERY + "/approve", headers=h, json=payload).status_code == 200
    control.recovery.jobs[job["id"]]["thread"].join(timeout=2)
    assert client.get(RECOVERY + "/status").json()["demo"]["result"]["passed"]
    assert client.post(RECOVERY + "/approve", headers=h, json=payload).status_code == 409


@pytest.mark.parametrize("extra", [{"Origin":"https://evil.invalid"}, {"Host":"evil.invalid"},
    {"Sec-Fetch-Site":"cross-site"}, {"X-ReOps-Monitor-Token":"wrong"}])
def test_browser_policy_rejects_cross_origin_before_recovery(web, extra):
    client, _, monitor = web
    h = headers(client) | extra
    assert client.post(RECOVERY + "/enable", headers=h, json={"approved":True,"offer_id":"anything"}).status_code == 403
    assert monitor.backend.started == 0


def test_fixed_policy_requires_explicit_click_and_revoke_preserves_monitoring(web):
    client, control, monitor = web
    h = headers(client)
    state = client.get(RECOVERY + "/status").json()
    assert not control.recovery.automation.active
    data = {"approved":True,"offer_id":state["automation"]["offer_id"]}
    assert client.post(RECOVERY + "/enable", headers=h, json=data | {"max_actions":100}).status_code == 422
    assert client.post(RECOVERY + "/enable", headers=h, json=data).status_code == 200
    assert control.recovery.automation.active
    assert client.post(RECOVERY + "/demo", headers=h, json={}).status_code == 409
    assert client.post(RECOVERY + "/disable", headers=h, json={}).status_code == 200
    assert monitor._watching
    assert monitor.backend.started == 0


@pytest.mark.parametrize("with_b", [False, True])
def test_browser_click_runs_complete_real_orchestration_with_only_offline_io(tmp_path, monkeypatch, with_b):
    import scripts.run_vikunja_acceptance as module
    monitor = healthy_monitor()
    backend = monitor.backend
    backend.stops = 0
    def stop(args, **kwargs):
        assert args[:3] == ["stop", "--time", "5"]
        assert args[3] == backend.identity.postgres_id
        backend.stopped = True
        backend.stops += 1
    backend._run = stop
    backend.sql_probe = lambda identity: not backend.stopped
    class Business:
        project_id, task_id = 1, 2
        probe_id = probe_title = None
        def read(self): return (None, False) if backend.stopped else (200, True)
        def read_observation(self): return (*self.read(), "read_timeout" if backend.stopped else None)
        def write_probe(self): self.probe_id = 3; return not backend.stopped
        def read_probe(self): return self.probe_id == 3 and not backend.stopped
        def close(self): pass
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "BusinessSession", Business)
    monkeypatch.setattr(module, "baseline", lambda session: {"passed":True})
    control = VikunjaMonitorControl(monitor, directory=tmp_path / "web")
    if with_b:
        from workbench.b_store import BStore
        control.recovery.b_store = BStore(tmp_path / "b-state.sqlite3", source="offline_fixture")
    app = create_app(control=control)
    install_vikunja_routes(app, control)
    with TestClient(app, base_url="http://127.0.0.1:8021", client=("127.0.0.1",1234)) as client:
        h = headers(client)
        assert client.post(RECOVERY + "/demo", headers=h, json={}).status_code == 200
        job = wait_pending(client)
        assert backend.stops == backend.started == 0
        assert client.post(RECOVERY + "/approve", headers=h, json={"approved":True,
            "job_id":job["id"],"confirmation_id":job["pending"]["id"]}).status_code == 200
        control.recovery.jobs[job["id"]]["thread"].join(timeout=10)
        status = client.get(RECOVERY + "/status").json()
        assert status["demo"]["result"]["passed"] is True
        assert status["demo"]["pending"] is None
        assert backend.stops == backend.started == 1
        report = json.loads(next((tmp_path / "runtime/vikunja-evidence").glob("*/report.json")).read_text())
        assert report["run_authorization"]["source"] == "single_run_browser_approval"
        assert report["recovery_verified"] and report["cleanup_extra_starts"] == 0
        assert report["b_agent_closed_loop"] is with_b
        if with_b:
            from workbench.b_store import read_feed
            feed = read_feed(control.recovery.b_store.path, allow_fixture=True)
            assert feed.incidents[0].trace_id == report["trace_id"]
            assert feed.incidents[0].status == "recovered"
            assert feed.experiences[0].status == "verified"
