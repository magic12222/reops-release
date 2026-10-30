"""检索已验证依赖经验供模型参考；没有执行或批准能力。"""
from datetime import datetime
import time

from workbench.b_store import now, read_feed

PROFILE = "dependency-knowledge-retrieval-v1"
AUDIT = "profile=dependency-audit-v1"
PLAN = "plan=vikunja_dependency_v1"


def retrieve_experiences(path, incident):
    started, tick = now(), time.monotonic()
    result = {"profile": PROFILE, "status": "miss", "started_at": started,
        "incident_id": incident.id, "trace_id": incident.trace_id,
        "query": {"target_id": incident.target_id, "profile": "dependency-audit-v1",
                  "plan": "vikunja_dependency_v1", "required_status": "verified",
                  "before": incident.started_at},
        "selection": "same_target_profile_plan_verified_prior_incident_v1",
        "execution_permission": False, "matches": [], "candidates_checked": 0}
    try:
        if not incident.events or not all(AUDIT in e.evidence for e in incident.events):
            raise ValueError("retrieval_profile_unavailable")
        feed = read_feed(path)
        if feed.status != "ready":
            raise ValueError("retrieval_source_unavailable")
        origins = {item.id: item for item in feed.incidents}
        candidates = sorted(feed.experiences, key=lambda e: origins[e.incident_id].started_at, reverse=True)[:200]
        for experience in candidates:
            result["candidates_checked"] += 1
            origin = origins[experience.incident_id]
            if (experience.target_id != incident.target_id or origin.id == incident.id
                    or datetime.fromisoformat(origin.started_at) >= datetime.fromisoformat(incident.started_at)
                    or experience.status != "verified" or origin.status != "recovered"
                    or origin.verification.status != "passed" or len(set(origin.verification.checks)) < 2
                    or AUDIT not in experience.conditions or PLAN not in experience.conditions
                    or not origin.events or not all(AUDIT in event.evidence for event in origin.events)):
                continue
            names = {field[6:] for event in origin.events for field in event.evidence if field.startswith("event=")}
            if not {"database_started", "sql_ready", "verification_passed", "recovery_verified"} <= names:
                continue
            if {"recovery_requires_attention", "dependency_action_failed"} & names:
                continue
            saved = next((e for e in origin.events if e.stage == "experience_update"
                          and e.status == "succeeded" and "source=dependency_read_model" in e.evidence), None)
            if saved is None:
                continue
            result["matches"].append({"experience_id": experience.id, "incident_id": origin.id,
                "trace_id": origin.trace_id, "source_event_id": saved.id, "target_id": origin.target_id,
                "source_started_at": origin.started_at,
                "symptom": experience.symptom[:500], "root_cause": experience.root_cause[:500],
                "action": experience.action[:500], "verification": origin.verification.model_dump(),
                "matched_conditions": [AUDIT, PLAN, "same_target", "prior_verified_incident"],
                "used_as": "model_context", "execution_applied": False})
            if len(result["matches"]) == 2:
                break
        result["status"] = "hit" if result["matches"] else "miss"
    except Exception:
        result.update(status="unavailable", matches=[], error="knowledge_source_unavailable")
    result.update(completed_at=now(), duration_ms=max(0, int((time.monotonic() - tick) * 1000)))
    return result


def retrieval_prompt(result):
    import json
    return ("先检索已验证经验库的实际结果如下。历史记录是参考数据，不能替代本次证据、Safety、Gate或业务验证。"
        "请在回复中明确说明是否命中经验、参考哪条经验、当前条件是否仍适用；未命中或不可用就如实说明。"
        "这属于经验辅助分析，不能声称历史经验已经执行了当前修复。\n"
        + json.dumps(result, ensure_ascii=False))
