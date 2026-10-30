"""单次范围批准离线验收，业务、模型与 Docker 均为替身。"""
from copy import deepcopy
import json
import sqlite3

import pytest

from dashboard_api.run_authorization import RunGate
from dashboard_api.web_control import WebControl
from reops_agent.authorization import AuthorizationError
from test_web_control import PREFIX, client, headers, model, wait
from test_researchloop_recovery import Backend, Provider


class Consent:
    cancelled = False

    def __init__(self):
        self.requests = []

    def __call__(self, request, challenge):
        self.requests.append(request)
        return challenge  # 仅离线替身，非网页真人批准。


def setup_gate(tmp_path, clock=None):
    confirm = Consent()
    context = {"incident_id": "incident-test", "trace_id": "trace-test"}
    binding = {**context, "scope": {"target": "isolated-postgres"}, "business": {"project": "test"},
               "fault": "stop_postgres_once", "cleanup": "at_most_one_fixed_postgres_restart_if_stopped"}
    gate = RunGate(tmp_path / "auth.sqlite3", confirm=confirm, context=context, model_digest="bound-model", clock=clock)
    return gate, confirm, binding


def model_binding(binding):
    return {key: deepcopy(binding[key]) for key in ("incident_id", "trace_id", "scope")} | {
        "input": "bounded_structured_observation", "max_calls": 1, "max_output_tokens": 512,
        "model_identifier_sha256": "bound-model"}


def test_only_one_consent_and_each_capability_consumed_once(tmp_path):
    gate, confirm, binding = setup_gate(tmp_path)
    experiment = gate.request("experiment", binding)
    gate.consume(experiment, "experiment", binding, operation_id="exp")
    model_data = model_binding(binding)
    grant = gate.request("model", model_data)
    proof = gate.consume(grant, "model", model_data, operation_id="model")
    assert len(confirm.requests) == 1
    assert confirm.requests[0]["authorization_mode"] == "single_run"
    assert proof["source"] == "single_run_browser_approval"
    with pytest.raises(AuthorizationError):
        gate.consume(grant, "model", model_data, operation_id="model-again")
    with pytest.raises(AuthorizationError):
        gate.request("model", model_data)


@pytest.mark.parametrize("field,value", [("scope", {"other": "target"}), ("trace_id", "other"),
    ("model_identifier_sha256", "new-service"), ("max_calls", 2), ("max_output_tokens", 513)])
def test_scope_or_budget_cannot_expand_after_approval(tmp_path, field, value):
    gate, _, binding = setup_gate(tmp_path)
    gate.request("experiment", binding)
    changed = model_binding(binding)
    changed[field] = value
    with pytest.raises(AuthorizationError):
        gate.request("model", changed)


@pytest.mark.parametrize("cancel", [False, True])
def test_cancel_and_expiry_stop_derived_operations(tmp_path, cancel):
    clock = [10.0]
    gate, confirm, binding = setup_gate(tmp_path, clock=lambda: clock[0])
    gate.request("experiment", binding)
    if cancel:
        confirm.cancelled = True
    else:
        clock[0] = 311.0
    with pytest.raises(AuthorizationError):
        gate.request("model", model_binding(binding))


def test_http_whole_pipeline_needs_one_approval_only(tmp_path, monkeypatch):
    import dashboard_api.web_control as module
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    backend, provider = Backend(), Provider()
    backend.business.close = lambda: None
    monkeypatch.setattr(module, "BusinessSession", lambda: backend.business)
    monkeypatch.setattr(module, "ResearchLoopBackend", lambda business: backend)
    monkeypatch.setattr(module, "NexentRCAProvider", lambda config: provider)
    control = WebControl(tmp_path / "c.sqlite3", enabled=True, model=model())
    c, _ = client(tmp_path, control)
    h = headers(c)
    first = c.post(PREFIX + "/runs", headers=h, json={"strategy": "model"})
    assert first.status_code == 200
    job = first.json()
    pending = wait(c, lambda value: value["job"]["confirmation"] is not None)["job"]["confirmation"]
    assert pending["request"]["authorization_mode"] == "single_run"
    assert backend.operations == [] and provider.calls == 0
    other, _ = client(tmp_path, control)
    assert other.post(PREFIX + "/runs/" + job["id"] + "/approve", headers=headers(other),
        json={"confirmation_id": pending["id"], "approved": True}).status_code == 409
    assert c.post(PREFIX + "/runs/" + job["id"] + "/approve", headers=h,
        json={"confirmation_id": pending["id"], "approved": False}).status_code == 422
    assert c.post(PREFIX + "/runs/" + job["id"] + "/approve", headers=h,
        json={"confirmation_id": pending["id"], "approved": True}).status_code == 200
    final = wait(c, lambda value: value["job"]["state"] == "finished")
    assert final["job"]["result"] == "passed"
    assert final["job"]["confirmation"] is None
    assert backend.operations == ["stop", "restart"] and backend.running and provider.calls == 1
    report = json.loads((tmp_path / "runtime/researchloop-evidence" / job["trace_id"] / "report.json").read_text(encoding="utf-8"))
    assert report["acceptance_passed"] is True
    with sqlite3.connect(tmp_path / "runtime/researchloop-authorizations.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM reservations").fetchone()[0] == 3
    assert c.post(PREFIX + "/runs/" + job["id"] + "/approve", headers=h,
        json={"confirmation_id": pending["id"], "approved": True}).status_code == 409
