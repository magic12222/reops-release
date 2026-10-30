"""RCA provider 边界；未来 Nexent adapter 在此接口之外封装 SDK。"""

import json
from typing import Any, Protocol


class RCAProvider(Protocol):
    def complete(self, request: dict[str, Any], *, timeout_seconds: float) -> str:
        """返回原始 JSON；adapter 应落实网络超时，不持有 executor。"""
        ...


class MockRCAProvider:
    """完全离线的确定性 provider，用于演示和端到端测试。"""

    offline_only = True

    def complete(self, request: dict[str, Any], *, timeout_seconds: float) -> str:
        diagnosis = request["rule_based_diagnosis"]
        logs = [log["message"] for log in request["relevant_logs"]]
        database_errors = [
            message for message in logs
            if "connection refused" in message.lower()
            and "postgres" in message.lower()
        ]
        if diagnosis["failure_detected"] and database_errors:
            result = {
                "suspected_root_cause": "database_unavailable",
                "affected_component": "postgres",
                "evidence": [*diagnosis["evidence"], *database_errors],
                "confidence": 0.8,
                "reasoning_summary": "Web 健康检查失败且 PostgreSQL 连接被拒绝，疑似数据库不可用；日志不能单独证明进程停止。",
                "suggested_action": {"action": "restart_service", "target": "postgres"},
            }
        else:
            result = {
                "suspected_root_cause": diagnosis["root_cause"],
                "affected_component": diagnosis["failed_component"],
                "evidence": diagnosis["evidence"],
                "confidence": diagnosis["confidence"],
                "reasoning_summary": "离线 provider 保留当前规则诊断。",
                "suggested_action": {"action": "no_action", "target": None},
            }
        for item in request.get("recovery_evidence", []):
            result["evidence"].append(
                f"历史 {item['event_id']}：{item['action']} target={item['target']}，"
                f"execution={item['execution_status']}，recovered={item['recovered']}"
            )
        return json.dumps(result, ensure_ascii=False, allow_nan=False)
