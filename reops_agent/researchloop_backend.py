"""ResearchLoop独立目标登记/观测与固定Docker操作，不复用或放宽C4 scope。"""
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

import httpx
from .contracts import PROJECT_ROOT, validate
from .docker_executor import LocalDocker, DockerBoundaryError, now

DIRECTORY = PROJECT_ROOT / "integrations/researchloop"
COMPOSE = DIRECTORY / "compose.yml"
PROJECT = "reops-researchloop-demo"
URL = "http://127.0.0.1:18090"


def deployment_fingerprint():
    paths = [COMPOSE, DIRECTORY / "Dockerfile", DIRECTORY / "demo_main.py",
             DIRECTORY / "requirements.txt", DIRECTORY / "source-manifest.json"]
    paths += [PROJECT_ROOT / name for name in (
        "reops_agent/researchloop_backend.py", "reops_agent/researchloop_recovery.py",
        "reops_agent/authorization.py", "reops_agent/safety.py", "reops_agent/planner.py",
        "reops_agent/measurements.py", "scripts/run_researchloop_recovery.py",
        "scripts/researchloop_baseline.py", "dashboard_api/researchloop.py")]
    manifest = json.loads((DIRECTORY / "source-manifest.json").read_text(encoding="utf-8"))
    for name, checksum in manifest["files"].items():
        path = (DIRECTORY / "source" / name).resolve()
        if not path.is_relative_to((DIRECTORY / "source").resolve()):
            raise DockerBoundaryError("demo_source_boundary_rejected")
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise DockerBoundaryError("demo_source_fingerprint_changed")
        paths.append(path)
    hashes = {path.relative_to(PROJECT_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in paths}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


class ResearchLoopBackend:
    def __init__(self, business, docker=None):
        self.business = business
        self.docker = docker or LocalDocker()

    def container(self, service):
        if service not in {"api", "postgres"}:
            raise DockerBoundaryError("demo_service_not_whitelisted")
        # 复用固定argv调用和本地daemon检查，绝不使用原reops-lab目标映射。
        self.docker.check_local()
        ids = self.docker._run(["ps", "--all", "--quiet", "--no-trunc", "--filter",
            "label=com.docker.compose.project=" + PROJECT, "--filter",
            "label=com.docker.compose.service=" + service]).split()
        if len(ids) != 1 or not re.fullmatch("[a-f0-9]{64}", ids[0]):
            raise DockerBoundaryError("demo_container_missing_or_ambiguous")
        raw = self.docker._run(["inspect", "--format",
            '{{json .Config.Labels}}\n{{json .State}}\n{{json .HostConfig.PortBindings}}\n{{.Image}}', ids[0]])
        labels_raw, state_raw, ports_raw, image = raw.strip().splitlines()
        labels, state, ports = json.loads(labels_raw), json.loads(state_raw), json.loads(ports_raw)
        if (labels.get("com.docker.compose.project") != PROJECT
                or labels.get("com.docker.compose.service") != service
                or labels.get("com.docker.compose.oneoff", "").lower() != "false"
                or Path(labels.get("com.docker.compose.project.working_dir", "")).resolve() != DIRECTORY
                or labels.get("com.docker.compose.project.config_files") != str(COMPOSE)
                or service == "api" and ports != {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18090"}]}
                or service == "postgres" and ports not in ({}, None)):
            raise DockerBoundaryError("demo_container_ownership_or_port_mismatch")
        return ids[0], state, image

    def scope(self):
        containers = {name: self.container(name) for name in ("api", "postgres")}
        return {"project": PROJECT, "compose_file": str(COMPOSE),
            "docker_endpoint": self.docker._run(["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]).strip(),
            "deployment_sha256": deployment_fingerprint(), "business_url": URL + "/api/projects",
            "containers": {name: data[0] for name, data in containers.items()},
            "images": {name: data[2] for name, data in containers.items()},
            "required_services": ["api", "postgres"]}

    def observe(self, context):
        started = now()
        services, metrics = {}, {}
        for name in ("api", "postgres"):
            _, state, _ = self.container(name)
            running = state.get("Running") is True
            healthy = running and state.get("Health", {}).get("Status") == "healthy"
            services[name] = {"status": "healthy" if healthy else "unhealthy",
                "message": "stopped" if state.get("Status") == "exited" and not running else
                    "health probe " + str(state.get("Health", {}).get("Status"))}
            metrics[name + "_up"] = int(running)
        try:
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=3) as client:
                alive = client.get(URL + "/health").status_code == 200
        except httpx.HTTPError:
            alive = False
        try:
            code, valid = self.business.read()
        except httpx.HTTPError:
            code, valid = None, False
        value = {"schema_version": "1.0", **context, "observation_id": "obs-researchloop-" + uuid4().hex,
            "timestamp": started, "system": {"name": PROJECT, "environment": "isolated-demo"},
            "services": services, "metrics": metrics, "logs": [],
            "request": {"method": "GET", "endpoint": "/api/projects/{project_id}", "status_code": code},
            "business": {"project_id": self.business.project_id, "owner_user_id": self.business.owner,
                "project_db_id": self.business.project_db_id, "read_valid": valid, "api_alive": alive}}
        validate("observation", value)
        return value

    def sql_probe(self, scope):
        if self.scope() != scope:
            raise DockerBoundaryError("demo_scope_changed")
        # 固定只读SQL；输入不进入SQL/argv。
        raw = self.docker._run(["exec", scope["containers"]["postgres"], "psql", "-U", "demo",
            "-d", "researchloop_demo", "-Atc", "SELECT 1"], timeout=5)
        return raw.strip() == "1"

    def mutate(self, operation, scope):
        if operation not in {"stop", "restart"}:
            raise DockerBoundaryError("demo_operation_not_whitelisted")
        if self.scope() != scope:
            raise DockerBoundaryError("demo_scope_changed")
        _, state, _ = self.container("postgres")
        if operation == "stop" and state.get("Running") is not True:
            raise DockerBoundaryError("demo_stop_requires_running")
        if operation == "restart" and (state.get("Status") != "exited" or state.get("Running") is not False):
            raise DockerBoundaryError("demo_restart_requires_stopped")
        self.docker._run([operation, "--time", "5", scope["containers"]["postgres"]], timeout=30)


def healthy(observation):
    if not isinstance(observation, dict) or not all(isinstance(observation.get(key), dict)
            for key in ("services", "metrics", "request", "business")):
        return False
    return (set(observation["services"]) == {"api", "postgres"}
        and all(observation["services"][name]["status"] == "healthy"
            and type(observation["metrics"].get(name + "_up")) is int
            and observation["metrics"][name + "_up"] == 1 for name in ("api", "postgres"))
        and observation["request"].get("status_code") == 200
        and observation["request"].get("method") == "GET"
        and observation["request"].get("endpoint") == "/api/projects/{project_id}"
        and observation.get("business", {}).get("read_valid") is True
        and observation["business"].get("api_alive") is True
        and not observation.get("observation_conflicts"))


def stopped_database(observation):
    if not isinstance(observation, dict) or not all(isinstance(observation.get(key), dict)
            for key in ("services", "metrics", "request", "business")):
        return False
    return (set(observation["services"]) == {"api", "postgres"}
        and observation["services"]["api"]["status"] == "healthy"
        and observation["services"]["postgres"] == {"status": "unhealthy", "message": "stopped"}
        and type(observation["metrics"].get("postgres_up")) is int
        and observation["metrics"]["postgres_up"] == 0
        and type(observation["metrics"].get("api_up")) is int and observation["metrics"]["api_up"] == 1
        and observation["request"].get("status_code") == 503
        and observation["request"].get("method") == "GET"
        and observation["request"].get("endpoint") == "/api/projects/{project_id}"
        and observation.get("business", {}).get("read_valid") is False
        and observation["business"].get("api_alive") is True
        and not observation.get("observation_conflicts"))
