"""Phase 7B 预备入口：默认 check；run 仅展示建议，不持有执行器。"""

import argparse
from dataclasses import replace
import json

from .model_preflight import add_confirmation_arguments, preflight
from .mocks import rca_mock
from .nexent_provider import NexentConfig, NexentRCAProvider
from .pipeline import diagnose
from .planner import plan_recovery
from .rca import RCAAgent
from .safety import check_action


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--run", action="store_true")
    add_confirmation_arguments(parser)
    args = parser.parse_args(argv)
    check = preflight(resources_confirmed=args.resources_confirmed,
                      credential_confirmed=args.credential_confirmed,
                      quota_confirmed=args.quota_confirmed)
    if not args.run or not check["ready_for_real_model_smoke"]:
        print(json.dumps(check, ensure_ascii=False, indent=2))
        return (0 if check["local_configuration_ready"] else 2) if not args.run else 2
    config = replace(NexentConfig.from_env(), max_output_tokens=512)
    observation = rca_mock()
    observation.pop("mock_dependencies", None)
    diagnosis = diagnose(observation)
    rca = RCAAgent(NexentRCAProvider(config), timeout_seconds=config.timeout_seconds).analyze(
        observation, diagnosis, [])
    action = plan_recovery(diagnosis, rca_result=rca["result"], observation=observation)
    result = {"rca": rca, "proposed_action": action,
              "safety": check_action(action, observation), "executor_called": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if rca["source"] == "provider" else 1


if __name__ == "__main__":
    raise SystemExit(main())
