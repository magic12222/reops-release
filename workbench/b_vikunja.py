"""Vikunja 专用 B profile：经验只提出固定候选，执行仍由原 A/Gate 决定。"""
from copy import deepcopy

from reops_agent.contracts import validate
from reops_agent.strategies import _action, _matching_history, check_offline_action
from reops_agent.verification import verify
from reops_agent.advisory import structured_observation
from .vikunja_target import TARGET_ID, VikunjaDocker, stopped_database
from .vikunja_actions import VikunjaRecoveryTool
from .a_docker import TargetError
from .b_a_port import WorkbenchAPort
from .a_monitor import now

PROFILE = "vikunja_database_start"
BUSINESS_ENDPOINT = "/api/v1/tasks/{task_id}"
POLICY_VERSION = "vikunja-start-v1"


def safe_vikunja_observation(observation, *, allow_unavailable=False):
    """Shared allowlist for live and explicitly verified historical projections."""
    validate("observation", observation)
    if (observation["system"].get("target_id") != TARGET_ID
            or observation["system"].get("name") != TARGET_ID
            or observation["system"].get("environment") != "isolated-demo"
            or set(observation["services"]) != {"api", "postgres", "business"}
            or observation["request"].get("method") != "GET"
            or observation["request"].get("endpoint") != BUSINESS_ENDPOINT
            or type(observation["request"].get("business_passed")) not in (bool, type(None))
            or observation.get("sampling_error") is not None and not allow_unavailable):
        raise ValueError("b_vikunja_observation_unavailable_or_invalid")
    safe = structured_observation(observation)
    safe["system"] = {"name": TARGET_ID, "environment": "isolated-demo", "target_id": TARGET_ID}
    safe["request"].update(endpoint=BUSINESS_ENDPOINT, business_passed=observation["request"]["business_passed"])
    safe["services"]["business"] = {"status": observation["services"]["business"]["status"]}
    if observation["request"].get("failure_kind") == "read_timeout":
        safe["request"]["failure_kind"] = "read_timeout"
    safe["target_health"] = observation.get("target_health", "unknown")
    safe["sampling_error"] = "vikunja_observation_unavailable" if observation.get("sampling_error") else None
    safe["sample_completed_at"] = observation["sample_completed_at"]
    safe["business"] = {key: observation.get("business", {}).get(key) is True
        for key in ("database_sql_valid", "probe_write_confirmed", "probe_read_valid")}
    validate("observation", safe)
    return safe


def current_business_healthy(observation):
    return (observation["system"].get("target_id") == TARGET_ID
        and observation.get("sampling_error") is None
        and observation.get("target_health") == "healthy"
        and all(observation["services"].get(name, {}).get("status") == "healthy" for name in ("api", "postgres", "business"))
        and observation["request"].get("status_code") == 200
        and observation["request"].get("business_passed") is True
        and all(type(observation["metrics"].get(name)) is int and observation["metrics"][name] == 1 for name in ("api_up", "postgres_up")))


def check_vikunja_start(action, observation):
    validate("recovery_action", action)
    validate("observation", observation)
    safety = check_offline_action(action, observation, retry_limit=1)
    allowed = (safety["allowed"] and (action["action"], action["target"]) == ("start_service", "postgres")
        and not action["parameters"] and action["requires_approval"] is False and action["risk"] <= .2
        and all(action[key] == observation[key] for key in ("incident_id", "trace_id"))
        and observation["system"].get("name") == TARGET_ID
        and observation["system"].get("environment") == "isolated-demo"
        and observation["request"].get("endpoint") == BUSINESS_ENDPOINT
        and stopped_database(observation))
    return {"allowed": bool(allowed), "reason": "vikunja_stopped_database_start" if allowed else "vikunja_current_evidence_rejected",
        "action": action["action"], "target": action["target"]}


def plan_vikunja_start(diagnosis, observation, history=(), *, model_suggestion=None):
    action = _action(diagnosis, "start_service", "postgres", {}, .8, "vikunja_stopped_database_start")
    adopted = [item["event_id"] for item in history if item.get("recovered") is True
        and _matching_history(item, diagnosis, {}, ("start_service", "postgres", {}))]
    action["reason"] = "Vikunja fixed stopped-database candidate; current Safety and original A authorization remain required"
    action["decision_basis"].update(strategy=PROFILE, target_id=TARGET_ID, offline_only=False,
        history_event_ids=adopted, model_suggested_action=deepcopy(model_suggestion), model_action_applied=False)
    validate("recovery_action", action)
    return action


def verify_vikunja_business(observation):
    diagnosis, result, _ = verify(observation)
    business = observation.get("business", {})
    healthy = (current_business_healthy(observation) and business.get("database_sql_valid") is True
        and business.get("probe_write_confirmed") is True and business.get("probe_read_valid") is True)
    result.update(status="recovered" if healthy else "not_recovered", business_request_passed=bool(healthy))
    result["evidence"].append("Vikunja task read, SQL and new-task write/read confirmed=" + str(bool(healthy)))
    return diagnosis, result, bool(healthy)


class VikunjaAPort(WorkbenchAPort):
    """No new executor. Original tool validates full identity and consumes the grant."""
    target_id = TARGET_ID
    _check = staticmethod(check_vikunja_start)

    def __init__(self, monitor):
        self.monitor = monitor
        self.tool = VikunjaRecoveryTool(monitor)
        self.offline_only = not isinstance(monitor.backend, VikunjaDocker)
        self.executed_context = None
        self.probe_attempted = self.probe_written = False
        self.verified_samples = []
        self.last_result = None

    @staticmethod
    def _target(target_id):
        if target_id != TARGET_ID:
            raise TargetError("b_vikunja_target_mismatch")

    def scope(self, target_id):
        value = super().scope(target_id)
        value["app_started_at"] = self.monitor.backend.inspect().app_started_at
        value["b_policy_version"] = POLICY_VERSION
        return value

    def execute(self, target_id, action, observation, authorization):
        result = super().execute(target_id, action, observation, authorization)
        self.last_result = deepcopy(result.execution.get("a_recovery_result")) if result.execution else None
        if result.status == "succeeded":
            self.executed_context = (action["incident_id"], action["trace_id"])
            self.probe_attempted = self.probe_written = False
            self.monitor.business.probe_id = self.monitor.business.probe_title = None
        return result

    def observe(self, target_id, context):
        observation = super().observe(target_id, context)
        if self.executed_context != (context["incident_id"], context["trace_id"]) or not current_business_healthy(observation):
            return observation
        # These writes are reachable only after an actually succeeded authorized A action.
        current = self.monitor.backend.inspect()
        identity, _ = self.monitor.action_scope()
        if current.identity != identity:
            raise TargetError("b_vikunja_verify_identity_changed")
        sql = self.monitor.backend.sql_probe(identity)
        if sql and not self.probe_attempted:
            self.probe_attempted = True  # Never retry an uncertain business write.
            self.probe_written = self.monitor.business.write_probe() is True
        read = self.monitor.business.read_probe() is True if self.probe_written else False
        observation["business"].update(database_sql_valid=sql is True,
            probe_write_confirmed=self.probe_written, probe_read_valid=read)
        observation["sample_completed_at"] = now()
        self.verified_samples.append(deepcopy(observation))
        return observation


def policy():
    from .b_runtime import TargetPolicy
    return TargetPolicy(TARGET_ID, TARGET_ID, "isolated-demo", allowed_actions=(("start_service", "postgres"),),
        business_endpoint=BUSINESS_ENDPOINT, profile=PROFILE)


def run_approved_recovery(store, monitor, gate, observation, context):
    """Only the already-approved demo calls this. Never injects a fault or calls a model."""
    from .b_runtime import BRuntime
    port = VikunjaAPort(monitor)
    runtime = BRuntime(store, port, policy(), gate=gate, provider=None, execute=True,
        a_timeout=30, action_timeout=90, sample_max_age=60, verify_timeout=45)
    identifier = runtime.notify(TARGET_ID, observation, context=context)
    if identifier is None:
        raise ValueError("b_vikunja_existing_fault_requires_review")
    body, _ = store.get(identifier)
    saved = [record for record, _ in store.experiences(TARGET_ID) if record["incident_id"] == identifier]
    verified = body["verification"]["status"] == "passed"
    completed = verified and body["status"] == "recovered" and any(record["status"] == "verified" for record in saved)
    samples = port.verified_samples[-2:]
    # Keep the original report's write marker semantics: first writes, second reads.
    for index, sample in enumerate(samples):
        sample["business"]["write_valid"] = index == 0 and port.probe_written
    return {"passed": completed, "recovery_verified": verified, "b_agent_closed_loop": completed,
        "model_calls": 0, "diagnosis_source": body["diagnosis_source"],
        "execution_result": port.last_result, "verify_observations": samples,
        "memory_written": bool(saved), "experience_ids": body["experience_ids"],
        "b_profile": PROFILE, "model_mode": "off_under_original_zero_model_approval"}
