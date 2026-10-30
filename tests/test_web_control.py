"""网页输入通道离线验收：原Gate/原DB编排，Docker、模型及业务均为替身。"""
from copy import copy
import json
from threading import Event, Thread
import time

from fastapi.testclient import TestClient
import httpx
import pytest

from dashboard_api.api import create_app
from dashboard_api.store import Store
from dashboard_api.web_control import BrowserConfirmation, BrowserGate, WebControl
from dashboard_api.web_model import WebModel, MODEL, BASE
from reops_agent.nexent_provider import NexentConfig
from reops_agent.authorization import AuthorizationError
from test_researchloop_recovery import Backend, Provider

ORIGIN = {"Origin": "http://127.0.0.1:5173"}
PREFIX = "/api/v1/researchloop/control"
SECRET = "fixture-key-never-returned"


def model():
    result = WebModel(NexentConfig(BASE, MODEL, SECRET, max_output_tokens=512, allow_dlut_http=True))
    result.verified = True
    return result


def client(tmp_path, control=None):
    store = Store(tmp_path / "c.sqlite3")
    control = control or WebControl(store.path, enabled=True, model=model(), runner=lambda *_: {"result": "passed"})
    app = create_app(store=store, web_control=control)
    return TestClient(app, base_url="http://127.0.0.1:8020", client=("127.0.0.1", 50000)), control


def headers(c):
    status = c.get(PREFIX + "/status")
    assert status.status_code == 200
    assert "HttpOnly" in status.headers["set-cookie"] and "SameSite=strict" in status.headers["set-cookie"]
    return {**ORIGIN, "X-ReOps-UI-Token": status.json()["csrf"]}


def test_api_configuration_supports_workbench_origin_without_widening_csrf(tmp_path):
    c,control=client(tmp_path)
    with c:
        state=c.get(PREFIX+'/status',headers={'Host':'127.0.0.1:5174'})
        assert state.status_code==200
        response=c.post(PREFIX+'/model/verify',headers={'Host':'127.0.0.1:5174','Origin':'http://127.0.0.1:5174'},json={})
        assert response.status_code==403  # Missing CSRF remains rejected before model IO.
        control.verify=lambda:{'verified':True}  # Offline route substitute, no gateway call.
        response=c.post(PREFIX+'/model/verify',headers={'Host':'127.0.0.1:5174','Origin':'http://127.0.0.1:5174','X-ReOps-UI-Token':state.json()['csrf']},json={})
        assert response.status_code==200
        assert c.get(PREFIX+'/status',headers={'Host':'evil.invalid:5174'}).status_code==403


def wait(c, predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        status = c.get(PREFIX + "/status").json()
        if predicate(status):
            return status
        time.sleep(.005)
    raise AssertionError("offline_worker_did_not_reach_expected_state")


def test_model_key_is_memory_only_no_echo_or_error_input(tmp_path, caplog):
    c, control = client(tmp_path)
    h = headers(c)
    before = set(tmp_path.rglob("*"))
    response = c.put(PREFIX + "/model", headers=h, json={"api_key": SECRET})
    assert response.status_code == 200 and response.json()["configured"]
    assert response.json()["verified"] is False and SECRET not in response.text
    assert set(tmp_path.rglob("*")) == before
    bad = c.put(PREFIX + "/model", headers=h, json={"api_key": {"bad": SECRET}})
    assert bad.status_code == 409 and SECRET not in bad.text and "input" not in bad.text
    duplicate = c.put(PREFIX + "/model", headers={**h, "Content-Type": "application/json"},
                      content=json.dumps({"api_key": SECRET})[:-1] + ',"api_key":"other"}')
    assert duplicate.status_code == 422 and SECRET not in duplicate.text
    assert SECRET not in caplog.text


@pytest.mark.parametrize("extra", [{"Origin": "https://evil.invalid"}, {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}, {"Host": "evil.invalid:8020"},
    {"X-ReOps-UI-Token": "wrong"}])
def test_writes_require_same_origin_host_and_browser_session(tmp_path, extra):
    c, control = client(tmp_path)
    h = headers(c)
    response = c.put(PREFIX + "/model", headers={**h, **extra}, json={"api_key": SECRET})
    assert response.status_code == 403
    assert control.model.verified is True


def test_missing_cookie_or_origin_and_disabled_entry_reject(tmp_path):
    c, control = client(tmp_path)
    h = headers(c)
    assert c.put(PREFIX + "/model", headers={"X-ReOps-UI-Token": h["X-ReOps-UI-Token"]}, json={"api_key": SECRET}).status_code == 403
    c.cookies.clear()
    assert c.put(PREFIX + "/model", headers=h, json={"api_key": SECRET}).status_code == 403
    control.enabled = False
    h = headers(c)
    assert c.post(PREFIX + "/jobs", headers=h, json={"strategy": "model"}).status_code == 403


def test_verification_uses_only_fixed_models_endpoint_and_never_infers(monkeypatch):
    value = model()
    calls = []
    def handle(request):
        calls.append((request.method, str(request.url)))
        assert request.headers["authorization"] == "Bearer " + SECRET
        return httpx.Response(200, json={"data": [{"id": MODEL}]})
    result = value.verify(httpx.MockTransport(handle))
    assert calls == [("GET", BASE + "/models")]
    assert result["verified"] and result["inference_performed"] is False and SECRET not in json.dumps(result)
    with pytest.raises(ValueError, match="model_authentication_rejected"):
        value.verify(httpx.MockTransport(lambda request: httpx.Response(401, text=SECRET)))
    assert not value.verified
    checks = value.status()["checks"]
    assert len(checks) == 2 and checks[0]["success"] is True and checks[1]["success"] is False
    assert all(row["duration_ms"] >= 0 and row["request_type"] == "GET /models" for row in checks)
    assert SECRET not in json.dumps(checks)
    assert checks[1]["error"] == "model_authentication_rejected"
    checks[0]["error"] = "caller-mutation"
    assert value.status()["checks"][0]["error"] is None


def test_browser_input_is_original_text_and_original_gate_still_binds_once(tmp_path):
    confirm = BrowserConfirmation(timeout=1)
    gate = BrowserGate(tmp_path / "grant.sqlite3", confirm=confirm)
    binding = {"incident_id": "fixture", "trace_id": "fixture", "action": "restart_service", "target": "postgres"}
    grants = []
    worker = Thread(target=lambda: grants.append(gate.request("recovery", binding)))
    worker.start()
    deadline = time.monotonic() + 1
    while confirm.status() is None and time.monotonic() < deadline: time.sleep(.002)
    pending = confirm.status()
    with pytest.raises(ValueError, match="mismatch"):
        confirm.respond(pending["id"], "wrong")
    confirm.respond(pending["id"], pending["challenge"])
    with pytest.raises(ValueError):
        confirm.respond(pending["id"], pending["challenge"])
    worker.join(1)
    grant = grants[0]
    with pytest.raises(AuthorizationError):
        gate.consume(copy(grant), "recovery", binding, operation_id="fixture")
    with pytest.raises(AuthorizationError):
        gate.consume(grant, "recovery", {**binding, "target": "web"}, operation_id="fixture")
    proof = gate.consume(grant, "recovery", binding, operation_id="fixture")
    assert proof["source"] == "interactive_browser_confirmation"
    with pytest.raises(AuthorizationError):
        gate.consume(grant, "recovery", binding, operation_id="fixture")


def test_pending_confirmation_timeout_and_cancellation_do_not_approve():
    confirm = BrowserConfirmation(timeout=.01)
    assert confirm({"purpose": "experiment"}, "AUTHORIZE experiment fixture") is None
    assert confirm.status() is None
    confirm.cancel()
    assert confirm({"purpose": "experiment"}, "AUTHORIZE experiment fixture") is None


@pytest.mark.parametrize("cancel_recovery", [False, True])
def test_http_worker_runs_original_pipeline_and_cleanup_with_manual_fixture_replies(tmp_path, monkeypatch, cancel_recovery):
    import dashboard_api.web_control as module
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    backend, provider = Backend(), Provider()
    backend.business.close = lambda: None
    monkeypatch.setattr(module, "BusinessSession", lambda: backend.business)
    monkeypatch.setattr(module, "ResearchLoopBackend", lambda business: backend)
    monkeypatch.setattr(module, "NexentRCAProvider", lambda config: provider)
    control = WebControl(tmp_path / "c.sqlite3", enabled=True, model=model())
    c, control = client(tmp_path, control)
    h = headers(c)
    first = c.post(PREFIX + "/jobs", headers=h, json={"strategy": "model"}).json()
    again = c.post(PREFIX + "/jobs", headers=h, json={"strategy": "model"}).json()
    assert first["id"] == again["id"]
    purposes = []
    for purpose in ("experiment", "model", "recovery"):
        status = wait(c, lambda value: value["job"]["confirmation"] is not None)
        pending = status["job"]["confirmation"]
        assert pending["request"]["purpose"] == purpose
        purposes.append(purpose)
        if purpose == "recovery" and cancel_recovery:
            assert c.post(PREFIX + "/jobs/" + first["id"] + "/cancel", headers=h, json={}).status_code == 200
            break
        assert c.post(PREFIX + "/jobs/" + first["id"] + "/confirmation", headers=h,
            json={"confirmation_id": pending["id"], "answer": pending["challenge"]}).status_code == 200
        # 原pending已消费，测试不使用旧ID响应下一项。
        wait(c, lambda value: value["job"]["confirmation"] is None
             or value["job"]["confirmation"]["id"] != pending["id"])
    final = wait(c, lambda value: value["job"]["state"] == "finished")
    assert final["busy"] is False and backend.running
    assert final["job"]["result"] == ("failed" if cancel_recovery else "passed")
    assert backend.operations == ["stop", "restart"] and provider.calls == 1
    directory = tmp_path / "runtime/researchloop-evidence" / first["trace_id"]
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    assert report["recovery_verified"] is (not cancel_recovery)
    assert report["cleanup_extra_restarts"] == int(cancel_recovery)
    assert SECRET not in (directory / "report.json").read_text(encoding="utf-8")
    assert SECRET not in (directory / "request.json").read_text(encoding="utf-8")
    assert h["X-ReOps-UI-Token"] not in (directory / "request.json").read_text(encoding="utf-8")
    assert c.post(PREFIX + "/jobs/" + first["id"] + "/confirmation", headers=h,
        json={"confirmation_id": "old", "answer": "old"}).status_code == 409


def test_other_browser_cannot_answer_or_cancel_owner_job(tmp_path):
    entered = Event()
    def runner(job, config):
        entered.set()
        job["confirm"]({"purpose": "experiment"}, "AUTHORIZE experiment fixture")
        return {"result": "rejected"}
    control = WebControl(tmp_path / "c.sqlite3", enabled=True, model=model(), runner=runner)
    c, _ = client(tmp_path, control)
    h = headers(c)
    job = c.post(PREFIX + "/jobs", headers=h, json={"strategy": "model"}).json()
    assert entered.wait(1)
    other, _ = client(tmp_path, control)
    other_h = headers(other)
    assert other.post(PREFIX + "/jobs/" + job["id"] + "/cancel", headers=other_h, json={}).status_code == 409
    assert other.post(PREFIX + "/jobs", headers=other_h, json={"strategy": "model"}).status_code == 409
    assert c.post(PREFIX + "/jobs/" + job["id"] + "/cancel", headers=h, json={}).status_code == 200
    wait(c, lambda value: value["job"]["state"] == "finished")
