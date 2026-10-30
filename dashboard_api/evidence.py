"""C6 inventory of committed evidence, not a real benchmark or a Verify engine."""

import hashlib
import json

from .models import SOURCES


def _text(value):
    return value if isinstance(value, str) and value else None


def inspect_trace(run, events, experiments):
    journal = [e for e in events if e.origin == "trace_journal"]
    steps = {}
    for event in journal:
        steps.setdefault(_text(event.data.get("step")), []).append(event)
    gaps = ["original_report_unavailable", "source_not_authenticated",
            "strategy_label_unavailable", "model_usage_unavailable", "latency_boundary_unconfirmed"]
    conflicts = []
    previous = None
    for event in journal:
        if event.parent_event_id != previous:
            conflicts.append("journal_parent_chain")
        previous = event.event_id
    linked = [e for e in experiments if e.get("source") == run.source
              and (e.get("incident_id"), e.get("trace_id")) == (run.incident_id, run.trace_id)]
    if len(linked) > 1:
        conflicts.append("multiple_experiments")
    experiment = linked[0] if len(linked) == 1 else None
    if experiment is None:
        gaps.append("experiment_ground_truth_unavailable")

    def single(step):
        values = steps.get(step, [])
        if len(values) > 1:
            conflicts.append(f"multiple_{step}")
        return values[0].data if len(values) == 1 else {}

    execution = single("executor_result")
    outcome = _text(execution.get("execution_outcome"))
    if outcome not in {"succeeded", "failed", "unknown", "not_run"}:
        outcome = None
        gaps.append("execution_result_unavailable")
    result = execution.get("result")
    if isinstance(result, dict):
        if (result.get("incident_id"), result.get("trace_id")) != (run.incident_id, run.trace_id):
            conflicts.append("execution_correlation")
        if outcome == "succeeded" and (result.get("execution_status") != "succeeded"
                or type(result.get("exit_code")) is not int or result["exit_code"] != 0):
            conflicts.append("execution_success_conflict")
    elif outcome == "succeeded":
        conflicts.append("execution_result_missing")
    verify = single("verify")
    verification = verify.get("verification")
    verification_status = _text(verification.get("status")) if isinstance(verification, dict) else None
    if verification_status not in {"recovered", "not_recovered", "inconclusive", "not_run"}:
        verification_status = None
        gaps.append("verify_result_unavailable")
    samples = []
    for event in steps.get("post_recovery_observation", []):
        observation = event.data.get("observation")
        if not isinstance(observation, dict):
            gaps.append("verify_observation_missing")
            continue
        if (observation.get("incident_id"), observation.get("trace_id")) != (run.incident_id, run.trace_id):
            conflicts.append("verify_correlation")
        samples.append({"event_id": event.event_id, "observation_id": _text(observation.get("observation_id")),
                        "timestamp": _text(observation.get("timestamp"))})
    ids = [s["observation_id"] for s in samples if isinstance(s["observation_id"], str) and s["observation_id"]]
    if len(ids) != len(set(ids)):
        conflicts.append("reused_verify_observation")
    if len(set(ids)) < 2:
        gaps.append("two_independent_verify_samples_unavailable")
    # Different IDs alone do not prove fresh sampling or two healthy Verify results.
    gaps.append("independent_verify_not_established")
    if verify.get("recovery_verified") is True and (outcome != "succeeded" or verification_status != "recovered"):
        conflicts.append("reported_recovery_conflict")
    if (run.metadata.get("ingest_kind") == "combined"
            and run.metadata.get("journal_success") is not None
            and run.metadata.get("experience_success") is not None
            and run.metadata["journal_success"] != run.metadata["experience_success"]):
        conflicts.append("journal_memory_conflict")
    action = single("planner").get("action")
    action = action if isinstance(action, dict) else {}
    canonical = json.dumps([e.to_dict() for e in events], ensure_ascii=False,
                           sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {"run_id": run.id, "source": run.source, "incident_id": run.incident_id,
            "trace_id": run.trace_id, "case_id": run.case_id,
            "experiment_id": experiment["id"] if experiment else None,
            "scenario": experiment.get("scenario") if experiment else None,
            "ground_truth": experiment.get("ground_truth") if experiment else None,
            "strategy": None, "action": _text(action.get("action")), "target": _text(action.get("target")),
            "event_count": len(events), "journal_event_count": len(journal),
            "execution_outcome_reported": outcome, "verification_status_reported": verification_status,
            "verify_samples": samples, "independent_verify": None,
            "real_model_calls": None, "token_usage": None, "api_cost": None, "recovery_latency_ms": None,
            "eligible_for_evaluation": False, "gaps": sorted(set(gaps)), "conflicts": sorted(set(conflicts)),
            "provenance": {"source_assertion": run.source, "authenticated": False,
                           "import_file_sha256": run.metadata.get("import_file_sha256", []),
                           "normalized_evidence_sha256": hashlib.sha256(canonical.encode()).hexdigest()}}


def evidence_page(store, source, limit=50, offset=0):
    if source not in SOURCES:
        raise ValueError("invalid source")
    # Keep the list, events and experiment links in one committed SQLite snapshot.
    with store._connect() as db:
        db.execute("BEGIN")
        total = db.execute("SELECT COUNT(*) FROM runs WHERE source=?", (source,)).fetchone()[0]
        rows = db.execute("SELECT * FROM runs WHERE source=? ORDER BY started_at DESC,id DESC LIMIT ? OFFSET ?",
                          (source, limit, offset)).fetchall()
        experiments = [json.loads(r[0]) for r in db.execute("SELECT body FROM experiments")]
        items = []
        for row in rows:
            run = store._read_run(row)
            events = [store._read_event(r) for r in db.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY ordinal", (run.id,))]
            items.append(inspect_trace(run, events, experiments))
    return {"source": source, "items": items, "total": total, "limit": limit, "offset": offset,
            "evaluation_sample_count": 0, "recovery_success_rate": None,
            "status": "evidence_only" if total else "no_evidence"}
