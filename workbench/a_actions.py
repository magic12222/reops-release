"""A's single-target tool proposal; no HTTP route or automatic authorization installed."""

from copy import deepcopy
import time

from reops_agent.authorization import AuthorizationGate, interactive_confirm

from .a_docker import DockerTarget, TARGET_ID, TargetError
from .a_monitor import now, validate_shared


def _contains_command(value):
    if isinstance(value, dict):
        return any(key.lower() in {"command", "shell", "script"} or _contains_command(item)
                   for key, item in value.items())
    return isinstance(value, list) and any(_contains_command(item) for item in value)


class RecoveryTool:
    def __init__(self, monitor):
        self.monitor = monitor

    def _accepts_live_gate(self, gate):
        return type(gate) is AuthorizationGate and gate.confirm is interactive_confirm

    def prepare(self, action):
        """Synchronous read-only binding for the existing Gate.request('recovery', binding)."""
        action = deepcopy(action)
        validate_shared("recovery_action", action)
        if (_contains_command(action) or action["action"] != "start_service" or action["target"] != "web"
                or action["parameters"] or action["requires_approval"] or action["risk"] >= 0.7):
            raise TargetError("action_not_allowed")
        identity, generation = self.monitor.action_scope()
        current = self.monitor.backend.inspect()
        if current.identity != identity or current.running or current.status != "exited":
            raise TargetError("target_changed_or_not_stopped")
        return {"scope": identity.binding(), "monitor_generation": generation,
                "action": action, "max_actions": 1}

    def execute(self, action, *, gate=None, grant=None):
        """Return shared RecoveryResult. Never requests, fabricates or renews a grant."""
        action = deepcopy(action)
        validate_shared("recovery_action", action)
        started = time.monotonic()
        from uuid import uuid4
        result = {"schema_version": "1.0", "result_id": "result-a-" + uuid4().hex,
                  "incident_id": action["incident_id"], "trace_id": action["trace_id"],
                  "case_id": action.get("case_id"), "action_id": action["action_id"],
                  "timestamp": now(), "execution_status": "rejected", "exit_code": None,
                  "stdout": "", "stderr": "action_not_authorized", "duration_ms": 0,
                  "post_observation_id": None, "target_id": getattr(self.monitor, "target_id", TARGET_ID), "mutation_attempted": False,
                  "verification": {"status": "not_run", "checked_at": None,
                      "health_check_passed": None, "fault_cleared": None,
                      "business_request_passed": None, "evidence": []}}
        with self.monitor.control:
            try:
                binding = self.prepare(action)
                if not isinstance(gate, AuthorizationGate):
                    raise TargetError("original_authorization_required")
                if isinstance(self.monitor.backend, DockerTarget) and not self._accepts_live_gate(gate):
                    raise TargetError("live_tool_requires_original_interactive_gate")
                # Original ledger reserves action_id before any mutation; uncertain attempts cannot replay.
                gate.consume(grant, "recovery", binding, operation_id="a-workbench:" + action["action_id"])
            except Exception:
                result["stderr"] = "action_rejected_check_scope_monitoring_and_authorization"
            else:
                identity = self.monitor.begin_action(binding["monitor_generation"])
                try:
                    self.monitor.backend.start(identity)
                    result.update(execution_status="succeeded", exit_code=0, stderr="", mutation_attempted=True)
                except TargetError as exc:
                    result.update(execution_status="failed", stderr="start_failed_or_uncertain",
                                  mutation_attempted=exc.mutation_attempted)
                except Exception:
                    result.update(execution_status="failed", stderr="start_failed_or_uncertain", mutation_attempted=None)
                try:
                    post = self.monitor.observe(action["incident_id"], action["trace_id"], action.get("case_id"))
                    result["post_observation_id"] = post["observation_id"]
                    alive = post["services"]["api"]["status"]
                    healthy = None if alive == "unknown" else alive == "healthy"
                    business = post["request"]["business_passed"]
                    result["verification"] = {
                        "status": "not_recovered" if healthy is False or business is False else
                                  "inconclusive" if healthy is None or business is None else "recovered",
                        "checked_at": post["sample_completed_at"], "health_check_passed": healthy,
                        "fault_cleared": None, "business_request_passed": business,
                        "evidence": ["Fresh Observation " + post["observation_id"],
                                     "A measures HTTP/business health; B confirms root cause and final Verify"]}
                except Exception:
                    result["verification"]["status"] = "inconclusive"
        result["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
        validate_shared("recovery_result", result)
        return result
