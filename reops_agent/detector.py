"""使用明确状态证据检测故障；日志用于辅助解释。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Detection:
    failed: bool
    failure_type: str | None
    component: str | None
    step: str | None
    root_cause: str | None
    evidence: tuple[str, ...]
    confidence: float


def detect(observation: dict[str, Any]) -> Detection:
    services = observation["services"]
    metrics = observation["metrics"]
    request = observation["request"]
    if observation.get("observation_conflicts"):
        return Detection(True, "health_check_failure", "api" if "api" in services else next(iter(services)),
                         "health_check", "observation_conflict_reobserve_required",
                         ("观测证据矛盾，需重新观测；不判定服务停止",), 0.3)
    errors = tuple(
        f"日志 [{log['source']}] {log['message']}"
        for log in observation["logs"]
        if (log.get("level") or "").upper() in {"ERROR", "CRITICAL", "FATAL"}
    )
    status_code = request.get("status_code")
    request_failed = status_code is not None and status_code >= 400
    request_evidence = (
        (f"{request.get('method') or '请求'} {request.get('endpoint') or ''} 返回 HTTP {status_code}",)
        if request_failed else ()
    )

    # up=0 是直接存活证据；unhealthy + 停止状态消息也支持服务停止。
    # 连接拒绝本身可能来自端口/网络错误，不能单独证明进程已停止。
    for component, service in services.items():
        up = metrics.get(f"{component}_up")
        explicitly_down = up is not None and not isinstance(up, bool) and up == 0
        message = (service.get("message") or "").strip().lower()
        stopped = service["status"] == "unhealthy" and message in {
            "stopped", "exited", "service stopped", "process not running"
        }
        if explicitly_down or stopped:
            evidence = [f"服务 {component} 状态为 {service['status']}"]
            if explicitly_down:
                evidence.append(f"指标 {component}_up=0")
            if stopped:
                evidence.append(f"服务 {component} 消息为 {service['message']}")
            return Detection(
                True, "service_failure", component,
                "database_query" if component == "postgres" else "service_status",
                f"{component}_service_down",
                tuple(evidence) + request_evidence + errors, 0.97,
            )

    for component, service in services.items():
        if service["status"] in {"unhealthy", "degraded"}:
            evidence = (f"服务 {component} 健康状态为 {service['status']}",)
            if service.get("message"):
                evidence += (f"服务 {component} 消息为 {service['message']}",)
            return Detection(
                True, "health_check_failure", component, "health_check",
                "health_check_failed_cause_unknown", evidence + request_evidence + errors, 0.85,
            )

    if request_failed:
        # 共享契约没有 request→service 映射，不能任意选择一个服务。
        component = "web" if "web" in services else "api" if "api" in services else "request"
        health = (request.get("endpoint") or "").rstrip("/") in {"/health", "/healthz", "/ready", "/readyz"}
        return Detection(
            True, "health_check_failure" if health else "request_failure",
            component, "health_check" if health else "http_request",
            "health_check_failed_cause_unknown" if health else "request_failed_cause_unknown",
            request_evidence + errors, 0.8,
        )

    healthy = all(service["status"] == "healthy" for service in services.values())
    evidence = tuple(f"服务 {name} 状态为 {service['status']}" for name, service in services.items())
    if status_code is not None:
        evidence += (f"请求返回 HTTP {status_code}",)
    evidence += errors
    if errors:
        evidence += ("错误日志缺少当前服务或请求失败证据，暂不判定运行故障",)
    return Detection(False, None, None, None, None, evidence, 0.65 if errors else 0.95 if healthy and status_code is not None else 0.3)
