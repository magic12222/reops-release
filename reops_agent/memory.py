"""以 JSONL 保存和查询过去的故障恢复 AgentEvent。"""

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema.exceptions import ValidationError

from .contracts import validate
from .executor import ExecutionOutcome, validate_outcome
from .credential_handling import redact_persistent


class RecoveryMemory:
    """简单本地恢复记忆；每行保存一个完整故障恢复 AgentEvent。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def remember(self, event: dict[str, Any]) -> None:
        event = redact_persistent(event)
        validate("agent_event", event)
        if not event["data"]["diagnosis"]["failure_detected"]:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _read_events(self):
        """检索限额前去重；冲突事件全部弃用，不选择任意版本。"""
        events = {}
        conflicts = set()
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line, object_pairs_hook=_unique_fields, parse_constant=_nonfinite)
                    validate("agent_event", event)
                    _validate_memory_payload(event)
                except (ValueError, ValidationError, TypeError, KeyError):
                    # 原始异常可能包含整段历史文本；只输出固定分类/行号。
                    raise ValueError(f"Recovery Memory 第 {line_number} 行无效") from None
                event_id = event["event_id"]
                if event_id in events and events[event_id] != event:
                    conflicts.add(event_id)
                else:
                    events[event_id] = event
        return [event for key, event in events.items() if key not in conflicts]

    def query(self, failure_type: str | None, location: str | None) -> list[dict[str, Any]]:
        """按相同 failure_type + location 返回按时间排序的历史证据。"""
        if failure_type is None or location is None or not self.path.exists():
            return []
        return self._query_events(self._read_events(), failure_type, location)

    @staticmethod
    def _query_events(events, failure_type, location):
        evidence = []
        for event in events:
            diagnosis = event["data"]["diagnosis"]
            if (
                diagnosis.get("failure_type") == failure_type
                and diagnosis.get("location", diagnosis.get("failed_component")) == location
            ):
                action = event["data"]["recovery_action"]
                execution = event["data"]["execution_result"]
                verification = event["data"]["verification_result"]
                evidence.append({
                    "event_id": event["event_id"],
                    "timestamp": event["timestamp"],
                    "incident_id": event["incident_id"],
                    "trace_id": event["trace_id"],
                    "failure_type": failure_type,
                    "location": location,
                    "action": action["action"],
                    "target": action["target"],
                    "execution_status": execution["execution_status"],
                    "verification_status": verification["status"],
                    "recovered": event["data"]["recovered"],
                    "incident_type": diagnosis["failure_type"],
                    "observation": deepcopy(event["data"]["observation"]),
                    "diagnosis": deepcopy(diagnosis),
                    "root_cause": event["data"].get("experience", {}).get("root_cause", diagnosis["root_cause"]),
                    # 历史动作不携带其历史，避免多轮检索递归膨胀。
                    "proposed_action": _action_summary(action),
                    "executed_action": _action_summary(action) if (
                        execution["executor"]["executed"] if "executor" in execution
                        else execution["execution_status"] != "skipped") else None,
                    "verification": deepcopy(verification),
                    "success": event["data"]["recovered"],
                })
        return sorted(evidence, key=lambda item: item["timestamp"])

    def retrieve(self, failure_type: str | None, location: str | None,
                 *, limit: int = 5) -> list[dict[str, Any]]:
        """优先精确匹配，再找同组件或同类型案例；相似度优先，成功/近期次之。"""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("Memory limit 必须为 1~20 的整数")
        if failure_type is None or location is None or not self.path.exists():
            return []
        # 复用严格读取和完整证据提取，保持 query 的精确匹配语义。
        events = self._read_events()
        pairs = set()
        for event in events:
            diagnosis = event["data"]["diagnosis"]
            pairs.add((diagnosis["failure_type"],
                       diagnosis.get("location", diagnosis["failed_component"])))
        evidence = []
        for kind, component in pairs:
            score = 2 * (component == location) + (kind == failure_type)
            if score:
                for item in self._query_events(events, kind, component):
                    item["similarity"] = score / 3
                    item["match_type"] = "exact" if score == 3 else "similar"
                    evidence.append(item)
        return sorted(evidence, key=lambda item: (
            item["similarity"], item["recovered"], item["timestamp"], item["event_id"]
        ), reverse=True)[:limit]


def _action_summary(action):
    return deepcopy({key: value for key, value in action.items() if key != "decision_basis"})


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_memory_field')
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError('nonfinite_memory_json')


def _validate_memory_payload(event):
    """AgentEvent外层允许任意data；Memory另校验实际使用的恢复载荷。"""
    data = event['data']
    if event['stage'] != 'experience_update' or type(data['recovered']) is not bool:
        raise ValueError('invalid_memory_payload')
    documents = [('observation', data['observation']), ('diagnosis', data['diagnosis']),
                 ('recovery_action', data['recovery_action'])]
    for schema, document in documents:
        validate(schema, document)
        if any(document[key] != event[key] for key in ('incident_id', 'trace_id')):
            raise ValueError('memory_correlation_mismatch')
    if (data['diagnosis']['observation_id'] != data['observation']['observation_id']
            or data['recovery_action']['diagnosis_id'] != data['diagnosis']['diagnosis_id']):
        raise ValueError('memory_correlation_mismatch')
    execution = data['execution_result']
    verification = data['verification_result']
    if not isinstance(execution, dict) or not isinstance(verification, dict):
        raise ValueError('invalid_memory_outcome')
    status = execution.get('execution_status')
    verified = verification.get('status')
    if not isinstance(status, str) or status not in {'succeeded','failed','rejected','skipped'}:
        raise ValueError('invalid_memory_execution')
    if not isinstance(verified, str) or verified not in {'recovered','not_recovered','inconclusive','not_run','not_executed'}:
        raise ValueError('invalid_memory_verification')
    if verified in {'not_run','not_executed'} and status != 'skipped':
        raise ValueError('contradictory_memory_unattempted')
    if 'result_id' in execution:
        validate('recovery_result', execution)
        validate_outcome(ExecutionOutcome(execution['execution_status'],execution['exit_code'],
            execution['stdout'],execution['stderr'],execution['duration_ms'],data['observation'],
            execution.get('executor') if status=='succeeded' else None),data['recovery_action'])
        if (any(execution[key] != event[key] for key in ('incident_id','trace_id'))
                or execution['action_id'] != data['recovery_action']['action_id']):
            raise ValueError('memory_execution_correlation_mismatch')
    elif status != 'skipped':
        raise ValueError('incomplete_memory_execution')
    metadata = execution.get('executor')
    if metadata is not None and (not isinstance(metadata, dict) or type(metadata.get('executed')) is not bool):
        raise ValueError('invalid_memory_executor')
    if data['recovered'] and (status != 'succeeded' or verified != 'recovered'
                             or metadata is not None and not metadata['executed']):
        raise ValueError('contradictory_memory_success')
