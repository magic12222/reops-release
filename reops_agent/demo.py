"""运行：python -m reops_agent.demo。"""

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from .memory import RecoveryMemory
from .mocks import RECOVERY_SCENARIOS, recovery_mock, rca_mock
from .recovery import recover
from .rca import RCAAgent
from .rca_provider import MockRCAProvider


def _memory_roundtrip(memory_path: Path) -> dict:
    memory = RecoveryMemory(memory_path)
    first_observation, succeeds = recovery_mock("postgres_restart_success")
    first = recover(first_observation, execution_succeeds=succeeds, memory=memory)

    second_observation, succeeds = recovery_mock("postgres_restart_success")
    second_observation.update(
        observation_id="obs-memory-second",
        incident_id="incident-memory-second",
        trace_id="trace-memory-second",
        case_id="case-memory-second",
    )
    second = recover(second_observation, execution_succeeds=succeeds, memory=memory)
    return {
        "scenario": "memory_roundtrip",
        "memory_format": "JSONL",
        "first_encounter": {
            "history_evidence": first["history_evidence"],
            "recovery_action": first["recovery_action"],
            "recovered": first["recovered"],
            "memory_written": first["memory_written"],
            "agent_event_id": first["agent_event"]["event_id"],
        },
        "second_encounter": {
            "history_evidence": second["history_evidence"],
            "recovery_action": second["recovery_action"],
            "recovered": second["recovered"],
            "memory_written": second["memory_written"],
            "agent_event_id": second["agent_event"]["event_id"],
        },
    }


def main() -> None:
    # PowerShell 管道下 Python 可能使用本地代码页，统一为 UTF-8。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="ReOps 最小 mock 恢复闭环演示")
    parser.add_argument(
        "--scenario",
        choices=("all", *RECOVERY_SCENARIOS, "memory_roundtrip", "rca_database_unavailable"),
        default="all",
    )
    parser.add_argument(
        "--memory-path",
        type=Path,
        help="memory_roundtrip 使用的 JSONL 路径；省略时使用临时文件",
    )
    parser.add_argument("--max-recovery-attempts", type=int, choices=range(1, 6), default=1,
                        help="普通恢复/RCA 场景最多尝试次数，默认 1；memory_roundtrip 固定单次")
    args = parser.parse_args()
    print("Detect → Localize → Diagnose → Decide → Execute → Verify")
    if args.scenario == "rca_database_unavailable":
        with TemporaryDirectory(prefix="reops-rca-") as directory:
            memory = RecoveryMemory(Path(directory) / "recovery_memory.jsonl")
            # 先写入同类型/位置的历史失败尝试，供 RCA 和 planner 消费。
            prior = rca_mock()
            prior.update(observation_id="obs-prior", incident_id="incident-prior",
                         trace_id="trace-prior")
            recover(prior, memory=memory, execution_succeeds=False)
            result = recover(rca_mock(), memory=memory,
                             rca_agent=RCAAgent(MockRCAProvider()),
                             max_recovery_attempts=args.max_recovery_attempts)
            print(json.dumps({"scenario": args.scenario, **result}, ensure_ascii=False, indent=2))
        return
    if args.scenario == "memory_roundtrip":
        if args.memory_path is not None:
            result = _memory_roundtrip(args.memory_path)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            with TemporaryDirectory(prefix="reops-memory-") as directory:
                result = _memory_roundtrip(Path(directory) / "recovery_memory.jsonl")
                print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for scenario in RECOVERY_SCENARIOS if args.scenario == "all" else (args.scenario,):
        observation, succeeds = recovery_mock(scenario)
        workflow = recover(observation, execution_succeeds=succeeds,
                           max_recovery_attempts=args.max_recovery_attempts)
        print(json.dumps({"scenario": scenario, **workflow}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
