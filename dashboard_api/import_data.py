"""Explicit-provenance, offline import of existing B JSONL evidence."""

import argparse
import json
import hashlib
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .normalize import from_experience_update, from_trace_journal
from .store import Store
from .benchmark import _pairs, _invalid_constant


def _merge(store: Store, run, events):
    previous = store.get_run(run.id)
    if previous is None or previous.metadata.get("ingest_kind") == run.metadata.get("ingest_kind"):
        return run, events
    old_events = store.list_events(run.id)
    if previous.metadata.get("ingest_kind") == "combined":
        metadata = previous.metadata
        if run.metadata["ingest_kind"] == "trace_journal":
            journal_run, journal_events = run, events
            experience_run = replace(previous, status=metadata["experience_status"],
                                     success=metadata["experience_success"],
                                     finished_at=metadata["experience_finished_at"])
            experience_events = [event for event in old_events if event.origin == "experience_update"]
        else:
            journal_run = replace(previous, status=metadata["journal_status"],
                                  success=metadata["journal_success"],
                                  finished_at=metadata["journal_finished_at"])
            journal_events = [event for event in old_events if event.origin == "trace_journal"]
            experience_run, experience_events = run, events
    elif previous.metadata.get("ingest_kind") == "trace_journal":
        journal_run, journal_events = previous, old_events
        experience_run, experience_events = run, events
    else:
        journal_run, journal_events = run, events
        experience_run, experience_events = previous, old_events
    original = next((event for event in experience_events if event.origin == "experience_update"), None)
    if original is None:
        raise ValueError("experience import missing original event")
    merged_events = list(journal_events)
    if not any(event.event_id == original.event_id for event in merged_events):
        position = next((index for index, event in enumerate(merged_events)
                         if event.data.get("event_id") == original.event_id), None)
        if position is None:
            original_time = datetime.fromisoformat(original.timestamp.replace("Z", "+00:00"))
            position = next((index for index, event in enumerate(merged_events)
                             if event.timestamp and datetime.fromisoformat(
                                 event.timestamp.replace("Z", "+00:00")) > original_time),
                            len(merged_events))
        merged_events.insert(position, original)
    merged_events = [replace(event, ordinal=index) for index, event in enumerate(merged_events)]
    if journal_run.status not in {"unknown", "diagnosing"} and experience_run.status not in {"unknown", "diagnosing"}:
        if (journal_run.status, journal_run.success) != (experience_run.status, experience_run.success):
            status, success, finished_at = "inconclusive", None, None
        else:
            status, success, finished_at = (journal_run.status, journal_run.success,
                                            journal_run.finished_at or experience_run.finished_at)
    elif journal_run.status not in {"unknown", "diagnosing"}:
        status, success, finished_at = journal_run.status, journal_run.success, journal_run.finished_at
    else:
        status, success, finished_at = experience_run.status, experience_run.success, experience_run.finished_at
    merged_run = replace(journal_run, status=status, success=success, finished_at=finished_at,
                         case_id=journal_run.case_id or experience_run.case_id,
                         action_count=experience_run.action_count,
                         metadata={"ingest_kind": "combined", "ingest_kinds": ["trace_journal", "experience_update"],
                                   "original_event_id": original.event_id,
                                   "journal_status": journal_run.status,
                                   "journal_success": journal_run.success,
                                   "journal_finished_at": journal_run.finished_at,
                                   "experience_status": experience_run.status,
                                   "experience_success": experience_run.success,
                                   "experience_finished_at": experience_run.finished_at})
    return merged_run, merged_events


def import_jsonl(store: Store, path: str | Path, *, kind: str, source: str) -> int:
    raw = Path(path).read_bytes()
    fingerprint = hashlib.sha256(raw).hexdigest()
    documents = [json.loads(line, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
                 for line in raw.decode("utf-8-sig").splitlines()
                 if line.strip()]
    if kind == "trace-journal":
        groups = defaultdict(list)
        for document in documents:
            groups[(document["incident_id"], document["trace_id"])].append(document)
        for group in groups.values():
            seen = set()
            previous = None
            for event in group:
                if event["event_id"] in seen or event.get("parent_event_id") != previous:
                    raise ValueError("duplicate event or broken journal parent chain")
                seen.add(event["event_id"])
                previous = event["event_id"]
        bundles = [from_trace_journal(group, source=source) for group in groups.values()]
    elif kind == "experience-jsonl":
        bundles = [from_experience_update(document, source=source) for document in documents]
    else:
        raise ValueError("unsupported import kind")
    if len({run.id for run, _ in bundles}) != len(bundles):
        raise ValueError("one import file contains duplicate incident/trace/source bundles")
    with store._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for run, events in bundles:
            previous = store.get_run(run.id)
            fingerprints = set(previous.metadata.get("import_file_sha256", []) if previous else [])
            fingerprints.add(fingerprint)
            run, events = _merge(store, run, events)
            run = replace(run, metadata={**run.metadata, "import_file_sha256": sorted(fingerprints)})
            store.put_bundle(run, events, connection=db)
    return len(bundles)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=("trace-journal", "experience-jsonl"))
    parser.add_argument("--source", required=True, choices=("real", "offline_fixture", "simulation"))
    args = parser.parse_args()
    print(json.dumps({"runs_imported": import_jsonl(Store(args.db), args.path,
                                                      kind=args.kind, source=args.source)}))


if __name__ == "__main__":
    main()
