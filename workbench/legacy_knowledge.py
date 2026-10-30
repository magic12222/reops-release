"""只读旧B Memory目录：保留声明与缺口，不重建消息、不迁移原件或放宽复用策略。"""
from hashlib import sha256
import json

from reops_agent.contracts import validate
from .b_privacy import redact
from .contracts import AgentFeed, Incident, Experience, Target

FILES = ("docker-recovery-memory.jsonl", "phase7c-memory.jsonl", "phase7d-memory.jsonl", "researchloop-memory.jsonl")


def historical_targets(incidents):
    ids = sorted({item.target_id for item in incidents if item.target_id.startswith("history:")})
    return [Target(id=identifier, name="Historical · " + identifier.removeprefix("history:"), runtime="docker",
        health="unknown", monitoring="not_connected", observed_at=None, components=[], allowed_actions=[]) for identifier in ids]


def read_legacy_knowledge(root):
    incidents, experiences, seen, links = [], [], {}, []
    for filename in FILES:
        path = root / "runtime" / filename
        if not path.is_file():
            continue
        payload = path.read_bytes()
        if payload and not payload.endswith(b"\n"):
            raise ValueError("legacy_memory_incomplete")
        for line_number, line in enumerate(payload.splitlines(), 1):
            original = json.loads(line)
            validate("agent_event", original)
            fingerprint = sha256(line).hexdigest()
            if original["event_id"] in seen:
                if seen[original["event_id"]] != fingerprint:
                    raise ValueError("legacy_memory_event_conflict")
                continue
            seen[original["event_id"]] = fingerprint
            data = original["data"]
            if original["stage"] != "experience_update" or not isinstance(data.get("observation"), dict):
                continue
            # Only existing fixed Memory files; explicit fixtures never enter the real library.
            if data.get("real_observation") is False or data.get("source") in {"offline_fixture", "simulation"}:
                continue
            safe = redact(data)
            observation, diagnosis, action = safe["observation"], safe.get("diagnosis", {}), safe.get("recovery_action", {})
            system = observation.get("system", {}).get("name")
            if system not in {"reops-lab", "reops-researchloop-demo"}:
                continue
            for document in (observation, diagnosis, action):
                if document and any(document.get(key) != original[key] for key in ("incident_id", "trace_id")):
                    raise ValueError("legacy_memory_context_conflict")
            suffix = sha256(original["event_id"].encode()).hexdigest()[:24]
            identifier, exp_id, event_id = "legacy-incident-" + suffix, "legacy-experience-" + suffix, "legacy-event-" + suffix
            target = "history:" + system
            verification = data.get("verification_result", {})
            verified = (data.get("real_observation") is True and data.get("recovered") is True
                and data.get("recovery_verified") is True and verification.get("status") == "recovered"
                and all(verification.get(key) is True for key in ("health_check_passed", "fault_cleared", "business_request_passed")))
            failed = data.get("real_observation") is True and data.get("recovered") is False
            status = "verified" if verified else "failed" if failed else "unverified"
            if isinstance(data.get("experience"), dict) and data["experience"].get("status") == "retired":
                status = "retired"
            conditions = ["source=historical_b_memory", "source_file=runtime/" + filename,
                f"source_line={line_number}", "source_sha256=" + fingerprint, "source_event=" + event_id,
                "original_event=" + original["event_id"], "original_incident=" + original["incident_id"],
                "original_real_observation=" + str(data.get("real_observation", "unknown")),
                "original_diagnosis_source=" + str(data.get("diagnosis_source", "unknown")),
                "original_model_calls=" + str(data.get("model_calls", "unknown")),
                "Historical record only; not offered to dependency or legacy execution policies"]
            for service, value in observation.get("services", {}).items():
                if isinstance(value, dict): conditions.append(f"service={service};status={value.get('status', 'unknown')}")
            event = {"id":event_id, "sequence":0, "timestamp":original["timestamp"], "stage":"experience_update",
                "status":"failed" if failed else "succeeded", "title":"Original B Memory record",
                "detail":"Read-only historical B Memory. Original event, incident and trace remain authoritative; model messages are not reconstructed.",
                "evidence":conditions}
            experiences.append(Experience(id=exp_id,target_id=target,incident_id=identifier,title="Historical B · " + str(diagnosis.get("failure_type") or "recorded outcome"),
                symptom=str(diagnosis.get("failure_type") or "Not recorded"),root_cause=str(diagnosis.get("root_cause") or "Not recorded"),
                action=str(action.get("action") or "Not recorded") + "(" + str(action.get("target") or "unknown") + ")", conditions=conditions,status=status))
            source = data.get("diagnosis_source")
            links.append((identifier, original["event_id"], data.get("memory_hit_event_ids", []) if source in {"experience", "memory/rule-supported"} else []))
            incidents.append(Incident(id=identifier,target_id=target,trace_id=original["trace_id"],title="Historical B Memory · " + system,
                started_at=observation.get("timestamp", original["timestamp"]),status="recovered" if verified else "failed" if failed else "unknown",
                diagnosis_source="model" if source == "provider" else source if source in {"rule","model"} else "unknown",summary="Historical B Memory; original model calls=" + str(data.get("model_calls", "unknown")) + ". Full messages are unavailable in this projection.",
                events=[event],model_calls=[],experience_ids=[exp_id],verification={"status":"passed" if verified else "failed" if failed else "unknown", "checks":["Original verification status=" + str(verification.get("status", "unknown"))]}))
    origins = {original_event: experiences[index] for index, (_, original_event, _) in enumerate(links)}
    for index, (_, _, references) in enumerate(links):
        if not isinstance(references, list):
            continue
        exact = [origins[key].id for key in references if isinstance(key, str) and key in origins
                 and origins[key].target_id == incidents[index].target_id and origins[key].id != experiences[index].id]
        if exact:
            incidents[index].diagnosis_source = "experience"
            incidents[index].experience_ids.extend(exact)
    return AgentFeed(status="ready" if incidents else "not_connected", incidents=incidents, experiences=experiences)
