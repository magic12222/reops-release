"""独立 RCA Agent：隔离 provider、严格校验并可靠回退规则诊断。"""

from copy import deepcopy
import json
import math
from queue import Empty, Queue
from threading import Lock, Thread
from typing import Any

from jsonschema import Draft202012Validator

from .contracts import validate
from .rca_provider import RCAProvider

_TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
RCA_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["suspected_root_cause", "affected_component", "evidence",
                 "confidence", "reasoning_summary", "suggested_action"],
    "properties": {
        "suspected_root_cause": {"anyOf": [_TEXT, {"type": "null"}]},
        "affected_component": {"anyOf": [_TEXT, {"type": "null"}]},
        "evidence": {"type": "array", "minItems": 1, "items": _TEXT},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning_summary": _TEXT,
        "suggested_action": {
            "type": "object", "additionalProperties": False,
            "required": ["action", "target"],
            "properties": {"action": _TEXT,
                           "target": {"anyOf": [_TEXT, {"type": "null"}]}},
        },
    },
}
Draft202012Validator.check_schema(RCA_RESULT_SCHEMA)
_VALIDATOR = Draft202012Validator(RCA_RESULT_SCHEMA)


def validate_rca_result(result: dict[str, Any]) -> None:
    _VALIDATOR.validate(result)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重复 JSON 字段")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("JSON 不允许非有限数值")


class RCAAgent:
    def __init__(self, provider: RCAProvider, *, timeout_seconds: float = 2.0):
        if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("RCA timeout 必须为有限正数")
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        # 同一 Agent 最多一个 provider 调用，超时后不积累悬挂线程。
        self._inflight = Lock()

    def analyze(self, observation: dict[str, Any], diagnosis: dict[str, Any],
                history_evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        validate("observation", observation)
        validate("diagnosis", diagnosis)
        for key in ("incident_id", "trace_id", "observation_id"):
            if diagnosis[key] != observation[key]:
                raise ValueError("RCA 输入关联 ID 不一致")
        request = deepcopy({
            "service_status": observation["services"],
            "metrics": observation["metrics"],
            "health_check": observation["request"],
            "relevant_logs": observation["logs"],
            "rule_based_diagnosis": diagnosis,
            "recovery_evidence": history_evidence or [],
        })
        if getattr(self.provider, 'offline_only', False) is True and 'offline_signals' in observation:
            request['offline_signals'] = deepcopy(observation['offline_signals'])
        def measured(result):
            # 在 RCA 最终返回边界关闭计量，避免后续 planner 阶段接受迟到结果。
            callback = getattr(type(self.provider), "_measurement_finished", None)
            if callable(callback):
                callback(self.provider, result)
            return result

        if not self._inflight.acquire(blocking=False):
            return measured(self._fallback(diagnosis, "provider_busy"))
        replies = Queue(maxsize=1)

        def call_provider():
            try:
                raw = self.provider.complete(request, timeout_seconds=self.timeout_seconds)
                replies.put((True, raw))
            except Exception:
                # 不把 provider 异常文本写入事件，避免意外暴露凭据。
                replies.put((False, None))
            finally:
                self._inflight.release()

        worker = Thread(target=call_provider, daemon=True)
        try:
            worker.start()
        except Exception:
            self._inflight.release()
            return measured(self._fallback(diagnosis, "provider_error"))
        try:
            succeeded, raw = replies.get(timeout=self.timeout_seconds)
        except Empty:
            return measured(self._fallback(diagnosis, "provider_timeout"))
        if not succeeded:
            return measured(self._fallback(diagnosis, "provider_error"))
        try:
            if not isinstance(raw, str):
                raise ValueError("provider 必须返回 JSON 文本")
            result = json.loads(raw, object_pairs_hook=_unique_object,
                                parse_constant=_invalid_constant)
            validate_rca_result(result)
        except Exception:
            return measured(self._fallback(diagnosis, "invalid_output"))
        return measured({"source": "provider", "fallback_reason": None, "result": result})

    @staticmethod
    def _fallback(diagnosis, reason):
        result = {
            "suspected_root_cause": diagnosis["root_cause"],
            "affected_component": diagnosis["failed_component"],
            "evidence": deepcopy(diagnosis["evidence"]),
            "confidence": diagnosis["confidence"],
            "reasoning_summary": "RCA 不可用，保留现有 rule-based diagnosis，由 planner 决策。",
            "suggested_action": {"action": "no_action", "target": None},
        }
        validate_rca_result(result)
        return {"source": "rule_based", "fallback_reason": reason, "result": result}
