"""只读核验 A-02 的实际 Docker 身份/存活采样，不运行 HTTP、模型或恢复。"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.system_tools import SystemTools
from run_b_offline_regression import fingerprints


def main():
    baseline = fingerprints()
    folder = ROOT / "runtime/b-delivery/a02-readonly" / ("session-" + uuid4().hex)
    folder.mkdir(parents=True)
    calls = []
    env = {key: os.environ[key] for key in (
        "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
        "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME",
        "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG") if key in os.environ}

    def read_only_runner(command, **kwargs):
        args = command[1:]
        allowed = (args == ["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]
            or len(args) == 8 and args[:5] == ["ps", "--all", "--quiet", "--no-trunc", "--filter"]
            and args[5:7] == ["label=com.docker.compose.project=reops-lab", "--filter"]
            and args[7] in {"label=com.docker.compose.service=" + name for name in ("api", "postgres", "redis")}
            or len(args) == 4 and args[:2] == ["inspect", "--format"]
            and ".Config.Env" not in args[2] and re.fullmatch(r"[a-f0-9]{64}", args[3]))
        if not allowed or kwargs.get("shell") is not False or kwargs.get("cwd") != ROOT:
            raise ValueError("readonly_command_rejected")
        record = {"operation": args[0], "read_only": True}
        calls.append(record)
        try:
            result = subprocess.run(command, **kwargs, env=env)
            record["exit_code"] = result.returncode
            # 不保存 Docker stdout/stderr、身份标签原文或任何配置/凭据。
            if result.returncode:
                record["failure"] = "docker_read_failed"
            return result
        except subprocess.TimeoutExpired:
            record["failure"] = "timeout"
            raise
        except OSError:
            record["failure"] = "process_unavailable"
            raise

    tools = SystemTools(read_only_runner)
    rounds = []
    for number in (1, 2):
        samples = {}
        for service in ("api", "postgres", "redis"):
            sample = tools.get_service_liveness(service)
            container_id = sample.pop("container_id")
            sample["container_id_sha256"] = hashlib.sha256(container_id.encode()).hexdigest() if container_id else None
            samples[service] = sample
            print(json.dumps({"round": number, "service": service,
                              "up": sample["up"], "reason": sample["reason"]}), flush=True)
        rounds.append(samples)
    stable = all(first["identity_confirmed"] and last["identity_confirmed"]
        and first["up"] in (0, 1) and first["up"] == last["up"]
        and first["container_id_sha256"] == last["container_id_sha256"]
        for first, last in zip(rounds[0].values(), rounds[1].values()))
    report = {"timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "real_docker_readonly", "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rounds": rounds, "commands": calls, "identity_and_state_verified": stable,
        "runtime_unchanged": fingerprints() == baseline,
        "http_probe": "not_run", "model_calls": 0, "mutation_commands": 0}
    report["passed"] = report["identity_and_state_verified"] and report["runtime_unchanged"]
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(folder / "report.json")}), flush=True)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
