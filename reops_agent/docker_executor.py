"""项目本地 Docker 恢复；固定映射、默认预演、独立真实健康观测。"""

from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import time
from types import MappingProxyType
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

from jsonschema.exceptions import ValidationError

from .contracts import PROJECT_ROOT, validate
from .executor import ExecutionOutcome
from .safety import check_action
from .verification import verify
from tools.system_tools import find_docker
from .b_clock import utc_now

# 来源：A 的 docker-compose.yml；Web 在 Compose 中称为 api。
ALLOWED_SERVICES = MappingProxyType({"web": "api", "postgres": "postgres"})
PROJECT_NAME = "reops-lab"


def now():
    return utc_now().isoformat()


class DockerBoundaryError(RuntimeError):
    def __init__(self, reason, *, mutation_attempted=False):
        super().__init__(reason)
        self.mutation_attempted = mutation_attempted


class LocalDocker:
    """仅暴露身份检查、固定健康读取和白名单重启，不接受命令字符串。"""

    def __init__(self, runner=None):
        self._runner = runner or subprocess.run

    def _run(self, args, timeout=15):
        executable = find_docker()
        if executable is None:
            raise DockerBoundaryError("docker_unavailable")
        try:
            from .measurements import CURRENT
            measurement = CURRENT.get()
            if measurement is not None and args[0] in {"start", "restart"}:
                measurement.command_started(args[0])
            result = self._runner([executable, *args], shell=False, cwd=PROJECT_ROOT,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            raise DockerBoundaryError("docker_timeout_state_uncertain",
                                      mutation_attempted=args[0] in {"restart", "stop", "start"}) from None
        except OSError:
            raise DockerBoundaryError("docker_unavailable") from None
        if result.returncode:
            # 不传播 Docker stderr/config/env，避免泄漏凭据。
            reason = "docker_engine_unavailable" if args[0] == "info" else "docker_command_failed"
            raise DockerBoundaryError(reason, mutation_attempted=args[0] in {"restart", "stop", "start"})
        return result.stdout

    def check_local(self):
        host = os.environ.get("DOCKER_HOST", "")
        if host and not host.startswith(("npipe://", "unix://")):
            raise DockerBoundaryError("remote_docker_forbidden")
        endpoint = self._run(["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
        if not endpoint.strip().startswith(("npipe://", "unix://")):
            raise DockerBoundaryError("remote_docker_forbidden")
        self._run(["info", "--format", "{{.ServerVersion}}"])
        config = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        if not re.search(r"^name: reops-lab\s*$", config, re.M) or any(
                not re.search(r"^  " + service + r":\s*$", config, re.M)
                for service in ("api", "postgres", "redis")):
            raise DockerBoundaryError("compose_mapping_mismatch")

    def container(self, service):
        if service not in {"api", "postgres", "redis"}:
            raise DockerBoundaryError("service_not_whitelisted")
        self.check_local()
        ids = self._run(["ps", "--all", "--quiet", "--no-trunc", "--filter",
                         f"label=com.docker.compose.project={PROJECT_NAME}", "--filter",
                         f"label=com.docker.compose.service={service}"]).split()
        if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]{64}", ids[0]):
            raise DockerBoundaryError("test_service_missing_or_ambiguous")
        # 仅输出所需标签和状态，不读取 Config.Env 或完整 inspect。
        raw = self._run(["inspect", "--format",
                         '{{json .Config.Labels}}\n{{json .State}}', ids[0]])
        labels_raw, state_raw = raw.strip().splitlines()
        labels, state = json.loads(labels_raw), json.loads(state_raw)
        files = labels.get("com.docker.compose.project.config_files", "").split(",")
        directory = labels.get("com.docker.compose.project.working_dir", "")
        if (labels.get("com.docker.compose.project") != PROJECT_NAME
                or labels.get("com.docker.compose.service") != service
                or labels.get("com.docker.compose.oneoff", "").lower() != "false"
                or Path(directory).resolve() != PROJECT_ROOT
                or len(files) != 1
                or Path(files[0]).resolve() != PROJECT_ROOT / "docker-compose.yml"):
            raise DockerBoundaryError("container_ownership_mismatch")
        return ids[0], state

    def recovery_scope(self):
        """只读绑定本次实验环境，不向模型发送路径、端点或容器 ID。"""
        containers = {service: self.container(service)[0] for service in ("api", "postgres", "redis")}
        endpoint = self._run(["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
        return {"project": PROJECT_NAME, "compose_file": str(PROJECT_ROOT / "docker-compose.yml"),
                "compose_sha256": hashlib.sha256((PROJECT_ROOT / "docker-compose.yml").read_bytes()).hexdigest(),
                "containers": containers, "docker_endpoint": endpoint.strip(),
                "business_url": "http://127.0.0.1:18000/users"}

    def restart(self, target, *, expected_container_id=None):
        if target not in ALLOWED_SERVICES:
            raise DockerBoundaryError("service_not_whitelisted")
        container_id, _ = self.container(ALLOWED_SERVICES[target])
        if expected_container_id is not None and container_id != expected_container_id:
            raise DockerBoundaryError("authorized_container_changed")
        self._run(["restart", "--time", "10", container_id], timeout=30)

    def inject_web_failure_test_only(self, *, expected_container_id=None):
        """测试入口调用；身份校验后仅停止本次授权的测试 Web。"""
        container_id, state = self.container(ALLOWED_SERVICES["web"])
        if expected_container_id is not None and container_id != expected_container_id:
            raise DockerBoundaryError("authorized_container_changed")
        if not state.get("Running"):
            raise DockerBoundaryError("test_web_not_running")
        self._run(["stop", "--time", "10", container_id], timeout=30)

    def start_web(self, *, expected_container_id):
        """仅供已授权 Phase 8 scoped adapter：固定已有 api ID，禁止启动运行中容器。"""
        container_id, state = self.container("api")
        if container_id != expected_container_id:
            raise DockerBoundaryError("authorized_container_changed")
        if (state.get("Running") is not False or state.get("Status") != "exited"
                or any(state.get(key) is True for key in ("Paused", "Restarting", "Dead"))):
            raise DockerBoundaryError("start_requires_exited_container")
        self._run(["start", container_id], timeout=30)
        return {"operation": "start", "compose_service": "api", "container_id": container_id,
                "pre_state": {key: state.get(key) for key in ("Status", "Running", "StartedAt", "FinishedAt")}}

    def observe(self, previous):
        post = {key: deepcopy(previous[key]) for key in
                ("schema_version", "incident_id", "trace_id")}
        if "case_id" in previous:
            post["case_id"] = previous["case_id"]
        post.update(observation_id=f"obs-docker-{uuid4()}", timestamp=now(),
                    system={"name": PROJECT_NAME, "environment": "docker-local-test"},
                    services={}, metrics={}, logs=[])
        for service in ("api", "postgres", "redis"):
            container_id, state = self.container(service)
            if service == "api":
                ports = json.loads(self._run(["inspect", "--format",
                                              '{{json .HostConfig.PortBindings}}', container_id]))
                if ports.get("8000/tcp") != [{"HostIp": "127.0.0.1", "HostPort": "18000"}]:
                    raise DockerBoundaryError("test_api_port_binding_mismatch")
            running = state.get("Running") is True
            health = state.get("Health", {}).get("Status")
            status = "healthy" if running and health == "healthy" else "unhealthy"
            post["services"][service] = {"status": status,
                "message": "stopped" if not running else "health probe " + str(health)}
            post["metrics"][f"{service}_up"] = int(running)
        started = time.monotonic()
        code = None
        try:
            # 固定 loopback 地址，不读取代理、不跟随重定向、不携带凭据。
            from urllib.request import HTTPRedirectHandler
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None
            opener = build_opener(ProxyHandler({}), NoRedirect())
            with opener.open("http://127.0.0.1:18000/users", timeout=3) as response:
                code = response.status
        except HTTPError as error:
            code = error.code if error.code >= 400 else None
        except (URLError, TimeoutError, OSError):
            pass
        post["request"] = {"method": "GET", "endpoint": "/users", "status_code": code,
                           "latency_ms": (time.monotonic() - started) * 1000}
        validate("observation", post)
        return post


class DockerRecoveryExecutor:
    """兼容 mock_execute 的 callable 接口；succeeds 不控制真实结果。"""

    def __init__(self, *, dry_run=True, backend=None, verify_timeout=30):
        if type(dry_run) is not bool:
            raise ValueError("dry_run 必须显式为 bool")
        if type(verify_timeout) not in (int, float) or not 0 <= verify_timeout <= 60:
            raise ValueError("verify_timeout 必须为 0~60 秒")
        self.dry_run = dry_run
        self.backend = backend or LocalDocker()
        self.verify_timeout = verify_timeout

    def __call__(self, action, observation, *, succeeds=True):
        started_at, started = now(), time.monotonic()
        post = deepcopy(observation)
        try:
            allowed = check_action(action, observation)
        except ValidationError:
            allowed = {"allowed": False, "reason": "schema_rejected"}
        mode = "dry_run" if self.dry_run else "real"
        status, executed, success, error = "skipped", False, False, None
        docker_status = None
        if not allowed["allowed"] or action["action"] != "restart_service":
            status, error = "rejected", allowed["reason"]
        elif self.dry_run:
            docker_status = "planned"
        elif isinstance(self.backend, LocalDocker):
            # Bare live backend would bypass Phase 7D's independent authorization
            # and scope pinning. The gated entry supplies its scoped adapter.
            status, error = "rejected", "phase7d_authorized_entry_required"
        else:
            try:
                # 先核验身份；restart 内再次核验，执行边界不接受用户 container name。
                self.backend.container(ALLOWED_SERVICES[action["target"]])
                self.backend.restart(action["target"])
                executed = True
                status, success, docker_status = "succeeded", True, "restart_completed"
            except (DockerBoundaryError, ValueError, KeyError, TypeError) as failure:
                executed = isinstance(failure, DockerBoundaryError) and failure.mutation_attempted
                status, error, docker_status = "failed", "docker_restart_failed_or_uncertain", "unknown"
            deadline = time.monotonic() + self.verify_timeout
            try:
                while True:
                    post = self.backend.observe(observation)
                    if not success or verify(post)[2] or time.monotonic() >= deadline:
                        break
                    time.sleep(min(0.5, max(0, deadline - time.monotonic())))
            except (DockerBoundaryError, ValueError, KeyError, TypeError):
                # 不能用故障前旧观测确认恢复；新观測明确标记未知。
                post = deepcopy(observation)
                post.update(observation_id=f"obs-unavailable-{uuid4()}", timestamp=now())
                for service in post["services"].values():
                    service.update(status="unknown", message="post observation unavailable")
                post["metrics"] = {}
                post["request"]["status_code"] = None
                error = "post_observation_unavailable"
        details = {"action": action["action"], "target": action["target"], "mode": mode,
                   "executed": executed, "success": success, "docker_status": docker_status,
                   "error": error, "started_at": started_at, "finished_at": now(),
                   "planned_operation": {"operation": "restart", "compose_service":
                       ALLOWED_SERVICES.get(action["target"])} if allowed["allowed"] else None}
        return ExecutionOutcome(status, 0 if success else None, None, error,
                                (time.monotonic() - started) * 1000, post, details)
