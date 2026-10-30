"""基于 shared 示例构造三个隔离的 mock 场景。"""

import json

from .contracts import PROJECT_ROOT

SCENARIOS = ("postgres_down", "web_health_failed", "log_error_alive")
RECOVERY_SCENARIOS = (
    "postgres_restart_success",
    "web_restart_success",
    "postgres_restart_failure",
    "no_failure",
)


def recovery_mock(scenario: str) -> tuple[dict, bool]:
    """返回恢复演示的初始 Observation 与模拟执行结果。"""
    mapping = {
        "postgres_restart_success": ("postgres_down", True),
        "web_restart_success": ("web_health_failed", True),
        "postgres_restart_failure": ("postgres_down", False),
        "no_failure": ("log_error_alive", True),
    }
    if scenario not in mapping:
        raise ValueError(f"未知恢复场景：{scenario}")
    observation_scenario, succeeds = mapping[scenario]
    observation = mock_observation(observation_scenario)
    observation.update(
        observation_id=f"obs-{scenario}",
        incident_id=f"incident-{scenario}",
        trace_id=f"trace-{scenario}",
        case_id=f"case-{scenario}",
    )
    return observation, succeeds


def mock_observation(scenario: str) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError(f"未知场景：{scenario}")
    filename = "observation.example.json" if scenario == "postgres_down" else "healthy_observation.example.json"
    result = json.loads((PROJECT_ROOT / "shared" / "examples" / filename).read_text(encoding="utf-8"))
    result.update(
        observation_id=f"obs-{scenario}", incident_id=f"incident-{scenario}",
        trace_id=f"trace-{scenario}", case_id=f"case-{scenario}",
    )
    if scenario == "web_health_failed":
        result["request"].update(endpoint="/health", status_code=503)
        result["services"]["api"].update(status="unhealthy", message="health endpoint returned 503")
        result["metrics"]["api_up"] = 1
    elif scenario == "log_error_alive":
        result["logs"] = [{"source": "api", "level": "ERROR", "message": "background job failed; request service remains available"}]
        result["metrics"]["api_up"] = 1
    return result


def rca_mock() -> dict:
    """Web 故障，数据库探针降级且日志指向依赖；存活指标暂不可用。"""
    observation = mock_observation("web_health_failed")
    observation["services"]["postgres"].update(status="degraded", message="mock database probe failed")
    observation["metrics"].pop("postgres_up", None)
    # 显式声明此离线场景的依赖关系，模拟重启后的新健康观测。
    observation["mock_dependencies"] = {"api": "postgres"}
    observation["logs"] = [{
        "source": "api", "level": "ERROR",
        "message": "PostgreSQL connection refused: postgres:5432 during /health",
    }]
    return observation
