"""明确新批准下的固定依赖恢复：数据库 → SQL → 必要时同一应用 → 双业务验证。"""
from copy import deepcopy
import time
from uuid import uuid4

from reops_agent.authorization import AuthorizationGate, AuthorizationError, Grant, digest
from .a_monitor import now, validate_shared
from .a_docker import TargetError
from .a_actions import _contains_command
from .vikunja_target import stopped_database

PLAN = "vikunja_dependency_v1"
SQL_SECONDS = 45
BUSINESS_SECONDS = 45


def dependency_failure(sample):
    return stopped_database(sample) or (
        sample.get("target_health") == "unhealthy" and sample.get("sampling_error") is None
        and sample.get("metrics") == {"api_up": 0, "postgres_up": 0}
        and sample.get("services", {}).get("api") == {"status": "unhealthy", "message": "stopped"}
        and sample.get("services", {}).get("postgres") == {"status": "unhealthy", "message": "stopped"}
        and sample.get("request", {}).get("failure_kind") == "container_stopped"
        and sample.get("request", {}).get("business_passed") is False)


class DependencyGate(AuthorizationGate):
    """新范围专用；与旧 Gate 无互换，逐动作复用原 SQLite 单次消费台账。"""
    def __init__(self, ledger, run):
        super().__init__(ledger)
        self.run = run

    def request(self, purpose, binding):
        self.run.check(purpose, binding)
        grant = Grant("authorization-" + uuid4().hex, purpose, digest(binding), self._now() + 120)
        self._issued[grant.authorization_id] = grant
        return grant

    def consume(self, grant, purpose, binding, *, operation_id):
        self.run.check(purpose, binding)
        return super().consume(grant, purpose, binding, operation_id=operation_id)


class DependencyRun:
    def __init__(self, owner, context, *, clock=time.monotonic, sleep=time.sleep):
        self.owner, self.monitor = owner, owner.monitor
        self.context, self.clock, self.sleep = context, clock, sleep
        self.expected_step = "postgres"
        self.binding = None
        self.gate = DependencyGate(owner.directory / "authorizations.sqlite3", self)

    def check(self, purpose, binding):
        o = self.owner
        o._expire()
        identity, generation = self.monitor.action_scope()
        current = self.monitor.backend.inspect()
        action = binding.get("action", {})
        validate_shared("recovery_action", action)
        if (purpose != "recovery" or not o.active or o.plan_id != PLAN or not o.inflight
                or identity.binding() != o.scope or current.identity != identity
                or generation != o.generation or current.app_started_at != o.app_started_at
                or binding != self.binding or binding.get("plan_id") != PLAN
                or binding.get("policy_id") != o.policy_id or binding.get("step") != self.expected_step
                or binding.get("monitor_generation") != generation
                or binding.get("scope") != o.scope or type(binding.get("max_actions")) is not int or binding.get("max_actions") != 1
                or _contains_command(action) or action["action"] != "start_service"
                or action["target"] != ("postgres" if self.expected_step == "postgres" else "api")
                or action["parameters"] != {} or action["requires_approval"] is not False or action["risk"] > .2
                or any(action.get(key) != value for key, value in self.context.items())
                or binding.get("business") != {"project_id": self.monitor.business.project_id,
                    "task_id": self.monitor.business.task_id, "app_started_at": o.app_started_at}
                or {"project_id": self.monitor.business.project_id, "task_id": self.monitor.business.task_id} != o.business_binding
                or o.actions > 3 or (self.expected_step == "postgres" and o.actions >= 3)):
            raise AuthorizationError("dependency_scope_budget_or_order_rejected")

    def _start(self, service, exit_evidence):
        # Revocation serializes with one submitted command, never the SQL/business wait.
        with self.owner.lock:
            return self._start_locked(service, exit_evidence)

    def _start_locked(self, service, exit_evidence):
        o = self.owner
        action = {"schema_version": "1.0", **self.context, "action_id": "action-vikunja-dependency-" + uuid4().hex,
            "diagnosis_id": "diagnosis-vikunja-dependency-" + uuid4().hex, "timestamp": now(),
            "action": "start_service", "target": "postgres" if service == "postgres" else "api",
            "reason": PLAN, "expected_success": .8, "estimated_cost": .1, "risk": .1,
            "requires_approval": False, "parameters": {}}
        validate_shared("recovery_action", action)
        self.binding = {"plan_id": PLAN, "policy_id": o.policy_id, "step": service,
            "scope": deepcopy(o.scope), "monitor_generation": o.generation, "action": action,
            "business": {"project_id": self.monitor.business.project_id, "task_id": self.monitor.business.task_id,
                         "app_started_at": o.app_started_at}, "max_actions": 1}
        grant = self.gate.request("recovery", self.binding)
        proof = self.gate.consume(grant, "recovery", self.binding,
                                  operation_id="vikunja-dependency:" + action["action_id"])
        # Durable reservation and audit precede mutation; errors never replay a step.
        o.record("dependency_action_reserved", **self.context, step=service, action_id=action["action_id"],
                 authorization_id=proof["authorization_id"], source="dependency_policy_browser_approval")
        self.check("recovery", self.binding)
        o.record("dependency_safety_passed", **self.context, step=service,
                 source="current_identity_scope_budget_and_order_checks")
        self.check("recovery", self.binding)
        identity = self.monitor.begin_action(o.generation)
        o.generation += 1
        if service == "postgres":
            o.actions += 1
            o.last_action = o.clock()
        self.expected_step = None
        try:
            self.monitor.backend.start_dependency(identity, service, o.app_started_at, exit_evidence)
            current = self.monitor.backend.inspect()
            if current.identity != identity or not (current.postgres_running if service == "postgres" else current.running):
                raise ValueError("dependency_start_not_observed")
            if service == "app":
                if current.app_started_at == o.app_started_at:
                    raise ValueError("dependency_app_start_not_fresh")
                o.app_started_at = current.app_started_at
        except Exception:
            o.record("dependency_action_failed", **self.context, step=service,
                     action_id=action["action_id"], outcome="failed_or_uncertain")
            raise ValueError("dependency_step_failed_or_uncertain") from None
        o.record("database_started" if service == "postgres" else "application_started", **self.context,
                 action_id=action["action_id"], source="docker_command_and_inspection", exit_code=0)

    def _wait(self, seconds, probe, failure):
        deadline = self.clock() + seconds
        while self.clock() < deadline:
            o = self.owner
            o._expire()
            current = self.monitor.backend.inspect()
            if (not o.active or self.monitor.action_scope()[1] != o.generation
                    or current.identity.binding() != o.scope or current.app_started_at != o.app_started_at
                    or {"project_id": self.monitor.business.project_id, "task_id": self.monitor.business.task_id} != o.business_binding):
                raise ValueError("dependency_binding_changed_during_wait")
            if probe(current) and self.clock() < deadline:
                return
            self.sleep(min(.5, max(0, deadline - self.clock())))
        raise ValueError(failure)

    def execute(self):
        o, backend = self.owner, self.monitor.backend
        identity, _ = self.monitor.action_scope()
        current = backend.inspect()
        sample = self.monitor.observe(**self.context)
        o.record("dependency_observed", **self.context, observation_id=sample["observation_id"],
                 method="GET", endpoint="/api/v1/tasks/{task_id}",
                 status_code=sample.get("request", {}).get("status_code"),
                 business_passed=sample.get("request", {}).get("business_passed") is True,
                 source="fresh_business_observation")
        if (not dependency_failure(sample) or current.identity != identity
                or current.app_started_at != o.app_started_at or current.postgres_running):
            raise ValueError("dependency_fresh_evidence_rejected")
        stopped_at = backend.database_stop_time(identity)
        exit_evidence = None if current.running else backend.dependency_exit(identity, o.app_started_at, stopped_at)
        if not current.running and not exit_evidence:
            raise ValueError("dependency_exit_not_confirmed")
        o.record("recovery_started", **self.context, plan_id=PLAN, source="fixed_dependency_rule",
                 exit_evidence=exit_evidence, observation_id=sample["observation_id"])
        self._start("postgres", exit_evidence)
        o.record("sql_wait_started", **self.context, timeout_seconds=SQL_SECONDS)
        def sql_ready(current):
            try:
                passed = backend.sql_probe(current.identity) is True
            except TargetError:
                passed = False
            o.record("sql_probe", **self.context, query="SELECT 1", passed=passed, source="actual_sql_probe")
            return passed
        self._wait(SQL_SECONDS, sql_ready, "dependency_sql_timeout")
        o.record("sql_ready", **self.context, source="SELECT 1")
        current = backend.inspect()
        if not current.running:
            exit_evidence = backend.dependency_exit(identity, o.app_started_at, stopped_at)
            if not exit_evidence:
                raise ValueError("dependency_exit_not_confirmed")
            o.record("application_exit_confirmed", **self.context, **exit_evidence)
            self.expected_step = "app"
            self._start("app", exit_evidence)
        else:
            o.record("application_start_skipped", **self.context, reason="same_application_still_running")
        o.record("verification_started", **self.context)
        observations = []
        def verify(current):
            sample = self.monitor.observe(**self.context)
            after = backend.inspect()
            valid = (sample["target_health"] == "healthy" and after == current
                and sql_ready(after) and sample["business"]["app_started_at"] == o.app_started_at
                and sample["business"]["project_id"] == self.monitor.business.project_id
                and sample["business"]["task_id"] == self.monitor.business.task_id)
            o.record("business_check", **self.context, observation_id=sample["observation_id"],
                     method="GET", endpoint="/api/v1/tasks/{task_id}",
                     status_code=sample.get("request", {}).get("status_code"),
                     business_passed=sample.get("request", {}).get("business_passed") is True,
                     passed=valid, source="fresh_business_read_and_sql")
            if not valid:
                observations.clear()
                return False
            if sample["observation_id"] not in observations:
                observations.append(sample["observation_id"])
                o.record("verification_passed", **self.context, check=len(observations),
                         observation_id=sample["observation_id"], source="fresh_business_read_and_sql")
            return len(observations) == 2
        self._wait(BUSINESS_SECONDS, verify, "dependency_business_timeout")
        o.record("recovery_verified", **self.context, observations=observations, model_calls=0,
                 source="fixed_dependency_rule", plan_id=PLAN)
