"""Small, provenance-aware read models; source objects remain JSON."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Source = Literal["real", "offline_fixture", "simulation"]
SOURCES = ("real", "offline_fixture", "simulation")
STATUSES = ("unknown", "pending", "observing", "diagnosing", "waiting_authorization",
            "executing", "verifying", "recovered", "failed", "inconclusive")


@dataclass(frozen=True)
class Run:
    id: str
    incident_id: str
    trace_id: str
    source: Source
    status: str = "unknown"
    case_id: str | None = None
    fault_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    model_calls: int | None = None
    action_count: int | None = None
    recovery_latency_ms: float | None = None
    success: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Event:
    event_id: str
    run_id: str
    incident_id: str
    trace_id: str
    ordinal: int
    stage: str
    source: Source
    origin: Literal["trace_journal", "decision_trace", "experience_update"]
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    parent_event_id: str | None = None
    case_id: str | None = None
    status: str | None = None
    timestamp: str | None = None
    original_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
