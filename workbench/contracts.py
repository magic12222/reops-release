"""工作台 v0.1 读模型；旧 shared 1.0 和 Agent 执行契约保持独立。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Component(Record):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    health: Literal["healthy", "unhealthy", "unknown"]


class Target(Record):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    runtime: Literal["process", "docker", "windows_service"]
    health: Literal["healthy", "unhealthy", "unknown"]
    monitoring: Literal["watching", "paused", "not_connected"]
    observed_at: str | None
    components: list[Component]
    allowed_actions: list[str]


class Event(Record):
    id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    timestamp: str
    stage: Literal["observe", "failure_detection", "localization", "root_cause_analysis",
                   "recovery_decision", "recovery_execution", "verification", "experience_update"]
    status: Literal["running", "succeeded", "failed", "skipped", "waiting_human", "unknown"]
    title: str
    detail: str
    evidence: list[str]


class ModelCall(Record):
    id: str = Field(min_length=1)
    model: str
    status: Literal["running", "succeeded", "failed", "unknown"]
    request: str
    response: str | None
    duration_ms: int | None = Field(ge=0)
    input_tokens: int | None = Field(ge=0)
    output_tokens: int | None = Field(ge=0)
    redacted: Literal[True]


class Verification(Record):
    status: Literal["passed", "failed", "pending", "unknown"]
    checks: list[str]


class Incident(Record):
    id: str = Field(min_length=1)
    target_id: str
    trace_id: str = Field(min_length=1)
    title: str
    started_at: str
    status: Literal["observing", "diagnosing", "waiting_human", "executing", "verifying",
                    "recovered", "failed", "unknown"]
    diagnosis_source: Literal["model", "experience", "rule", "unknown"]
    summary: str
    events: list[Event]
    model_calls: list[ModelCall]
    experience_ids: list[str]
    verification: Verification


class Experience(Record):
    id: str = Field(min_length=1)
    target_id: str
    incident_id: str
    title: str
    symptom: str
    root_cause: str
    action: str
    conditions: list[str]
    status: Literal["verified", "failed", "retired", "unverified"]


class TargetFeed(Record):
    status: Literal["not_connected", "ready"]
    targets: list[Target]


class AgentFeed(Record):
    status: Literal["not_connected", "ready"]
    incidents: list[Incident]
    experiences: list[Experience]


def unique_ids(items):
    ids = [item.id for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate_workbench_id")
    return set(ids)


class Snapshot(Record):
    schema_version: Literal["0.1"]
    source: Literal["real", "offline_fixture"]
    generated_at: str
    a_status: Literal["not_connected", "ready"]
    b_status: Literal["not_connected", "ready"]
    targets: list[Target]
    incidents: list[Incident]
    experiences: list[Experience]

    @model_validator(mode="after")
    def references(self):
        target_ids = unique_ids(self.targets)
        incident_ids = unique_ids(self.incidents)
        experience_ids = unique_ids(self.experiences)
        if self.a_status == "not_connected" and self.targets:
            raise ValueError("unconnected_target_feed")
        if self.b_status == "not_connected" and (self.incidents or self.experiences):
            raise ValueError("unconnected_agent_feed")
        for incident in self.incidents:
            if incident.target_id not in target_ids:
                raise ValueError("unknown_target")
            unique_ids(incident.events)
            unique_ids(incident.model_calls)
            if [event.sequence for event in incident.events] != list(range(len(incident.events))):
                raise ValueError("event_order_conflict")
            if not set(incident.experience_ids) <= experience_ids:
                raise ValueError("unknown_experience")
            if incident.diagnosis_source == "experience" and not incident.experience_ids:
                raise ValueError("experience_evidence_required")
            if incident.status == "recovered" and incident.verification.status != "passed":
                raise ValueError("verification_required")
        for experience in self.experiences:
            if experience.target_id not in target_ids or experience.incident_id not in incident_ids:
                raise ValueError("unknown_experience_origin")
            origin = next(item for item in self.incidents if item.id == experience.incident_id)
            if origin.target_id != experience.target_id:
                raise ValueError("experience_target_conflict")
            if experience.status == "verified" and origin.verification.status != "passed":
                raise ValueError("experience_verification_required")
        for incident in self.incidents:
            if any(item.target_id != incident.target_id for item in self.experiences
                   if item.id in incident.experience_ids):
                raise ValueError("experience_target_conflict")
        return self
