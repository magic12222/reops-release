"""持续监控上的固定规则恢复策略；无故障注入、模型或任意命令权限。"""
from copy import deepcopy
import json
import os
from pathlib import Path
from threading import RLock
import time
from uuid import uuid4

from reops_agent.authorization import AuthorizationError, digest
from .a_monitor import now
from .vikunja_authorization import VikunjaPolicyGate
from .vikunja_target import stopped_database
from .vikunja_dependency import PLAN, DependencyRun, dependency_failure

DURATION = 8 * 3600
MAX_ACTIONS = 3
COOLDOWN = 60


class VikunjaAutomation:
    def __init__(self, monitor, directory, *, clock=time.monotonic):
        self.monitor, self.directory, self.clock = monitor, Path(directory), clock
        self.lock = RLock()
        self.active = False
        self.policy_id = self.scope = self.generation = self.deadline = None
        self.app_started_at = None
        self.business_binding = None
        self.actions = 0
        self.last_action = None
        self.seen = None
        self.failures = self.healthy = 0
        self.failure_observations = []
        self.latched = False
        self.events = []
        self.state = "observe"
        self.offers = {}
        self.inflight = False
        self.plan_id = "database_only"
        self.on_record = None
        self.gate = VikunjaPolicyGate(self.directory / "authorizations.sqlite3", self)
        self._published = self._status_value()

    def record(self, event, **fields):
        value = {"timestamp": now(), "event": event, "policy_id": self.policy_id, **fields}
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.events = (self.events + [value])[-512:]
            self._published = self._status_value()
        if self.on_record is not None:
            self.on_record()

    def _current(self):
        identity, generation = self.monitor.action_scope()
        return identity.binding(), generation

    def _expire(self):
        if self.active and self.clock() >= self.deadline:
            self.active, self.state = False, "expired"
            self.record("policy_expired")

    def _status_value(self, offer=None, dependency_offer=None):
        return {"mode": "automatic" if self.active else "observe", "state": self.state,
            "offer_id": offer, "dependency_offer_id": dependency_offer,
            "plan_id": self.plan_id, "dependency_plan": {"id": PLAN,
                "max_database_starts_per_incident": 1, "max_application_starts_per_incident": 1,
                "sql_timeout_seconds": 45, "business_timeout_seconds": 45,
                "order": ["start_postgres", "wait_sql", "start_exited_app_if_confirmed", "two_fresh_business_checks"]},
            "policy": {"duration_hours": 8, "max_actions": MAX_ACTIONS,
                "cooldown_seconds": COOLDOWN, "action": "start_service(postgres)" if self.plan_id == "database_only" else "postgres_sql_then_conditional_app_start",
                "model_calls": 0, "fault_injection": False},
            "remaining_actions": max(0, MAX_ACTIONS - self.actions),
            "remaining_seconds": max(0, int(self.deadline - self.clock())) if self.active else 0,
            "inflight": self.inflight, "events": deepcopy(self.events)}

    def status(self, owner=None):
        # Recovery owns monitor.control through actual Docker/SQL/HTTP work.
        # Readers must never wait for that work or take locks in reverse order.
        if not self.monitor.control.acquire(blocking=False):
            return deepcopy(self._published)
        try:
            with self.lock:
                return self._status_locked(owner)
        finally:
            self.monitor.control.release()

    def _status_locked(self, owner):
        offer = None
        dependency_offer = None
        try:
            scope, generation = self._current()
            feed = self.monitor.read_targets()
            eligible = bool(feed.targets and feed.targets[0].health == "healthy")
            if owner and eligible and not self.active and not self.inflight:
                business = {"project_id": self.monitor.business.project_id, "task_id": self.monitor.business.task_id}
                key = digest({"scope": scope, "generation": generation, "business": business})
                previous = self.offers.get(owner)
                if previous is None or previous["key"] != key or self.clock() >= previous["deadline"]:
                    previous = {"id": uuid4().hex, "scope": scope, "generation": generation,
                                "key": key, "business": business, "deadline": self.clock() + 300}
                    if len(self.offers) >= 128:
                        self.offers.clear()
                    self.offers[owner] = previous
                offer = previous["id"]
                key_owner = (owner, PLAN)
                dependency = self.offers.get(key_owner)
                if dependency is None or dependency["key"] != key or self.clock() >= dependency["deadline"]:
                    dependency = {**previous, "id": uuid4().hex, "plan_id": PLAN}
                    self.offers[key_owner] = dependency
                dependency_offer = dependency["id"]
        except Exception:
            pass
        self._published = self._status_value()
        return self._status_value(offer, dependency_offer)

    def enable(self, owner, offer_id, *, plan_id="database_only"):
        with self.monitor.control, self.lock:
            if plan_id not in {"database_only", PLAN}:
                raise ValueError("policy_plan_invalid")
            offer = self.offers.get(owner if plan_id == "database_only" else (owner, PLAN))
            if (self.active or self.inflight or offer is None or offer["id"] != offer_id
                    or self.clock() >= offer["deadline"]):
                raise ValueError("policy_offer_invalid")
            scope, generation = self._current()
            current = self.monitor.backend.inspect()
            business = {"project_id": self.monitor.business.project_id, "task_id": self.monitor.business.task_id}
            feed = self.monitor.read_targets()
            if (scope != offer["scope"] or generation != offer["generation"]
                    or current.identity.binding() != scope or business != offer["business"] or not current.running
                    or not current.postgres_running or not feed.targets or feed.targets[0].health != "healthy"):
                raise ValueError("policy_target_not_healthy_or_changed")
            self.policy_id = "policy-vikunja-" + uuid4().hex
            self.plan_id = plan_id
            self.scope, self.generation = scope, generation
            self.app_started_at = current.app_started_at
            self.business_binding = business
            self.deadline, self.actions = self.clock() + DURATION, 0
            self.failures = self.healthy = 0
            self.failure_observations = []
            self.seen, self.last_action, self.latched = None, None, False
            self.record("policy_approved", source="explicit_browser_click", scope_digest=digest(scope),
                        max_actions=MAX_ACTIONS, duration_seconds=DURATION, cooldown_seconds=COOLDOWN,
                        plan_id=plan_id, app_started_at=self.app_started_at, business=self.business_binding)
            self.active, self.state = True, "watching"
            self.offers.clear()

    def disable(self, reason="user_disabled"):
        with self.lock:
            was_active = self.active
            self.active, self.state = False, "observe"
            if was_active:
                self.record("policy_disabled", reason=reason)
            self.offers.clear()

    def check_binding(self, binding):
        self._expire()
        action = binding.get("action", {})
        from reops_agent.contracts import validate
        validate("recovery_action", action)
        scope, generation = self._current()
        if (self.plan_id != "database_only" or not self.active or self.actions >= MAX_ACTIONS or scope != self.scope
                or generation != self.generation or binding.get("scope") != self.scope
                or binding.get("monitor_generation") != generation
                or (action.get("action"), action.get("target")) != ("start_service", "postgres")
                or action.get("parameters") != {} or action.get("requires_approval") is not False
                or action.get("risk", 1) > .2 or type(binding.get("max_actions")) is not int
                or binding.get("max_actions") != 1
                or binding.get("business", {}).get("project_id") != self.monitor.business.project_id
                or binding.get("business", {}).get("task_id") != self.monitor.business.task_id
                or binding.get("business", {}).get("app_started_at") != self.app_started_at
                or (self.last_action is not None and self.clock() - self.last_action < COOLDOWN)):
            raise AuthorizationError("automatic_policy_scope_or_budget_rejected")

    def consume_action(self, binding):
        self.check_binding(binding)
        self.actions += 1
        self.last_action = self.clock()
        self.record("action_reserved", action_id=binding["action"]["action_id"], used_actions=self.actions)

    def tick(self):
        with self.monitor.control:
            self._expire()
            if not self.active:
                return
            try:
                if self._current() != (self.scope, self.generation):
                    raise ValueError("target_changed")
                current = self.monitor.backend.inspect()
                if (current.identity.binding() != self.scope or current.app_started_at != self.app_started_at
                        or {"project_id": self.monitor.business.project_id, "task_id": self.monitor.business.task_id} != self.business_binding):
                    raise ValueError("target_changed")
            except Exception:
                self.disable("monitor_paused_or_target_changed")
                return
            sample = self.monitor.latest_observation()
            feed = self.monitor.read_targets()
            if not sample or not feed.targets or feed.targets[0].health == "unknown":
                return
            if sample["observation_id"] == self.seen:
                return
            self.seen = sample["observation_id"]
            if sample.get("target_health") == "healthy":
                self.healthy += 1
                self.failures = 0
                self.failure_observations = []
                if self.healthy >= 2:
                    self.latched = False
                return
            self.healthy = 0
            predicate = dependency_failure if self.plan_id == PLAN else stopped_database
            self.failures = self.failures + 1 if predicate(sample) else 0
            self.failure_observations = (self.failure_observations + [sample["observation_id"]])[-2:] if predicate(sample) else []
            if self.failures < 2 or self.latched:
                return
            if self.actions >= MAX_ACTIONS:
                self.active, self.state = False, "budget_exhausted"
                self.record("policy_budget_exhausted")
                return
            if self.last_action is not None and self.clock() - self.last_action < COOLDOWN:
                return
            self.latched, self.inflight, self.state = True, True, "recovering"
            context = {"incident_id": "incident-vikunja-auto-" + uuid4().hex,
                       "trace_id": "trace-vikunja-auto-" + uuid4().hex}
            proposal = {"schema_version": "1.0", **context, "action_id": "action-vikunja-auto-" + uuid4().hex,
                "diagnosis_id": "diagnosis-vikunja-rule-" + uuid4().hex, "timestamp": now(),
                "action": "start_service", "target": "postgres", "reason": "Two fresh stopped database business failures",
                "expected_success": .8, "estimated_cost": .1, "risk": .1, "requires_approval": False, "parameters": {}}
            try:
                self.record("fault_confirmed", **context, source="fixed_dependency_rule" if self.plan_id == PLAN else "fixed_rule",
                            plan_id=self.plan_id, observations=self.failure_observations)
                if self.plan_id == PLAN:
                    DependencyRun(self, context).execute()
                    self.state = "watching"
                    if self.actions >= MAX_ACTIONS:
                        self.active, self.state = False, "budget_exhausted"
                        self.record("policy_budget_exhausted")
                    return
                from .vikunja_actions import VikunjaRecoveryTool
                tool = VikunjaRecoveryTool(self.monitor)
                grant = self.gate.request("recovery", tool.prepare(proposal))
                self.record("recovery_started", **context)
                result = tool.execute(proposal, gate=self.gate, grant=grant)
                if result["execution_status"] != "succeeded":
                    raise ValueError("automatic_action_not_completed")
                self.record("database_started", **context)
                # Only our own A action may advance this generation.
                scope, generation = self._current()
                if scope != self.scope or generation != self.generation + 1:
                    raise ValueError("automatic_target_generation_changed")
                self.generation = generation
                observations = []
                self.record("verification_started", **context)
                for index in range(2):
                    observation = self.monitor.observe(**context)
                    current = self.monitor.backend.inspect()
                    if (observation.get("target_health") != "healthy" or current.identity.binding() != self.scope
                            or current.app_started_at != self.app_started_at
                            or not self.monitor.backend.sql_probe(current.identity)):
                        raise ValueError("automatic_verify_failed")
                    observations.append(observation["observation_id"])
                    self.record("verification_passed", **context, check=index + 1,
                                observation_id=observation["observation_id"])
                if len(set(observations)) != 2:
                    raise ValueError("automatic_verify_not_fresh")
                self.state = "watching"
                self.record("recovery_verified", **context, action_id=proposal["action_id"],
                            observations=observations, model_calls=0, source="fixed_rule")
                if self.actions >= MAX_ACTIONS:
                    self.active, self.state = False, "budget_exhausted"
                    self.record("policy_budget_exhausted")
            except Exception as error:
                self.active, self.state = False, "attention"
                reasons = {"dependency_fresh_evidence_rejected", "dependency_exit_not_confirmed",
                    "dependency_sql_timeout", "dependency_business_timeout", "dependency_start_not_observed",
                    "dependency_app_start_not_fresh", "dependency_binding_changed_during_wait",
                    "dependency_scope_budget_or_order_rejected", "dependency_step_failed_or_uncertain"}
                self.record("recovery_requires_attention", **context,
                            reason=str(error) if str(error) in reasons else "recovery_failed_or_uncertain")
            finally:
                self.inflight = False
