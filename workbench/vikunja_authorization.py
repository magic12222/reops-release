"""一次终端批准覆盖固定 Vikunja 运行，逐操作沿用原一次性消费台账。"""
from copy import deepcopy
from uuid import uuid4

from reops_agent.authorization import AuthorizationError, AuthorizationGate, Grant, digest
from reops_agent.contracts import validate


class VikunjaRunGate(AuthorizationGate):
    def __init__(self, ledger, *, confirm=None, ttl=300, clock=None):
        super().__init__(ledger, confirm=confirm, ttl=ttl,
                         **({} if clock is None else {"clock": clock}))
        self.run_binding = None
        self.deadline = None
        self.requested = set()
        self.experiment_consumed = False

    def _experiment(self, binding):
        if (binding.get("operation") != "stop_postgres_for_connection_acceptance"
                or binding.get("authorization_mode") != "single_run"
                or binding.get("allowed_recovery") != "start_service(postgres)"
                or any(type(binding.get(key)) is not int or binding[key] != value for key, value in (
                    ("max_stops", 1), ("max_recovery_starts", 1),
                    ("necessary_cleanup_max_starts", 1), ("model_calls", 0)))
                or binding.get("app_restart_allowed") is not False
                or binding.get("scope", {}).get("target_id") != "reops-vikunja-demo"
                or any(not isinstance(binding.get(key), str) or not binding[key]
                       for key in ("incident_id", "trace_id"))
                or any(type(binding.get("business", {}).get(key)) is not int
                       or binding["business"][key] <= 0 for key in ("project_id", "task_id"))):
            raise AuthorizationError("vikunja_run_policy_rejected")

    def _recovery(self, binding):
        parent = self.run_binding
        if parent is None or not self.experiment_consumed:
            raise AuthorizationError("approved_consumed_run_required")
        action = binding.get("action", {})
        validate("recovery_action", action)
        if (binding.get("scope") != parent["scope"]
                or any(action.get(key) != parent[key] for key in ("incident_id", "trace_id"))
                or any(binding.get("business", {}).get(key) != value
                       for key, value in parent["business"].items())
                or action.get("action") != "start_service" or action.get("target") != "postgres"
                or action.get("parameters") != {} or action.get("requires_approval") is not False
                or action.get("risk", 1) > .2 or type(binding.get("max_actions")) is not int
                or binding.get("max_actions") != 1
                or type(binding.get("monitor_generation")) is not int
                or binding["monitor_generation"] <= 0):
            raise AuthorizationError("vikunja_run_recovery_outside_scope")

    def request(self, purpose, binding):
        if getattr(self.confirm, "cancelled", False):
            raise AuthorizationError("vikunja_run_cancelled")
        if purpose in self.requested:
            raise AuthorizationError("vikunja_run_operation_already_requested")
        if purpose == "experiment":
            if self.requested:
                raise AuthorizationError("vikunja_run_already_started")
            self._experiment(binding)
            grant = super().request(purpose, binding)
            self.run_binding = deepcopy(binding)
            self.deadline = grant.expires_at
        elif purpose == "recovery":
            self._recovery(binding)
            if self.deadline is None or self._now() >= self.deadline:
                raise AuthorizationError("vikunja_run_expired")
            grant = Grant("authorization-" + str(uuid4()), purpose, digest(binding), self.deadline)
            self._issued[grant.authorization_id] = grant
        else:
            raise AuthorizationError("vikunja_run_operation_not_allowed")
        self.requested.add(purpose)
        return grant

    def consume(self, grant, purpose, binding, *, operation_id):
        if getattr(self.confirm, "cancelled", False):
            raise AuthorizationError("vikunja_run_cancelled")
        if purpose == "experiment":
            self._experiment(binding)
            if binding != self.run_binding:
                raise AuthorizationError("vikunja_run_binding_changed")
        elif purpose == "recovery":
            self._recovery(binding)
        else:
            raise AuthorizationError("vikunja_run_operation_not_allowed")
        proof = super().consume(grant, purpose, binding, operation_id=operation_id)
        if purpose == "experiment":
            self.experiment_consumed = True
        proof.update(source="single_run_terminal_approval", run_binding_digest=digest(self.run_binding))
        return proof


class VikunjaBrowserRunGate(VikunjaRunGate):
    """复用 ResearchLoop 的明确点击协议，批准来源如实记为网页。"""
    def request(self, purpose, binding):
        if purpose != "experiment":
            return super().request(purpose, binding)
        original = self.confirm
        def consent(request, challenge):
            request["authorization_mode"] = "single_run"
            return original(request, challenge)
        self.confirm = consent
        try:
            return super().request(purpose, binding)
        finally:
            self.confirm = original

    def consume(self, *args, **kwargs):
        proof = super().consume(*args, **kwargs)
        proof["source"] = "single_run_browser_approval"
        return proof


class VikunjaPolicyGate(AuthorizationGate):
    """已明确开启的目标策略派生能力，不进行交互式自动代答。"""
    def __init__(self, ledger, owner):
        super().__init__(ledger)
        self.owner = owner
        self.requested_actions = set()

    def request(self, purpose, binding):
        if purpose != "recovery":
            raise AuthorizationError("policy_cannot_inject_fault_or_call_model")
        self.owner.check_binding(binding)
        action_id = binding["action"]["action_id"]
        if action_id in self.requested_actions:
            raise AuthorizationError("policy_action_already_requested")
        # Keep the original Gate clock/TTL and durable consumption implementation.
        grant = Grant("authorization-" + str(uuid4()), purpose, digest(binding), self._now() + 120)
        self._issued[grant.authorization_id] = grant
        self.requested_actions.add(action_id)
        return grant

    def consume(self, grant, purpose, binding, *, operation_id):
        if purpose != "recovery":
            raise AuthorizationError("policy_operation_rejected")
        self.owner.check_binding(binding)
        proof = super().consume(grant, purpose, binding, operation_id=operation_id)
        self.owner.consume_action(binding)
        proof.update(source="target_policy_browser_approval", policy_id=self.owner.policy_id)
        return proof
