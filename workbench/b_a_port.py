"""Bridge actual A delivery; original Gate is consumed inside A RecoveryTool exactly once."""
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

from reops_agent.authorization import AuthorizationGate, Grant, digest
from reops_agent.contracts import validate
from reops_agent.executor import ExecutionOutcome
from .a_actions import RecoveryTool
from .a_docker import DockerTarget, TARGET_ID, TargetError
from .b_a_policy import check_a_start


@dataclass(frozen=True)
class AAuthorization:
    gate: AuthorizationGate = field(repr=False)
    grant: Grant = field(repr=False)
    binding: dict = field(repr=False)


class WorkbenchAPort:
    delegates_authorization = True
    target_id = TARGET_ID
    _check = staticmethod(check_a_start)

    def __init__(self, monitor):
        self.monitor = monitor
        self.tool = RecoveryTool(monitor)
        self.offline_only = not isinstance(monitor.backend, DockerTarget)

    @staticmethod
    def _target(target_id):
        if target_id != TARGET_ID:
            raise TargetError("b_a_target_mismatch")

    def scope(self, target_id):
        self._target(target_id)
        identity, _ = self.monitor.action_scope()
        current = self.monitor.backend.inspect()
        if current.identity != identity:
            raise TargetError("b_a_selected_identity_changed")
        # Generation is included in each A grant, not in the durable experience key.
        return deepcopy(identity.binding())

    def observe(self, target_id, context):
        self._target(target_id)
        return self.monitor.observe(context["incident_id"], context["trace_id"], context.get("case_id"))

    def prepare(self, target_id, action, observation):
        self._target(target_id)
        if not self._check(action, observation)["allowed"]:
            raise TargetError("b_a_start_policy_rejected")
        return self.tool.prepare(action)

    @staticmethod
    def _consumed(authorization, action):
        ledger = Path(authorization.gate.ledger).resolve()
        if not ledger.is_file():
            return False
        with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute("SELECT authorization_id,digest FROM reservations WHERE operation_id=?",
                             ("a-workbench:" + action["action_id"],)).fetchone()
        return row == (authorization.grant.authorization_id, digest(authorization.binding))

    def execute(self, target_id, action, observation, authorization):
        self._target(target_id)
        if not isinstance(authorization, AAuthorization) or not self._check(action, observation)["allowed"]:
            raise TargetError("b_a_original_grant_required")
        result = self.tool.execute(action, gate=authorization.gate, grant=authorization.grant)
        validate("recovery_result", result)
        if (any(result[key] != action[key] for key in ("incident_id", "trace_id", "action_id"))
                or result.get("target_id") != self.target_id):
            raise TargetError("b_a_result_correlation_mismatch", mutation_attempted=None)
        consumed = self._consumed(authorization, action)
        succeeded = result["execution_status"] == "succeeded"
        if result["execution_status"] != "rejected" and not consumed:
            raise TargetError("b_a_consumption_not_proven", mutation_attempted=None)
        return ExecutionOutcome(result["execution_status"], result["exit_code"], None, None,
            result["duration_ms"], deepcopy(observation), {
                "executed": result.get("mutation_attempted") is True, "success": succeeded,
                "action": action["action"], "target": action["target"],
                "authorization_consumed_by_a": consumed,
                "outcome_unknown": result["execution_status"] == "failed" and result.get("mutation_attempted") is not False,
                "a_recovery_result": deepcopy(result)})
