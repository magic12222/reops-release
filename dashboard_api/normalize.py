"""Normalize the two existing B trajectory shapes without inventing evidence."""

from hashlib import sha256
from dataclasses import replace
from typing import Any

from reops_agent.contracts import validate
from reops_agent.credential_handling import redact_persistent

from .models import Event, Run, SOURCES

STEP_STAGE = {
    "Observation": "observe",
    "Failure detected": "failure_detection",
    "Diagnosis": "localization",
    "RCA evidence": "root_cause_analysis",
    "Memory evidence": "root_cause_analysis",
    "Nexent recommendation": "root_cause_analysis",
    "Safety decision": "recovery_decision",
    "Action": "recovery_decision",
    "Executor started": "recovery_execution",
    "Executor finished": "recovery_execution",
    "Execution": "recovery_execution",
    "Verification": "verification",
    "Final status": "verification",
}


def _source(event: dict[str, Any], source: str):
    if source not in SOURCES:
        raise ValueError("source must be explicitly real, offline_fixture or simulation")
    data = event.get("data", {})
    if source == "real" and (data.get("offline_only") is True or
                             data.get("real_model") is False or
                             data.get("real_observation") is False):
        raise ValueError("offline evidence cannot be labeled real")


def _id(incident_id: str, trace_id: str, source: str) -> str:
    digest = sha256(f"{source}\0{incident_id}\0{trace_id}".encode()).hexdigest()[:24]
    return f"run-{digest}"


def _case_id(events: list[dict[str, Any]]) -> str | None:
    ids = set()
    for event in events:
        if event.get("case_id") is not None:
            ids.add(event["case_id"])
        data = event.get("data", {})
        for name in ("observation", "recovery_action", "action", "result"):
            nested = data.get(name)
            if isinstance(nested, dict) and nested.get("case_id") is not None:
                ids.add(nested["case_id"])
    if len(ids) > 1:
        raise ValueError("conflicting case_id in one trace")
    return next(iter(ids), None)


def _final(event: dict[str, Any]):
    data = event["data"]
    final_status = data.get("final_status")
    diagnosis = data.get("diagnosis", {})
    verification = data.get("verification_result", {})
    execution = data.get("execution_result", {})
    if (final_status == "recovered" and diagnosis.get("failure_detected") is True
            and verification.get("status") == "recovered"
            and execution.get("execution_status") == "succeeded"):
        return "recovered", True
    if final_status in {"max_attempts_reached", "no_safe_candidate", "safety_rejected"}:
        return "failed", False
    if final_status in {"dry_run", "healthy"}:
        return "inconclusive", None
    if final_status == "retry_pending":
        return "diagnosing", None
    if final_status is not None:
        return "inconclusive", None
    return "unknown", None


def _journal_status(raw_events: list[dict[str, Any]]):
    for raw in reversed(raw_events):
        if raw["stage"] == "experience_update" and "final_status" in raw["data"]:
            status, success = _final(raw)
            return status, success, raw["timestamp"] if status not in {"unknown", "diagnosing"} else None
        if raw["stage"] == "verification" and "recovery_verified" in raw["data"]:
            verification = raw["data"].get("verification", {})
            if (raw["data"]["recovery_verified"] is True and raw["status"] == "success"
                    and verification.get("status") == "recovered"):
                return "recovered", True, raw["timestamp"]
            if verification.get("status") == "not_recovered":
                return "failed", False, raw["timestamp"]
            return "inconclusive", None, raw["timestamp"]
    last = raw_events[-1]
    if last["status"] == "waiting_human":
        return "waiting_authorization", None, None
    if last["status"] == "started":
        status = {"observe": "observing", "failure_detection": "diagnosing",
                  "localization": "diagnosing", "root_cause_analysis": "diagnosing",
                  "recovery_execution": "executing", "verification": "verifying"}.get(last["stage"], "unknown")
        return status, None, None
    return "unknown", None, None


def from_trace_journal(raw_events: list[dict[str, Any]], *, source: str) -> tuple[Run, list[Event]]:
    if not raw_events:
        raise ValueError("empty TraceJournal")
    for raw in raw_events:
        validate("agent_event", raw)
        _source(raw, source)
    first = raw_events[0]
    identity = (first["incident_id"], first["trace_id"])
    if any((raw["incident_id"], raw["trace_id"]) != identity for raw in raw_events):
        raise ValueError("TraceJournal import must contain exactly one incident/trace")
    case_id = _case_id(raw_events)
    run_id = _id(*identity, source)
    events = [Event(event_id=raw["event_id"], run_id=run_id, incident_id=identity[0],
                    trace_id=identity[1], case_id=raw.get("case_id") or case_id, ordinal=index,
                    parent_event_id=raw.get("parent_event_id"), stage=raw["stage"],
                    status=raw["status"], timestamp=raw["timestamp"],
                    message=redact_persistent(raw["message"]), source=source,
                    origin="trace_journal", data=redact_persistent(raw["data"]),
                    original_event_id=raw["event_id"])
              for index, raw in enumerate(raw_events)]
    # A journal may stop mid-flight. Only an explicit final experience event can close the run.
    status, success, finished_at = _journal_status(raw_events)
    run = Run(id=run_id, incident_id=identity[0], trace_id=identity[1], case_id=case_id,
              source=source, status=status, started_at=first["timestamp"],
              finished_at=finished_at,
              success=success, metadata={"ingest_kind": "trace_journal"})
    return run, events


def from_experience_update(raw: dict[str, Any], *, source: str) -> tuple[Run, list[Event]]:
    validate("agent_event", raw)
    _source(raw, source)
    if raw["stage"] != "experience_update":
        raise ValueError("expected experience_update")
    trace = raw["data"].get("decision_trace")
    if trace is None and isinstance(raw["data"].get("trajectory"), list):
        return _from_online_experience(raw, source=source)
    if not isinstance(trace, list) or not trace:
        raise ValueError("experience_update has no decision_trace")
    run_id = _id(raw["incident_id"], raw["trace_id"], source)
    events = []
    for index, step in enumerate(trace):
        if not isinstance(step, dict) or step.get("stage") not in STEP_STAGE or "data" not in step:
            raise ValueError("unknown or malformed decision_trace step")
        event_id = f"{raw['event_id']}:step:{index}"
        events.append(Event(event_id=event_id, run_id=run_id,
                            incident_id=raw["incident_id"], trace_id=raw["trace_id"],
                            case_id=raw.get("case_id"), ordinal=index,
                            parent_event_id=events[-1].event_id if events else raw.get("parent_event_id"),
                            stage=STEP_STAGE[step["stage"]], status=None, timestamp=None,
                            message=step["stage"], source=source, origin="decision_trace",
                            original_event_id=raw["event_id"],
                            data={"step": step["stage"], "value": redact_persistent(step["data"])}))
    events.append(Event(event_id=raw["event_id"], run_id=run_id,
                        incident_id=raw["incident_id"], trace_id=raw["trace_id"],
                        case_id=raw.get("case_id"), ordinal=len(events),
                        parent_event_id=raw.get("parent_event_id"), stage=raw["stage"],
                        status=raw["status"], timestamp=raw["timestamp"],
                        message=redact_persistent(raw["message"]), source=source,
                        origin="experience_update", original_event_id=raw["event_id"],
                        data=redact_persistent(raw["data"])))
    status, success = _final(raw)
    observation = raw["data"].get("observation", {})
    run = Run(id=run_id, incident_id=raw["incident_id"], trace_id=raw["trace_id"],
              case_id=raw.get("case_id"), source=source, status=status,
              started_at=observation.get("timestamp"),
              finished_at=raw["timestamp"] if status != "unknown" else None,
              action_count=1 if raw["data"].get("execution_result", {}).get("execution_status") in
              {"succeeded", "failed"} else 0 if "execution_result" in raw["data"] else None,
              success=success, metadata={"ingest_kind": "experience_update",
                                        "original_event_id": raw["event_id"]})
    return run, events


def _from_online_experience(raw: dict[str, Any], *, source: str) -> tuple[Run, list[Event]]:
    """Read B's durable online Memory without synthesizing legacy decision steps."""
    from reops_agent.memory import _validate_memory_payload

    try:
        _validate_memory_payload(raw)
    except (ValueError, TypeError, KeyError):
        raise ValueError("invalid online memory payload") from None
    trajectory = raw["data"]["trajectory"]
    previous = None
    seen = {raw["event_id"]}
    for event in trajectory:
        validate("agent_event", event)
        if event["event_id"] in seen or event.get("parent_event_id") != previous:
            raise ValueError("duplicate event or broken journal parent chain")
        seen.add(event["event_id"])
        previous = event["event_id"]
    if not trajectory or raw.get("parent_event_id") != previous:
        raise ValueError("online memory parent does not match trajectory")
    case_id = _case_id([*trajectory, raw])
    run, events = from_trace_journal(trajectory, source=source)
    if (run.incident_id, run.trace_id) != (raw["incident_id"], raw["trace_id"]):
        raise ValueError("online memory trajectory correlation mismatch")
    # Only B's explicit verified execution can confirm recovery; cleanup is separate.
    data = raw["data"]
    if run.status == "waiting_authorization":
        # The Memory is a completed attempt; an earlier challenge is no longer pending.
        run = replace(run, status="unknown", success=None, finished_at=None)
    if run.success is True and not all(data.get(key) is True for key in
            ("recovered", "recovery_verified", "recovery_executed", "executor_called")):
        run = replace(run, status="inconclusive", success=None, finished_at=None)
    events = [replace(event, case_id=case_id) for event in events]
    events.append(Event(event_id=raw["event_id"], run_id=run.id,
        incident_id=run.incident_id, trace_id=run.trace_id, case_id=case_id,
        ordinal=len(events), parent_event_id=raw.get("parent_event_id"),
        stage=raw["stage"], status=raw["status"], timestamp=raw["timestamp"],
        message=redact_persistent(raw["message"]), source=source,
        origin="experience_update", original_event_id=raw["event_id"],
        data=redact_persistent(data)))
    return replace(run, case_id=case_id,
        metadata={"ingest_kind": "experience_update", "format": "online_trajectory",
                  "original_event_id": raw["event_id"]}), events
