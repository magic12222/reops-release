"""Host-side allowlisted Docker tools. Never accept shell strings from callers."""
import os
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = frozenset({"api", "postgres", "redis"})


def find_docker():
    """Also find a fresh Windows install before the parent app refreshes PATH."""
    found = shutil.which("docker")
    if found:
        return found
    if os.name == "nt":
        candidates = [ROOT.parent / "Docker/resources/bin/docker.exe",
                      Path(os.getenv("ProgramFiles", "C:/Program Files")) / "Docker/Docker/resources/bin/docker.exe",
                      Path(os.getenv("LOCALAPPDATA", "C:/Users/Default/AppData/Local")) / "Programs/DockerDesktop/resources/bin/docker.exe"]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


class SystemTools:
    def __init__(self, runner=subprocess.run):
        self.runner = runner

    @staticmethod
    def validate_service(service):
        if service not in SERVICES:
            raise ValueError("Target must be api, postgres or redis")

    def _compose(self, args, profile="normal", timeout=90):
        if profile not in {"normal", "bad_password"}:
            raise ValueError("Unsupported configuration profile")
        env = os.environ.copy()
        env["REOPS_DB_PROFILE"] = profile
        # Fixed compose file and project name isolate actions from other workloads.
        command = [find_docker() or "docker", "compose", "--project-name", "reops-lab", "--file",
                   str(ROOT / "docker-compose.yml"), *args]
        try:
            result = self.runner(command, cwd=ROOT, env=env, shell=False, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=timeout)
            return {"exit_code": result.returncode, "stdout": result.stdout[-16000:],
                    "stderr": result.stderr[-16000:]}
        except subprocess.TimeoutExpired:
            return {"exit_code": 124, "stdout": "", "stderr": "Docker operation timed out; state uncertain"}
        except OSError as exc:
            return {"exit_code": 127, "stdout": "", "stderr": f"Docker unavailable: {type(exc).__name__}"}

    def operate(self, action, service):
        self.validate_service(service)
        if action not in {"start", "stop", "restart"}:
            raise ValueError("Unsupported operation")
        return self._compose([action, service])

    def start_service(self, service):
        return self.operate("start", service)

    def stop_service(self, service):
        return self.operate("stop", service)

    def restart_service(self, service):
        return self.operate("restart", service)

    def get_service_status(self, service):
        self.validate_service(service)
        return self._compose(["ps", "--all", "--format", "json", service], timeout=10)

    def get_service_liveness(self, service):
        """独立只读 Docker 存活证据；不从健康/HTTP 或 Compose 名称推断身份。"""
        self.validate_service(service)
        unknown = {"up": None, "source": "docker_state", "identity_confirmed": False,
                   "container_id": None, "state": "unknown"}
        host = os.environ.get("DOCKER_HOST", "")
        def local_endpoint(value):
            return value.startswith(("unix:///", "npipe:////./pipe/"))
        if host and not local_endpoint(host):
            return {**unknown, "reason": "remote_docker_forbidden"}
        executable = find_docker()
        if executable is None:
            return {**unknown, "reason": "docker_unavailable"}
        def read(args):
            result = self.runner([executable, *args], cwd=ROOT, shell=False, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=10)
            if result.returncode != 0:
                raise ValueError("docker_read_failed")
            return result.stdout
        try:
            endpoint = read(["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]).strip()
            if not local_endpoint(endpoint):
                return {**unknown, "reason": "remote_docker_forbidden"}
            ids = read(["ps", "--all", "--quiet", "--no-trunc", "--filter",
                "label=com.docker.compose.project=reops-lab", "--filter",
                f"label=com.docker.compose.service={service}"]).split()
            if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]{64}", ids[0]):
                return {**unknown, "reason": "target_missing_or_ambiguous"}
            # 只取身份标签和两个状态字段；不读取 Config.Env、错误文本或完整 inspect。
            fields = {"id": ".Id", "running": ".State.Running", "status": ".State.Status"}
            for key, label in (("project", "project"), ("service", "service"),
                               ("oneoff", "oneoff"), ("directory", "project.working_dir"),
                               ("config", "project.config_files")):
                fields[key] = f'index .Config.Labels "com.docker.compose.{label}"'
            template = "{" + ",".join('"' + key + '":{{json (' + expr + ')}}'
                                       for key, expr in fields.items()) + "}"
            value = json.loads(read(["inspect", "--format", template, ids[0]]))
            if (not isinstance(value, dict) or value.get("id") != ids[0]
                    or value.get("project") != "reops-lab" or value.get("service") != service
                    or value.get("oneoff") not in ("False", "false")
                    or not isinstance(value.get("directory"), str) or not value["directory"]
                    or Path(value["directory"]).resolve() != ROOT
                    or not isinstance(value.get("config"), str) or "," in value["config"]
                    or not value["config"] or Path(value["config"]).resolve() != ROOT / "docker-compose.yml"):
                return {**unknown, "reason": "target_identity_mismatch"}
            up = (1 if value.get("running") is True and value.get("status") == "running"
                  else 0 if value.get("running") is False and value.get("status") in {"exited", "dead"}
                  else None)
            return {"up": up, "source": "docker_state", "identity_confirmed": True,
                    "container_id": ids[0], "state": "running" if up == 1 else "stopped" if up == 0 else "unknown",
                    "reason": "confirmed" if up is not None else "state_uncertain"}
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError):
            return {**unknown, "reason": "docker_evidence_unavailable"}

    def get_logs(self, service, tail=100):
        self.validate_service(service)
        if type(tail) is not int or not 1 <= tail <= 200:
            raise ValueError("tail must be 1..200")
        return self._compose(["logs", "--no-color", "--timestamps", "--tail", str(tail), service], timeout=10)

    def set_database_profile(self, profile):
        return self._compose(["up", "-d", "--no-deps", "--force-recreate", "api"], profile)


_tools = SystemTools()
start_service = _tools.start_service
stop_service = _tools.stop_service
restart_service = _tools.restart_service
get_service_status = _tools.get_service_status
get_logs = _tools.get_logs


def health_check():
    import httpx
    with httpx.Client(timeout=8, trust_env=False) as client:
        return client.get("http://127.0.0.1:18000/health").json()
