"""一次运行批准：只向当前固定范围派生逐操作能力，保留原消费台账。"""
from copy import deepcopy
from uuid import uuid4

from reops_agent.authorization import AuthorizationError, AuthorizationGate, Grant, digest
from reops_agent.contracts import validate


class RunGate(AuthorizationGate):
    def __init__(self, ledger, *, confirm, context, model_digest, ttl=300, clock=None):
        self.context = deepcopy(context)
        self.model_digest = model_digest
        self.scope = self.business = self.deadline = None
        self.requested = set()
        kwargs = {} if clock is None else {"clock": clock}
        super().__init__(ledger, confirm=confirm, ttl=ttl, **kwargs)

    def _check(self, purpose, binding):
        if (any(binding.get(key) != value for key, value in self.context.items())
                or binding.get("scope") != self.scope):
            raise AuthorizationError("run_scope_mismatch")
        if purpose == "experiment":
            if (binding.get("fault") != "stop_postgres_once"
                    or binding.get("cleanup") != "at_most_one_fixed_postgres_restart_if_stopped"):
                raise AuthorizationError("run_fault_or_cleanup_rejected")
        elif purpose == "model":
            if (binding.get("max_calls") != 1 or type(binding.get("max_calls")) is not int
                    or binding.get("max_output_tokens") != 512 or type(binding.get("max_output_tokens")) is not int
                    or binding.get("input") != "bounded_structured_observation"
                    or binding.get("model_identifier_sha256") != self.model_digest):
                raise AuthorizationError("run_model_budget_or_service_rejected")
        elif purpose == "recovery":
            action = binding.get("action", {})
            validate("recovery_action", action)
            if (action.get("action") != "restart_service" or action.get("target") != "postgres"
                    or action.get("parameters") != {}
                    or any(action.get(key) != value for key, value in self.context.items())
                    or {key: binding.get("business", {}).get(key) for key in self.business} != self.business):
                raise AuthorizationError("run_recovery_rejected")
        else:
            raise AuthorizationError("unknown_authorization_purpose")

    def request(self, purpose, binding):
        if purpose in self.requested:
            raise AuthorizationError("run_operation_already_requested")
        if purpose == "experiment":
            if self.requested or not isinstance(binding.get("scope"), dict) or not isinstance(binding.get("business"), dict):
                raise AuthorizationError("run_experiment_required")
            self.scope = deepcopy(binding["scope"])
            self.business = {key: deepcopy(binding["business"].get(key))
                             for key in ("project_id", "project_db_id", "owner_user_id")}
            self._check(purpose, binding)
            original = self.confirm
            def consent(request, challenge):
                request.update(authorization_mode="single_run", policy={
                    "target": "ResearchLoop isolated PostgreSQL", "max_faults": 1,
                    "max_model_calls": 1, "max_output_tokens": 512,
                    "recovery": "restart_service(postgres)", "max_recoveries": 1,
                    "cleanup": "at most one fixed PostgreSQL restart if stopped",
                    "model_service_digest": self.model_digest})
                return original(request, challenge)
            self.confirm = consent
            try:
                grant = super().request(purpose, binding)
            finally:
                self.confirm = original
            self.deadline = grant.expires_at
        else:
            self._check(purpose, binding)
            if self.deadline is None or self._now() >= self.deadline or self.confirm.cancelled:
                raise AuthorizationError("run_expired_or_cancelled")
            grant = Grant("authorization-" + str(uuid4()), purpose, digest(binding), self.deadline)
            self._issued[grant.authorization_id] = grant
        self.requested.add(purpose)
        return grant

    def consume(self, grant, purpose, binding, *, operation_id):
        self._check(purpose, binding)
        if self.confirm.cancelled:
            raise AuthorizationError("run_cancelled")
        proof = super().consume(grant, purpose, binding, operation_id=operation_id)
        proof.update(source="single_run_browser_approval", approval_scope_digest=digest(self.scope))
        return proof
