"""Phase 7C：真实观测诊断，只展示建议；没有恢复执行入口。"""

import argparse
from dataclasses import replace
import hashlib
import json
import time
from uuid import uuid4

from .advisory import BoundedProvider, diagnose_advisory, structured_observation
from .contracts import PROJECT_ROOT, validate
from .credential_handling import redact_persistent
from .docker_executor import DockerBoundaryError, LocalDocker, now
from .memory import RecoveryMemory
from .nexent_provider import NexentConfig, NexentRCAProvider
from .verification import verify

MEMORY_PATH = PROJECT_ROOT / "runtime/phase7c-memory.jsonl"


def advisory(observation, provider, *, memory=None, timeout=30,
             real_observation=False, real_model=False, model_identifier="offline-test"):
    """正式 Planner + Safety；拒绝 fallback 的规则恢复，永久禁止执行。"""
    core = diagnose_advisory(observation, provider, memory=memory, timeout=timeout)
    observation, diagnosis, rca = core["observation"], core["diagnosis"], core["rca"]
    action, safety = core["recovery_action"], core["safety"]
    reason, would_execute = core["rejection_reason"], core["would_execute"]
    report = {"phase": "7C", "mode": "diagnose-only", "real_observation": real_observation,
        "real_model": real_model, "provider": "nexent/dlut" if real_model else "offline-test",
        "model_identifier_sha256": hashlib.sha256(model_identifier.encode()).hexdigest(),
        "observation": observation, "model_input": core["model_input"], "rca": rca,
        "planner_decision": "accepted" if would_execute else "rejected" if reason else "no_action",
        "rejection_reason": reason, "recovery_action": action, "safety": safety,
        "execution": "WOULD_EXECUTE" if would_execute else "NO_ACTION",
        "execution_skipped_reason": "blocked_by_phase_7c_read_only",
        "executor_called": False, "recovery_executed": False,
        "diagnosis_validated": reason is None and safety["allowed"],
        "recovery_verified": False, "verification_status": "not_executed",
        "model_calls": core["model_calls"], "memory_written": False}
    event = {"schema_version": "1.0", "event_id": f"event-{uuid4()}",
        "incident_id": observation["incident_id"], "trace_id": observation["trace_id"],
        "timestamp": now(), "stage": "experience_update", "status": "skipped",
        "message": "真实诊断建议已记录；Phase 7C 未执行恢复，未验证恢复成功",
        "observation_id": observation["observation_id"], "diagnosis_id": diagnosis["diagnosis_id"],
        "action_id": action["action_id"], "data": {**report, "diagnosis": diagnosis,
            "recovered": False, "execution_result": {"execution_status": "skipped",
                "executor": {"executed": False}, "reason": report["execution_skipped_reason"]},
            "verification_result": {"status": "not_executed", "recovery_verified": False}}}
    event = redact_persistent(event)
    # 持久事件本身已是留痕，不保存尚未写入时的临时 false 标记。
    event["data"].pop("memory_written")
    validate("agent_event", event)
    if memory and diagnosis["failure_detected"]:
        memory.remember(event)
        report["memory_written"] = True
    report["event_id"] = event["event_id"]
    return redact_persistent(report)


def context():
    return {"schema_version": "1.0", "incident_id": f"incident-7c-{uuid4()}",
            "trace_id": f"trace-7c-{uuid4()}"}


def fault_smoke(backend, provider, *, memory, timeout=30, real_model=False,
                model_identifier="offline-test"):
    if isinstance(backend, LocalDocker):
        raise DockerBoundaryError("phase7d_authorized_entry_required")
    class CountedProvider:
        calls = 0

        def complete(self, request, *, timeout_seconds):
            self.calls += 1
            return provider.complete(request, timeout_seconds=timeout_seconds)

    counted = CountedProvider()
    baseline = backend.observe(context())
    if not verify(baseline)[2]:
        raise DockerBoundaryError("baseline_not_healthy_no_fault_injected")
    report = {"cleanup_success": False, "model_calls": 0, "executor_called": False,
              "recovery_executed": False, "recovery_verified": False}
    injected = False
    try:
        injected = True  # 停止超时仍需履行清理责任。
        backend.inject_web_failure_test_only()
        fault = backend.observe(baseline)
        if fault["metrics"].get("api_up") != 0 or fault["services"]["api"]["message"] != "stopped":
            raise DockerBoundaryError("fault_not_observed")
        report.update(advisory(fault, counted, memory=memory, timeout=timeout,
            real_observation=True, real_model=real_model, model_identifier=model_identifier))
        report["fault"] = "test_compose_api_stopped"
    except Exception:
        # 失败原文可能包含凭据，公开错误仅固定分类；不重试模型。
        report["error"] = "diagnosis_smoke_failed"
    finally:
        report["model_calls"] = counted.calls
        if injected:
            try:
                # 测试清理：固定 Web 目标，与 RecoveryPlan 完全无关。
                backend.restart("web")
                deadline = time.monotonic() + 30
                while True:
                    post = backend.observe(baseline)
                    if verify(post)[2] or time.monotonic() >= deadline:
                        break
                    time.sleep(0.5)
                report["cleanup_success"] = verify(post)[2]
                report["cleanup_is_test_fixture_only"] = True
            except Exception:
                report["cleanup_error"] = "cleanup_failed_inspect_test_environment"
    return report


def main(argv=None, *, backend=None, provider=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnose-only", action="store_true", help="默认模式；只读，不调用模型")
    parser.add_argument("--fault-smoke", action="store_true", help="一次真实 Web 故障诊断及测试清理")
    args = parser.parse_args(argv)
    backend = backend or LocalDocker()
    try:
        if not args.fault_smoke:
            observation = backend.observe(context())
            report = {"mode": "diagnose-only", "observation": structured_observation(observation),
                "baseline_healthy": verify(observation)[2], "model_calls": 0,
                "executor_called": False, "recovery_executed": False, "recovery_verified": False}
            code = 0
        else:
            if isinstance(backend, LocalDocker):
                raise DockerBoundaryError("phase7d_authorized_entry_required")
            config = replace(NexentConfig.from_env(), max_output_tokens=512)
            config.require_real_model()  # 在注入前检查独立模型 Gate。
            report = fault_smoke(backend, provider or NexentRCAProvider(config),
                memory=RecoveryMemory(MEMORY_PATH), timeout=config.timeout_seconds,
                real_model=provider is None, model_identifier=config.model_id)
            code = 0 if (report.get("diagnosis_validated") and report.get("cleanup_success")
                and report.get("execution") == "WOULD_EXECUTE"
                and report.get("recovery_action", {}).get("target") == "web") else 1
    except Exception:
        report, code = {"error": "precondition_failed", "executor_called": False,
                        "recovery_executed": False, "recovery_verified": False}, 2
    # ASCII JSON escapes 避免 Windows PowerShell 管道误解码中文；JSON 消费者可还原。
    print(json.dumps(redact_persistent(report), ensure_ascii=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
