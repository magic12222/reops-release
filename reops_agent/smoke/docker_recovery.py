"""完全离线、test-only 的 Web 停止/受限重启闭环。"""

import argparse
from copy import deepcopy
import json
import time
from uuid import uuid4

from reops_agent.contracts import PROJECT_ROOT
from reops_agent.docker_executor import DockerBoundaryError, DockerRecoveryExecutor, LocalDocker
from reops_agent.memory import RecoveryMemory
from reops_agent.pipeline import diagnose
from reops_agent.planner import plan_recovery
from reops_agent.recovery import recover
from reops_agent.safety import check_action
from reops_agent.verification import verify


def context():
    return {"schema_version": "1.0", "incident_id": f"incident-smoke-{uuid4()}",
            "trace_id": f"trace-smoke-{uuid4()}", "case_id": "test-only-docker-web-stopped"}


def check(backend):
    backend.check_local()
    for service in ("api", "postgres", "redis"):
        backend.container(service)
    observation = backend.observe(context())
    # 策略自检用明确标记的合成停止证据，不作为真实观测写入 Memory。
    stopped = deepcopy(observation)
    stopped["services"]["api"].update(status="unhealthy", message="stopped")
    stopped["metrics"]["api_up"] = 0
    action = plan_recovery(diagnose(stopped))
    safety = check_action(action, stopped)
    if action["target"] != "web" or not safety["allowed"]:
        raise DockerBoundaryError("safety_self_check_failed")
    return observation, safety


def run(backend):
    if isinstance(backend, LocalDocker):
        raise DockerBoundaryError("legacy_live_recovery_disabled_use_phase7d")
    healthy, safety = check(backend)
    if not verify(healthy)[2]:
        raise DockerBoundaryError("baseline_not_healthy_no_fault_injected")
    injected = False
    report = {"test_only": True, "offline": True, "safety_self_check": safety,
              "recovered": False, "cleanup_success": False}
    try:
        # 超时也可能已停止，先登记 cleanup 责任。
        injected = True
        backend.inject_web_failure_test_only()
        stopped = backend.observe(healthy)
        if stopped["metrics"]["api_up"] != 0:
            raise DockerBoundaryError("fault_not_observed")
        result = recover(stopped, executor=DockerRecoveryExecutor(dry_run=False, backend=backend),
                         memory=RecoveryMemory(PROJECT_ROOT / "runtime/docker-recovery-memory.jsonl"),
                         max_recovery_attempts=3)
        report.update(recovered=result["recovered"], final_status=result["final_status"],
                      attempt_count=result["attempt_count"], decision_trace=result["decision_trace"],
                      memory_written=result["memory_written"])
    except (DockerBoundaryError, ValueError, KeyError, TypeError):
        report["error"] = "smoke_failed_or_state_uncertain"
    finally:
        if injected:
            try:
                # 已恢复时无需额外 restart；失败则仅重启同一白名单测试服务。
                try:
                    post = backend.observe(healthy)
                except (DockerBoundaryError, ValueError, KeyError, TypeError):
                    post = None
                if post is None or not verify(post)[2]:
                    backend.restart("web")
                    # 有界等待只读观测，不借助 mock 修改健康状态。
                    deadline = time.monotonic() + 30
                    post = backend.observe(healthy)
                    while not verify(post)[2] and time.monotonic() < deadline:
                        time.sleep(0.5)
                        post = backend.observe(healthy)
                report["cleanup_success"] = verify(post)[2]
            except (DockerBoundaryError, ValueError, KeyError, TypeError):
                report["cleanup_error"] = "cleanup_failed_inspect_test_environment"
    return report


def main(argv=None, *, backend=None):
    parser = argparse.ArgumentParser(description="ReOps 离线 test-only Docker 恢复验证")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true", help="只读检查，不修改容器")
    modes.add_argument("--run", action="store_true", help="停止并恢复项目测试 Web")
    modes.add_argument("--cleanup", action="store_true", help="仅重启已核验身份的测试 Web")
    args = parser.parse_args(argv)
    if not args.check:
        print(json.dumps({"error": "legacy_live_recovery_disabled_use_phase7d",
                          "entry": "python -m reops_agent.recovery_smoke",
                          "executor_called": False, "recovered": False}))
        return 2
    backend = backend or LocalDocker()
    try:
        observation, safety = check(backend)
        report = {"mode": "check", "available": True, "baseline_healthy": verify(observation)[2],
                  "safety": safety, "modified": False}
        code = 0
    except (DockerBoundaryError, ValueError, KeyError, TypeError) as error:
        reason = str(error) if isinstance(error, DockerBoundaryError) else "invalid_docker_evidence"
        report, code = {"available": False, "error": reason, "recovered": False}, 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
