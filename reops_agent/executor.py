"""不执行真实命令的白名单 mock executor。"""

from copy import deepcopy
from dataclasses import dataclass
import math
from .b_clock import utc_now
from typing import Any
from uuid import uuid4

from .contracts import validate


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    duration_ms: float
    observation: dict[str, Any]
    execution: dict[str, Any] | None = None


def validate_outcome(outcome, action):
    """拒绝不一致的适配器结果；调用方不得重试或沉淀未确认结果。"""
    if not isinstance(outcome,ExecutionOutcome):
        raise ValueError('invalid_executor_outcome')
    if (not isinstance(outcome.status,str) or outcome.status not in {'succeeded','failed','rejected','skipped'}
            or outcome.exit_code is not None and type(outcome.exit_code) is not int
            or type(outcome.duration_ms) not in (int,float) or not math.isfinite(outcome.duration_ms)
            or outcome.duration_ms < 0
            or any(value is not None and not isinstance(value,str) for value in (outcome.stdout,outcome.stderr))):
        raise ValueError('invalid_executor_outcome')
    metadata=outcome.execution
    if metadata is not None:
        if (not isinstance(metadata,dict) or type(metadata.get('executed')) is not bool
                or type(metadata.get('success')) is not bool
                or any(metadata.get(key)!=action[key] for key in ('action','target'))):
            raise ValueError('invalid_executor_outcome')
        if (metadata['success'] != (outcome.status=='succeeded')
                or outcome.status=='succeeded' and not metadata['executed']
                or outcome.status in {'skipped','rejected'} and metadata['executed']):
            raise ValueError('contradictory_executor_outcome')
    if outcome.status=='succeeded' and (outcome.exit_code != 0 or type(outcome.exit_code) is not int):
        raise ValueError('contradictory_executor_outcome')


def mock_execute(
    action: dict[str, Any],
    observation: dict[str, Any],
    *,
    succeeds: bool = True,
) -> ExecutionOutcome:
    """模拟白名单动作结果，并始终返回一个新的 Observation。"""
    validate("recovery_action", action)
    validate("observation", observation)
    post = deepcopy(observation)
    post["observation_id"] = f"obs-post-{uuid4()}"
    post["timestamp"] = utc_now().isoformat()

    if action["action"] == "no_action":
        outcome = ExecutionOutcome(
            "skipped", None, "no_action：未执行恢复动作", None, 0.0, post
        )
    elif action["action"] == "restart_service" and action["target"] in {"postgres", "web"}:
        target = action["target"]
        if succeeds:
            _apply_successful_restart(post, target)
            outcome = ExecutionOutcome(
                "succeeded", 0, f"mock restart {target} succeeded", None, 25.0, post
            )
        else:
            post["logs"].append({
                "source": "mock_executor",
                "level": "ERROR",
                "timestamp": post["timestamp"],
                "message": f"mock restart {target} failed",
            })
            outcome = ExecutionOutcome(
                "failed", 1, None, f"mock restart {target} failed", 25.0, post
            )
    else:
        raise ValueError(
            f"mock executor 不支持动作：{action['action']} target={action['target']}"
        )

    validate("observation", outcome.observation)
    return outcome


def _apply_successful_restart(observation: dict[str, Any], target: str) -> None:
    # 第一阶段 Observation 使用 api 表示 Web 服务；执行层保留 web 动作名。
    component = "api" if target == "web" and "api" in observation["services"] else target
    service = observation["services"].get(component)
    if service is None:
        raise ValueError(f"Observation 中不存在恢复目标：{target}")
    service.update(status="healthy", message=f"mock restart {target} succeeded")
    observation["metrics"][f"{component}_up"] = 1
    # 只有 mock 场景显式声明的 Web→postgres 依赖才模拟依赖恢复。
    # 这不是执行成功本身的证明；Verify 仍独立读取新 Observation。
    if target == "postgres":
        dependencies = observation.get("mock_dependencies", {})
        for name in ("api", "web"):
            dependent = observation["services"].get(name)
            if (dependencies.get(name) == "postgres" and dependent is not None
                    and dependent["status"] in {"unhealthy", "degraded"}
                    and observation["metrics"].get(f"{name}_up") == 1):
                dependent.update(status="healthy", message="mock database dependency restored; health probe passed")
    status_code = observation["request"].get("status_code")
    if (status_code is not None and status_code >= 400
            and all(item["status"] == "healthy" for item in observation["services"].values())):
        observation["request"]["status_code"] = 200
