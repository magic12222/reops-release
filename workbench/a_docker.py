"""A-owned fixed Docker target; never inspect environment, command lines or logs."""

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess

from tools.system_tools import find_docker

ROOT = Path(__file__).resolve().parents[1]
TARGET_ID = "reops-lab-api"
BASE_URL = "http://127.0.0.1:18000"


class TargetError(RuntimeError):
    """Only fixed error codes may leave this boundary."""

    def __init__(self, code, *, mutation_attempted=False):
        super().__init__(code)
        self.mutation_attempted = mutation_attempted


@dataclass(frozen=True)
class Identity:
    endpoint: str
    engine_id: str
    container_id: str
    image_id: str
    compose_sha256: str

    def binding(self):
        return {**self.__dict__, "target_id": TARGET_ID, "root": str(ROOT),
                "project": "reops-lab", "service": "api", "business_url": BASE_URL + "/users"}


@dataclass(frozen=True)
class Inspection:
    identity: Identity
    running: bool
    status: str


class DockerTarget:
    """Select an existing running API; a replacement container requires reselection."""

    def __init__(self, runner=None):
        self._runner = runner or subprocess.run

    def _run(self, args, *, endpoint=None, timeout=2):
        executable = find_docker()
        if executable is None:
            raise TargetError("docker_unavailable")
        env = os.environ.copy()
        # Every data/action command pins its daemon explicitly, independent of context changes.
        if endpoint is not None:
            for key in ("DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
                env.pop(key, None)
        try:
            result = self._runner([executable, *(["--host", endpoint] if endpoint else []), *args],
                                  cwd=ROOT, env=env, shell=False, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            raise TargetError("docker_timeout_state_uncertain", mutation_attempted=args[0] == "start") from None
        except OSError:
            raise TargetError("docker_unavailable") from None
        if result.returncode != 0:
            raise TargetError("docker_operation_failed", mutation_attempted=args[0] == "start")
        return result.stdout

    def inspect(self):
        try:
            endpoint = os.environ.get("DOCKER_HOST") or self._run(
                ["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]
            ).strip()
            if not (re.fullmatch(r"npipe:////\./pipe/[\w.-]+", endpoint)
                    or re.fullmatch(r"unix:///[^\s]+", endpoint)):
                raise TargetError("remote_docker_forbidden")
            engine_id = self._run(["info", "--format", "{{.ID}}"], endpoint=endpoint).strip()
            if not engine_id:
                raise TargetError("docker_identity_unavailable")
            ids = self._run(["ps", "--all", "--quiet", "--no-trunc", "--filter",
                             "label=com.docker.compose.project=reops-lab", "--filter",
                             "label=com.docker.compose.service=api"], endpoint=endpoint).split()
            if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]{64}", ids[0]):
                raise TargetError("target_missing_or_ambiguous")
            # State.Error and Health.Log may contain secrets: select scalar fields only.
            raw = self._run(["inspect", "--format",
                '{{json .Config.Labels}}\n{{json .HostConfig.PortBindings}}\n{{.Image}}\n'
                '{{json .State.Running}}\n{{.State.Status}}\n{{json .State.Paused}}\n'
                '{{json .State.Restarting}}\n{{json .State.Dead}}', ids[0]], endpoint=endpoint)
            labels_raw, ports_raw, image, running_raw, status, paused, restarting, dead = raw.strip().splitlines()
            labels, ports, running = json.loads(labels_raw), json.loads(ports_raw), json.loads(running_raw)
            files = labels.get("com.docker.compose.project.config_files", "").split(",")
            if (labels.get("com.docker.compose.project") != "reops-lab"
                    or labels.get("com.docker.compose.service") != "api"
                    or labels.get("com.docker.compose.oneoff", "").lower() != "false"
                    or Path(labels.get("com.docker.compose.project.working_dir", "")).resolve() != ROOT
                    or len(files) != 1 or Path(files[0]).resolve() != ROOT / "docker-compose.yml"
                    or ports != {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18000"}]}
                    or not re.fullmatch(r"sha256:[a-f0-9]{64}", image)):
                raise TargetError("target_ownership_mismatch")
            if (type(running) is not bool or any(value != "false" for value in (paused, restarting, dead))
                    or (running, status) not in {(True, "running"), (False, "exited")}):
                raise TargetError("target_state_uncertain")
            identity = Identity(endpoint, engine_id, ids[0], image,
                                sha256((ROOT / "docker-compose.yml").read_bytes()).hexdigest())
            return Inspection(identity, running, status)
        except (ValueError, TypeError, AttributeError, OSError):
            raise TargetError("target_inspection_unavailable") from None

    def start(self, expected):
        current = self.inspect()
        if current.identity != expected or current.running or current.status != "exited":
            raise TargetError("target_changed_or_not_stopped")
        # Full immutable ID; never compose up, recreate, search by PID, or execute a caller command.
        self._run(["start", expected.container_id], endpoint=expected.endpoint, timeout=30)
