"""只允许已停止的独立 Vikunja PostgreSQL 启动；沿用 A 的原授权与消费实现。"""
from copy import deepcopy

from reops_agent.strategies import check_offline_action
from reops_agent.authorization import interactive_confirm
from .a_actions import RecoveryTool, _contains_command
from .a_docker import TargetError
from .a_monitor import validate_shared
from .vikunja_target import stopped_database
from .vikunja_authorization import VikunjaRunGate, VikunjaBrowserRunGate, VikunjaPolicyGate


class VikunjaRecoveryTool(RecoveryTool):
    def _accepts_live_gate(self, gate):
        if type(gate) is VikunjaBrowserRunGate:
            from dashboard_api.web_control import BrowserConfirmation
            return type(gate.confirm) is BrowserConfirmation and gate.experiment_consumed
        if type(gate) is VikunjaPolicyGate:
            from .vikunja_automation import VikunjaAutomation
            return type(gate.owner) is VikunjaAutomation and gate.owner.active
        return super()._accepts_live_gate(gate) or (
            type(gate) is VikunjaRunGate and gate.confirm is interactive_confirm
            and gate.experiment_consumed)

    def prepare(self, action):
        action = deepcopy(action)
        validate_shared("recovery_action", action)
        if (_contains_command(action) or (action["action"], action["target"]) != ("start_service", "postgres")
                or action["parameters"] or action["requires_approval"] or action["risk"] > 0.2):
            raise TargetError("vikunja_action_not_allowed")
        identity, generation = self.monitor.action_scope()
        observation = self.monitor.observe(action["incident_id"], action["trace_id"], action.get("case_id"))
        # Same independent strategy safety used by the existing Phase8 online adapter.
        safety = check_offline_action(action, observation, retry_limit=1)
        current = self.monitor.backend.inspect()
        if (not safety["allowed"] or not stopped_database(observation)
                or current.identity != identity or not current.running or current.postgres_running
                or current.postgres_status != "exited"):
            raise TargetError("vikunja_safety_or_identity_rejected")
        return {"scope": identity.binding(), "monitor_generation": generation, "action": action,
            "business": observation["business"], "max_actions": 1}
