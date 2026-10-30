"""B notification worker. No HTTP routes, native process controls or default real executor."""
from copy import deepcopy
from dataclasses import dataclass
import math
import time
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from reops_agent.advisory import diagnose_advisory, structured_observation
from reops_agent.agent_event import build_agent_event
from reops_agent.authorization import AuthorizationError, AuthorizationGate, digest
from reops_agent.b_clock import wall_time
from reops_agent.contracts import validate
from reops_agent.executor import ExecutionOutcome, validate_outcome
from reops_agent.memory import RecoveryMemory
from reops_agent.pipeline import diagnose
from reops_agent.planner import plan_recovery
from reops_agent.safety import check_action
from reops_agent.verification import verify

from .b_model import RecordingProvider
from .b_io import BoundedA
from .b_store import BStore, instant, now
from .b_a_policy import check_a_start, plan_a_start, verify_a_business
from .b_a_port import AAuthorization, WorkbenchAPort
from .b_vikunja import (PROFILE as VIKUNJA_PROFILE, BUSINESS_ENDPOINT as VIKUNJA_ENDPOINT,
    VikunjaAPort, check_vikunja_start, current_business_healthy, plan_vikunja_start, verify_vikunja_business, safe_vikunja_observation)


class APort(Protocol):
    """Proposed A boundary; host supplies authenticated whitelist implementation."""
    def scope(self, target_id: str) -> dict: ...
    def observe(self, target_id: str, context: dict) -> dict: ...
    def execute(self, target_id: str, action: dict, observation: dict, authorization: dict) -> ExecutionOutcome: ...


def condition_fingerprint(obs, diagnosis, profile):
    signature = {"services": obs["services"], "metrics": obs["metrics"],
        "request": {key: obs["request"].get(key) for key in ("method", "endpoint", "status_code")},
        "failure_type": diagnosis["failure_type"], "component": diagnosis["failed_component"]}
    if profile == VIKUNJA_PROFILE:
        signature["request"].update({key: obs["request"].get(key) for key in ("failure_kind", "business_passed")})
    return digest(signature)


@dataclass(frozen=True)
class TargetPolicy:
    target_id: str
    system_name: str
    environment: str
    allowed_actions: tuple = (("restart_service", "web"), ("restart_service", "postgres"))
    runtime: str = "docker"
    business_endpoint: str = "/users"
    profile: str = "default"

    def __post_init__(self):
        if (not all(isinstance(value, str) and value.strip() for value in
                    (self.target_id, self.system_name, self.environment, self.business_endpoint))
                or self.runtime != "docker" or not isinstance(self.allowed_actions, tuple)
                or self.profile not in {"default", "a_workbench_start", VIKUNJA_PROFILE}
                or (self.profile == "default" and not set(self.allowed_actions) <= {("restart_service", "web"), ("restart_service", "postgres")})
                or (self.profile == "a_workbench_start" and (self.target_id, self.system_name, self.environment,
                    self.business_endpoint, self.allowed_actions) != ("reops-lab-api", "reops-lab", "docker-local",
                    "/users", (("start_service", "web"),)))
                or (self.profile == VIKUNJA_PROFILE and (self.target_id, self.system_name, self.environment,
                    self.business_endpoint, self.allowed_actions) != ("reops-vikunja-demo", "reops-vikunja-demo", "isolated-demo",
                    VIKUNJA_ENDPOINT, (("start_service", "postgres"),)))):
            raise ValueError("b_target_policy_invalid_native_scope_unconfirmed")


class BRuntime:
    def __init__(self, store: BStore, port: APort, policy: TargetPolicy, *, gate: AuthorizationGate,
                 provider=None, model="unknown", execute=False, model_timeout=30, sample_max_age=30,
                 a_timeout=5, action_timeout=30, verify_timeout=30, verify_poll_interval=.5):
        if type(execute) is not bool or not isinstance(gate, AuthorizationGate):
            raise ValueError("b_explicit_gate_and_execution_flag_required")
        if any(type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 60
               for value in (model_timeout, sample_max_age, verify_timeout)) or any(
                   type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 120
                   for value in (a_timeout, action_timeout)):
            raise ValueError("b_time_budget_invalid")
        if type(verify_poll_interval) not in (int, float) or not math.isfinite(verify_poll_interval) or not 0 < verify_poll_interval <= 2:
            raise ValueError("b_verify_poll_interval_invalid")
        if policy.profile == "a_workbench_start" and not isinstance(port, WorkbenchAPort):
            raise ValueError("b_a_profile_requires_original_A_port")
        if policy.profile == VIKUNJA_PROFILE and not isinstance(port, VikunjaAPort):
            raise ValueError("b_vikunja_profile_requires_original_vikunja_port")
        if policy.profile == "a_workbench_start" and isinstance(port, VikunjaAPort):
            raise ValueError("b_a_profile_vikunja_port_conflict")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("b_model_identifier_required")
        if store.source == "real" and (getattr(port, "offline_only", False) is True
                or getattr(provider, "offline_only", False) is True):
            raise ValueError("b_fixture_cannot_produce_real_records")
        config = getattr(provider, "config", None)
        if config is not None and (type(config.max_output_tokens) is not int or not 64 <= config.max_output_tokens <= 512):
            raise ValueError("b_model_output_budget_exceeds_512")
        self.store, self.port, self.policy, self.gate = store, port, policy, gate
        self.a_io = BoundedA(port)
        self.provider, self.model, self.execute = provider, model, execute
        self.model_timeout, self.sample_max_age = model_timeout, sample_max_age
        self.a_timeout, self.action_timeout = a_timeout, action_timeout
        self.verify_timeout, self.verify_poll_interval = verify_timeout, verify_poll_interval
        # Reuse a single RCA inflight boundary across incidents. A timed-out call blocks
        # further model calls until its thread exits; no accumulating orphan requests.
        from threading import Lock
        self.provider_lock = Lock()

    def _check(self, action, observation):
        if self.policy.profile == VIKUNJA_PROFILE:
            return check_vikunja_start(action, observation)
        return check_a_start(action, observation) if self.policy.profile == "a_workbench_start" else check_action(action, observation, retry_limit=1)

    def _verify(self, observation):
        if self.policy.profile == VIKUNJA_PROFILE:
            return verify_vikunja_business(observation)
        return verify_a_business(observation) if self.policy.profile == "a_workbench_start" else verify(observation)

    def _plan(self, diagnosis, observation, history=(), *, model_suggestion=None):
        if self.policy.profile == VIKUNJA_PROFILE:
            return plan_vikunja_start(diagnosis, observation, history, model_suggestion=model_suggestion)
        return plan_a_start(diagnosis, observation, history, model_suggestion=model_suggestion) if self.policy.profile == "a_workbench_start" else plan_recovery(diagnosis, observation=observation, history_evidence=history)

    def _scope(self):
        value = self.a_io.call("scope", self.policy.target_id, timeout=self.a_timeout)
        if not isinstance(value, dict) or not value or value.get("target_id") != self.policy.target_id:
            raise ValueError("b_a_scope_target_binding_required")
        return deepcopy(value)

    def _sample(self, observation, *, context=None, previous=None, not_before=None, allow_unavailable=False):
        validate("observation", observation)
        if (observation["system"].get("name") != self.policy.system_name
                or observation["system"].get("environment") != self.policy.environment
                or not observation["services"]
                or not set(observation["services"]) <= ({"api", "business"} if self.policy.profile == "a_workbench_start" else {"api", "postgres", "business"} if self.policy.profile == VIKUNJA_PROFILE else {"api", "postgres", "redis"})
                or observation["request"].get("endpoint") != self.policy.business_endpoint
                or observation["request"].get("method") != "GET"
                or observation["observation_id"].startswith("obs-unavailable-")):
            raise ValueError("b_observation_target_or_business_mismatch")
        sampled = instant(observation["timestamp"])
        current = wall_time()
        if sampled > current + 1 or current - sampled > self.sample_max_age:
            raise ValueError("b_observation_stale")
        if not_before is not None and sampled < not_before:
            raise ValueError("b_observation_not_fresh")
        if context and any(observation[key] != context[key] for key in ("incident_id", "trace_id")):
            raise ValueError("b_observation_correlation_mismatch")
        if previous and (observation["observation_id"] == previous["observation_id"]
                         or sampled < instant(previous["timestamp"])):
            raise ValueError("b_observation_repeated_or_reversed")
        # Existing structured filter removes free logs, headers, business IDs and paths.
        safe = structured_observation(observation)
        safe["system"] = {"name": self.policy.system_name, "environment": self.policy.environment}
        safe["request"]["endpoint"] = self.policy.business_endpoint
        if self.policy.profile == "a_workbench_start":
            if (observation["system"].get("target_id") != self.policy.target_id
                    or set(observation["services"]) != {"api", "business"}
                    or type(observation["request"].get("business_passed")) not in (bool, type(None))
                    or observation.get("sampling_error") is not None and not allow_unavailable):
                raise ValueError("b_a_observation_unavailable_or_invalid")
            safe["system"]["target_id"] = self.policy.target_id
            safe["services"]["business"] = {"status": observation["services"]["business"]["status"],
                                                  "message": "GET /users payload validation"}
            safe["request"]["business_passed"] = observation["request"]["business_passed"]
            safe["target_health"] = observation["target_health"]
            safe["sampling_error"] = "a_observation_unavailable" if observation.get("sampling_error") is not None else None
            safe["sample_completed_at"] = observation["sample_completed_at"]
            instant(safe["sample_completed_at"])
        if self.policy.profile == VIKUNJA_PROFILE:
            safe = safe_vikunja_observation(observation, allow_unavailable=allow_unavailable)
            instant(safe["sample_completed_at"])
        return safe

    def _observe(self, context, previous, scope, *, for_verify=False):
        started = wall_time()
        raw = self.a_io.call("observe", self.policy.target_id, deepcopy(context), timeout=self.a_timeout)
        sample = self._sample(raw, context=context, previous=previous, not_before=started, allow_unavailable=for_verify)
        if self._scope() != scope:
            raise ValueError("b_target_identity_changed")
        return sample

    def notify(self, target_id, observation, *, context=None):
        """A calls once per sample; duplicates merge without additional model/action."""
        if target_id != self.policy.target_id:
            raise ValueError("b_unknown_target")
        # Reject malformed/old samples before any provider, action or persistent claim.
        safe = self._sample(observation)
        scope = self._scope()
        scope_key = digest({"scope": scope, "policy": self.policy.__dict__})
        diagnosis = diagnose(safe)
        healthy = current_business_healthy(safe) if self.policy.profile == VIKUNJA_PROFILE else self._verify(safe)[2]
        incident = self.store.claim(target_id, safe, failing=diagnosis["failure_detected"],
                                    healthy=healthy, scope_key=scope_key, context=context)
        if incident is None:
            return None
        context = {"incident_id": incident.id, "trace_id": incident.trace_id}
        safe.update(context)
        self._run(incident.id, safe, scope, scope_key)
        return incident.id

    def observation_failed(self, target_id):
        """Observer exceptions carry no raw text and never authorize a recovery."""
        if target_id != self.policy.target_id:
            raise ValueError("b_unknown_target")
        # An outage of the observation channel is latched separately from service faults.
        unavailable = {"observation_id": "observer-error-" + uuid4().hex,
            "incident_id": "upstream-unknown", "trace_id": "upstream-unknown", "timestamp": now()}
        incident = self.store.claim(target_id, unavailable, failing=True, healthy=False, scope_key="observer_unavailable")
        if incident:
            self.store.event(incident.id, "observe", "failed", "observation_unavailable")
            self.store.update(incident.id, status="failed", summary="observation_unavailable",
                              verification={"status": "unknown", "checks": []})
            self.store.finish(incident.id, unavailable["timestamp"], recovered=False)
        return incident.id if incident else None

    def _history(self, incident_id, obs, scope_key, memory):
        diagnosis = diagnose(obs)
        failure_key = condition_fingerprint(obs, diagnosis, self.policy.profile)
        records = self.store.experiences(self.policy.target_id)
        compatible = [(exp, meta) for exp, meta in records
                      if meta["scope_key"] == scope_key and meta["failure_key"] == failure_key]
        # A matching failure invalidates the fast path, rather than cherry-picking success.
        successful = [(exp, meta) for exp, meta in compatible if exp["status"] == "verified"]
        source_ids = {meta["memory_event_id"] for _, meta in successful}
        history = memory.retrieve(diagnosis["failure_type"], diagnosis["failed_component"], limit=20)
        history = [item for item in history if item["event_id"] in source_ids
                   and item["recovered"] is True and item.get("match_type") == "exact"]
        selected = next(((exp, meta) for exp, meta in reversed(successful)
                         if any(item["event_id"] == meta["memory_event_id"] for item in history)), None)
        reason = "experience_conditions_matched" if selected else (
            "experience_conditions_or_status_rejected" if records else "no_previous_experience")
        self.store.event(incident_id, "root_cause_analysis", "succeeded", "experience_lookup",
            evidence=[reason, "scope=" + scope_key, "conditions=" + failure_key])
        for exp, meta in records:
            if selected and exp["id"] == selected[0]["id"]:
                continue
            rejection = ("status=" + exp["status"] if exp["status"] != "verified" else
                "environment_or_identity_changed" if meta["scope_key"] != scope_key else
                "failure_conditions_changed" if meta["failure_key"] != failure_key else
                "source_memory_missing_or_not_selected")
            self.store.event(incident_id, "root_cause_analysis", "skipped", "experience_rejected",
                             evidence=["experience_id=" + exp["id"], rejection])
        return diagnosis, failure_key, history if selected else [], selected

    def _run(self, incident_id, obs, scope, scope_key):
        stage, current = "observe", obs
        context = {key: obs[key] for key in ("incident_id", "trace_id")}
        memory = RecoveryMemory(self.store.path.parent / "b-memory" / (scope_key + ".jsonl"))
        action = result = verification = diagnosis = None
        failure_key = None
        root_cause = None
        recovered = False
        try:
            self.store.event(incident_id, stage, "succeeded", "observation_received",
                             evidence=["observation_id=" + obs["observation_id"], "observed_at=" + obs["timestamp"],
                                *[name + "=" + item["status"] for name, item in obs["services"].items()],
                                "business_status=" + str(obs["request"].get("status_code"))])
            stage = "failure_detection"
            self.store.event(incident_id, stage, "succeeded", "incident_claimed_once")
            self.store.update(incident_id, status="diagnosing")
            stage = "localization"
            diagnosis = diagnose(obs)
            self.store.event(incident_id, stage, "succeeded", "failure_localized",
                             evidence=["component=" + str(diagnosis["failed_component"])])
            stage = "root_cause_analysis"
            diagnosis, failure_key, history, selected = self._history(incident_id, obs, scope_key, memory)
            root_cause = diagnosis["root_cause"]
            if selected:
                exp, meta = selected
                root_cause = exp["root_cause"]
                self.store.update(incident_id, diagnosis_source="experience", experience_ids=[exp["id"]])
                action = self._plan(diagnosis, obs, history)
                self.store.event(incident_id, stage, "succeeded", "experience_adopted",
                    evidence=["experience_id=" + exp["id"], "source_incident=" + exp["incident_id"],
                              "source_memory_event=" + meta["memory_event_id"]])
            elif self.provider is not None:
                binding = {**context, "scope_digest": digest(scope), "model_digest": digest(self.model),
                           "max_model_calls": 1, "max_output_tokens": 512,
                           "pre_observation_id": obs["observation_id"]}
                self.store.update(incident_id, status="waiting_human")
                self.store.event(incident_id, stage, "waiting_human", "model_authorization_required")
                grant = self.gate.request("model", binding)
                if self._scope() != scope:
                    raise AuthorizationError("b_model_scope_changed")
                self.gate.consume(grant, "model", binding, operation_id="b:model:" + incident_id)
                self.store.update(incident_id, status="diagnosing")
                recorder = RecordingProvider(self.provider, self.store, incident_id, self.model)
                lock = self.provider_lock
                wrapped = self.provider

                class SingleInflight:
                    def complete(self, request, *, timeout_seconds):
                        if not lock.acquire(blocking=False):
                            raise ValueError("b_provider_busy")
                        try:
                            return wrapped.complete(request, timeout_seconds=timeout_seconds)
                        finally:
                            lock.release()

                recorder.provider = SingleInflight()
                core = diagnose_advisory(obs, recorder, timeout=self.model_timeout)
                # BoundedProvider forwards the RCA close callback, including timeout.
                if not core["diagnosis_validated"] or core["rejection_reason"] is not None:
                    self.store.event(incident_id, stage, "failed", "model_diagnosis_rejected",
                                     evidence=[core["rejection_reason"] or "diagnosis_invalid"])
                    raise ValueError("b_model_failed_no_fallback_execution")
                self.store.update(incident_id, diagnosis_source="model")
                diagnosis = core["diagnosis"]
                root_cause = core["rca"]["result"]["suspected_root_cause"]
                action = core["recovery_action"]
                if self.policy.profile == "a_workbench_start":
                    if (not core["would_execute"] or root_cause != "api_service_down"
                            or core["rca"]["result"]["affected_component"] not in {"api", "web"}):
                        raise ValueError("b_a_model_root_cause_not_supported")
                    suggestion = core["rca"]["result"]["suggested_action"]
                    action = self._plan(diagnosis, obs, model_suggestion=suggestion)
                    self.store.event(incident_id, stage, "succeeded", "a_scoped_start_selected_independently",
                        evidence=["model_suggestion=" + suggestion["action"] + "(" + str(suggestion["target"]) + ")",
                                  "model_action_applied=false", "A_allowed_action=start_service(web)"])
                if self.policy.profile == VIKUNJA_PROFILE:
                    if (not core["would_execute"] or root_cause != "postgres_service_down"
                            or core["rca"]["result"]["affected_component"] != "postgres"):
                        raise ValueError("b_vikunja_model_root_cause_not_supported")
                    suggestion = core["rca"]["result"]["suggested_action"]
                    action = self._plan(diagnosis, obs, model_suggestion=suggestion)
                    self.store.event(incident_id, stage, "succeeded", "vikunja_scoped_start_selected_independently",
                        evidence=["model_action_applied=false", "A_allowed_action=start_service(postgres)"])
                self.store.event(incident_id, stage, "succeeded", "model_diagnosis_validated")
            else:
                self.store.update(incident_id, diagnosis_source="rule")
                action = self._plan(diagnosis, obs)
                self.store.event(incident_id, stage, "skipped", "model_not_configured_rule_only")
            stage = "recovery_decision"
            safety = self._check(action, obs)
            if (not safety["allowed"] or (action["action"], action["target"]) not in self.policy.allowed_actions
                    or action["action"] == "no_action"):
                raise ValueError("b_action_rejected")
            self.store.event(incident_id, stage, "succeeded", "safety_and_target_policy_passed",
                evidence=[action["action"] + "(" + action["target"] + ")", "max_recovery_actions=1"])
            if not self.execute:
                self.store.event(incident_id, stage, "waiting_human", "recovery_disabled_by_default")
                self.store.update(incident_id, status="waiting_human", summary="execution_flag_required")
                return
            self.store.update(incident_id, status="waiting_human")
            binding = {**context, "scope_digest": digest(scope), "target_id": self.policy.target_id,
                "action_digest": digest(action), "pre_observation_id": obs["observation_id"], "max_actions": 1}
            if self.policy.profile in {"a_workbench_start", VIKUNJA_PROFILE}:
                binding = self.a_io.call("prepare", self.policy.target_id, deepcopy(action), deepcopy(obs), timeout=self.a_timeout)
            self.store.event(incident_id, stage, "waiting_human", "recovery_authorization_required")
            grant = self.gate.request("recovery", binding)
            current = self._observe(context, obs, scope)
            if not self._check(action, current)["allowed"]:
                raise AuthorizationError("b_pre_execution_fault_changed")
            authorization = (AAuthorization(self.gate, grant, deepcopy(binding)) if self.policy.profile in {"a_workbench_start", VIKUNJA_PROFILE} else
                self.gate.consume(grant, "recovery", binding, operation_id="b:recovery:" + incident_id))
            stage = "recovery_execution"
            self.store.update(incident_id, status="executing")
            self.store.event(incident_id, stage, "running", "controlled_a_tool_started")
            self.store.tool_pending(incident_id, True)
            # Irrevocable claim and audit already committed. Unknown results never replay.
            outcome = self.a_io.call("execute", self.policy.target_id, deepcopy(action), deepcopy(current), authorization,
                timeout=self.action_timeout, finished=lambda: self.store.tool_pending(incident_id, False))
            validate_outcome(outcome, action)
            if outcome.execution and "a_recovery_result" in outcome.execution:
                self.store.event(incident_id, stage, "succeeded" if outcome.status == "succeeded" else "failed",
                    "a_original_result_and_consumption_retained",
                    evidence=["a_result_id=" + outcome.execution["a_recovery_result"]["result_id"],
                              "authorization_consumed_by_a=" + str(outcome.execution["authorization_consumed_by_a"]).lower()],
                    documents={"recovery_result": outcome.execution["a_recovery_result"]})
            if outcome.status in {"rejected", "skipped"}:
                self.store.event(incident_id, stage, "failed", "controlled_a_tool_rejected_no_mutation")
                self.store.update(incident_id, status="failed", summary="a_tool_rejected",
                                  verification={"status": "unknown", "checks": []})
                return
            if outcome.execution and outcome.execution.get("outcome_unknown"):
                raise ValueError("b_a_execution_unknown")
            if (outcome.execution and "a_recovery_result" in outcome.execution and outcome.status == "failed"
                    and outcome.execution["a_recovery_result"].get("mutation_attempted") is False):
                self.store.event(incident_id, stage, "failed", "controlled_a_tool_failed_before_mutation")
                self.store.update(incident_id, status="failed", summary="a_tool_failed_before_mutation",
                                  verification={"status": "unknown", "checks": []})
                return
            if not outcome.execution or outcome.execution.get("executed") is not True:
                raise ValueError("b_controlled_execution_not_confirmed")
            self.store.event(incident_id, stage, "succeeded" if outcome.status == "succeeded" else "failed",
                             "controlled_a_tool_result", evidence=["execution_status=" + outcome.status])
            stage = "verification"
            self.store.update(incident_id, status="verifying")
            checks = []
            consecutive = []
            deadline = time.monotonic() + self.verify_timeout
            # Executor's post observation is not reused. Two distinct fresh business checks.
            while time.monotonic() < deadline:
                current = self._observe(context, current, scope, for_verify=True)
                _, verification, healthy = self._verify(current)
                healthy = healthy and current["request"].get("status_code") == 200
                healthy = healthy and time.monotonic() <= deadline
                checks.append("observation_id=" + current["observation_id"] + ";business=" + ("passed" if healthy else "failed"))
                consecutive = (consecutive + [checks[-1]])[-2:] if healthy else []
                retry = self.policy.profile in {"a_workbench_start", VIKUNJA_PROFILE} and time.monotonic() < deadline
                self.store.event(incident_id, stage, "succeeded" if healthy else "running" if retry else "failed",
                                 "fresh_business_check", evidence=[checks[-1]])
                if len(consecutive) == 2 or not healthy and not retry:
                    break
                if self.policy.profile in {"a_workbench_start", VIKUNJA_PROFILE}:
                    time.sleep(min(self.verify_poll_interval, max(0, deadline - time.monotonic())))
            recovered = outcome.status == "succeeded" and len(consecutive) == 2
            if recovered:
                checks = consecutive
            elif self.policy.profile in {"a_workbench_start", VIKUNJA_PROFILE}:
                self.store.event(incident_id, stage, "failed", "business_verification_deadline_or_failure")
            verification = verification or {"status": "inconclusive", "checked_at": now(),
                "health_check_passed": None, "fault_cleared": None, "business_request_passed": None, "evidence": []}
            verification["status"] = "recovered" if recovered else "not_recovered"
            result = {"schema_version": "1.0", **context, "result_id": "result-b-" + uuid4().hex,
                "action_id": action["action_id"], "timestamp": now(), "execution_status": outcome.status,
                "exit_code": outcome.exit_code, "stdout": None, "stderr": None, "duration_ms": outcome.duration_ms,
                "post_observation_id": current["observation_id"], "verification": verification,
                "executor": {key: outcome.execution[key] for key in ("executed", "success", "action", "target")}}
            validate("recovery_result", result)
            if "a_recovery_result" in outcome.execution:
                result["a_recovery_result"] = outcome.execution["a_recovery_result"]
            self.store.update(incident_id, status="recovered" if recovered else "failed", summary="business_verified" if recovered else "business_verification_failed",
                              verification={"status": "passed" if recovered else "failed", "checks": checks})
            stage = "experience_update"
            self._remember(incident_id, memory, obs, diagnosis, action, result, verification, recovered,
                           scope_key, failure_key, root_cause)
        except AuthorizationError:
            self.store.event(incident_id, stage, "waiting_human", "authorization_missing_expired_or_changed")
            self.store.update(incident_id, status="waiting_human", summary="authorization_required")
        except Exception:
            # An execution exception means the tool may already have acted. No automatic retry.
            code = "execution_outcome_unknown_no_retry" if stage == "recovery_execution" else "b_" + stage + "_failed"
            self.store.event(incident_id, stage, "failed", code)
            body, _ = self.store.get(incident_id)
            self.store.update(incident_id, status="unknown" if stage == "recovery_execution" else "failed",
                              summary=code, verification=body["verification"] if recovered else {"status": "unknown" if stage != "verification" else "failed", "checks": []})
            if stage in {"recovery_execution", "verification"} and failure_key:
                self._retire(scope_key, failure_key)
        finally:
            # Only a completed verified recovery can release a latch without a new healthy notification.
            self.store.finish(incident_id, current["timestamp"], recovered=recovered)

    def _retire(self, scope_key, failure_key):
        for exp, meta in self.store.experiences(self.policy.target_id):
            if meta["scope_key"] == scope_key and meta["failure_key"] == failure_key and exp["status"] == "verified":
                self.store.retire(exp["id"])

    def _remember(self, incident_id, memory, obs, diagnosis, action, result, verification, recovered,
                  scope_key, failure_key, root_cause):
        event = build_agent_event(obs, diagnosis, action, result, verification, recovered)
        event["data"].update(target_id=self.policy.target_id, scope_fingerprint=scope_key, source=self.store.source)
        event["data"]["experience"] = {"root_cause": root_cause or "unknown"}
        body, _ = self.store.get(incident_id)
        event["parent_event_id"] = body["events"][-1]["id"]
        event["data"]["sequence"] = len(body["events"])
        # Existing Memory contract and fsync are preserved. No runtime/example import.
        memory.remember(event)
        if not recovered:
            self._retire(scope_key, failure_key)
        source_event = self.store.event(incident_id, "experience_update", "succeeded" if recovered else "failed",
            "memory_persisted", evidence=["memory_event_id=" + event["event_id"]], source_event=event)
        experience = {"id": "experience-b-" + uuid4().hex, "target_id": self.policy.target_id,
            "incident_id": incident_id, "title": "Verified recovery" if recovered else "Failed recovery",
            "symptom": diagnosis["failure_type"] or "unknown", "root_cause": root_cause or "unknown",
            "action": action["action"] + "(" + action["target"] + ")",
            "conditions": ["target=" + self.policy.target_id, "scope=" + scope_key, "conditions=" + failure_key,
                "source_event=" + source_event, "memory_event=" + event["event_id"],
                *["service=" + name + ";status=" + value["status"] for name, value in obs["services"].items()],
                *[name + "=" + str(value) for name, value in obs["metrics"].items()],
                "business=GET " + self.policy.business_endpoint + ";status=" + str(obs["request"]["status_code"]),
                "requires current Safety, target binding and two fresh business verifications"],
            "status": "verified" if recovered else "failed"}
        self.store.save_experience(experience, {"scope_key": scope_key, "failure_key": failure_key,
            "memory_event_id": event["event_id"], "source_event_ids": [source_event]})
        body, _ = self.store.get(incident_id)
        self.store.update(incident_id, experience_ids=body["experience_ids"] + [experience["id"]])


def poll(runtime, *, interval=2, stop):
    """Optional A polling host; not started by read_agent or GET. Push uses notify directly."""
    if type(interval) not in (int, float) or not math.isfinite(interval) or not .2 <= interval <= 60:
        raise ValueError("b_poll_interval_invalid")
    while not stop.is_set():
        context = {"incident_id": "observation-" + uuid4().hex, "trace_id": "sample-" + uuid4().hex}
        try:
            observation = runtime.a_io.call("observe", runtime.policy.target_id, context, timeout=runtime.a_timeout)
            runtime.notify(runtime.policy.target_id, observation)
        except Exception:
            runtime.observation_failed(runtime.policy.target_id)
        stop.wait(interval)
