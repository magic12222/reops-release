"""一次真实批准的派生边界；仅使用离线替身。"""
from copy import deepcopy

import pytest

from reops_agent.authorization import AuthorizationError, interactive_confirm
from workbench.vikunja_authorization import VikunjaRunGate
from workbench.a_actions import RecoveryTool
from workbench.vikunja_actions import VikunjaRecoveryTool
from test_vikunja import IDENTITY, active_monitor, action


def binding():
    return {"scope": IDENTITY.binding(), "incident_id": "incident-test", "trace_id": "trace-test",
        "business": {"project_id": 1, "task_id": 2},
        "operation": "stop_postgres_for_connection_acceptance", "max_stops": 1,
        "max_recovery_starts": 1, "necessary_cleanup_max_starts": 1,
        "app_restart_allowed": False, "model_calls": 0,
        "authorization_mode": "single_run", "allowed_recovery": "start_service(postgres)"}


def setup(tmp_path, *, approve=True):
    calls = []
    clock = [100.0]
    def confirm(request, challenge):
        calls.append(deepcopy(request))
        return challenge if approve else None  # 离线批准替身，真实工具必须拒绝此回调。
    gate = VikunjaRunGate(tmp_path / "auth.sqlite3", confirm=confirm, clock=lambda: clock[0])
    monitor = active_monitor()
    monitor._generation = 1
    return gate, monitor, calls, clock


def approve_run(gate):
    data = binding()
    grant = gate.request("experiment", data)
    return gate.consume(grant, "experiment", data, operation_id="stop-once")


def test_one_confirmation_runs_recovery_with_original_single_use_ledger(tmp_path):
    gate, monitor, calls, _ = setup(tmp_path)
    proof = approve_run(gate)
    tool, proposal = VikunjaRecoveryTool(monitor), action()
    recovery = tool.prepare(proposal)
    grant = gate.request("recovery", recovery)
    assert tool.execute(proposal, gate=gate, grant=grant)["execution_status"] == "succeeded"
    assert len(calls) == 1
    assert calls[0]["binding"]["authorization_mode"] == "single_run"
    assert proof["source"] == "single_run_terminal_approval"
    assert monitor.backend.started == 1
    assert tool.execute(proposal, gate=gate, grant=grant)["execution_status"] == "rejected"
    with pytest.raises(AuthorizationError):
        gate.request("recovery", recovery)


@pytest.mark.parametrize("change", [
    {"max_stops": 2}, {"max_stops": True}, {"max_recovery_starts": 2},
    {"necessary_cleanup_max_starts": 2}, {"model_calls": 1}, {"model_calls": False},
    {"app_restart_allowed": True}, {"allowed_recovery": "restart_service(postgres)"},
    {"authorization_mode": "legacy"},
])
def test_rejects_expanded_initial_policy_before_asking(tmp_path, change):
    gate, _, calls, _ = setup(tmp_path)
    with pytest.raises(AuthorizationError):
        gate.request("experiment", binding() | change)
    assert calls == []


@pytest.mark.parametrize("field,value", [
    ("scope", {}), ("business", {"project_id": 100, "task_id": 2}),
    ("action", {"trace_id": "other"}), ("action", {"incident_id": "other"}),
    ("action", {"action": "restart_service"}), ("action", {"target": "web"}),
    ("action", {"parameters": {"force": True}}), ("action", {"risk": .3}),
    ("action", {"requires_approval": True}),
])
def test_derived_recovery_cannot_expand_parent_scope(tmp_path, field, value):
    gate, monitor, _, _ = setup(tmp_path)
    approve_run(gate)
    data = VikunjaRecoveryTool(monitor).prepare(action())
    if field == "action":
        data[field].update(value)
    else:
        data[field] = value
    with pytest.raises(AuthorizationError):
        gate.request("recovery", data)


def test_no_approval_no_consumption_and_expiry(tmp_path):
    gate, monitor, calls, clock = setup(tmp_path)
    data = VikunjaRecoveryTool(monitor).prepare(action())
    with pytest.raises(AuthorizationError):
        gate.request("recovery", data)
    grant = gate.request("experiment", binding())
    with pytest.raises(AuthorizationError):
        gate.request("recovery", data)
    gate.consume(grant, "experiment", binding(), operation_id="stop-once")
    clock[0] = 401.0
    with pytest.raises(AuthorizationError):
        gate.request("recovery", data)
    with pytest.raises(AuthorizationError):
        gate.request("model", {})
    assert len(calls) == 1 and monitor.backend.started == 0


def test_refusal_creates_no_derived_capability(tmp_path):
    gate, monitor, _, _ = setup(tmp_path, approve=False)
    with pytest.raises(AuthorizationError):
        gate.request("experiment", binding())
    with pytest.raises(AuthorizationError):
        gate.request("recovery", VikunjaRecoveryTool(monitor).prepare(action()))
    assert monitor.backend.started == 0


def test_live_gate_is_limited_to_vikunja_and_original_human_confirmation(tmp_path):
    gate, monitor, _, _ = setup(tmp_path)
    approve_run(gate)
    assert not VikunjaRecoveryTool(monitor)._accepts_live_gate(gate)
    gate.confirm = interactive_confirm
    assert VikunjaRecoveryTool(monitor)._accepts_live_gate(gate)
    assert not RecoveryTool(monitor)._accepts_live_gate(gate)
