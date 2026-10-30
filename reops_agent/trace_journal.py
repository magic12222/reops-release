"""执行前必须成功落盘的脱敏轨迹；使用 shared 已有 AgentEvent。"""

from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

from .contracts import validate
from .credential_handling import redact_persistent
from .docker_executor import now


class TraceJournal:
    def __init__(self, context, path):
        self.context = {key: context[key] for key in ("incident_id", "trace_id")}
        if "case_id" in context:
            self.context["case_id"] = deepcopy(context["case_id"])
        self.path = Path(path)
        self.events = []

    def record(self, stage, step, status, data):
        event = redact_persistent({"schema_version": "1.0", **self.context,
            "event_id": f"event-{uuid4()}", "parent_event_id":
                self.events[-1]["event_id"] if self.events else None,
            "timestamp": now(), "stage": stage, "status": status,
            "message": step, "data": {"step": step, **deepcopy(data)}})
        validate("agent_event", event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.events.append(event)
        return event
