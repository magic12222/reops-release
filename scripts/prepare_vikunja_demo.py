"""仅初始化已确认的独立 Vikunja；凭据只经子进程环境进入容器，不写配置文件。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time

import httpx

from reops_agent.contracts import PROJECT_ROOT
from tools.system_tools import find_docker

DIRECTORY = PROJECT_ROOT / "integrations/vikunja"
COMPOSE = DIRECTORY / "compose.yml"
LOCK = DIRECTORY / "images.lock.json"
PROJECT = "reops-vikunja-demo"
APP_IMAGE = "ghcr.io/go-vikunja/vikunja:2.7.1"
PG_IMAGE = "postgres:16-alpine"


def docker(args, *, env=None, timeout=30):
    executable = find_docker()
    if executable is None:
        raise ValueError("docker_unavailable")
    try:
        result = subprocess.run([executable, *args], cwd=DIRECTORY, env=env,
            shell=False, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("docker_operation_unavailable_or_uncertain") from None
    if result.returncode:
        # Compose interpolates secrets: neither its output nor exception is published.
        raise ValueError("docker_operation_failed")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true", help="新建此隔离环境；拒绝已有容器或卷")
    args = parser.parse_args()
    endpoint = os.environ.get("DOCKER_HOST") or docker(
        ["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
    if not endpoint.startswith(("npipe://", "unix://")):
        raise ValueError("remote_docker_forbidden")
    # Pin all subsequent commands to this daemon, independent of context changes.
    selected_env = os.environ.copy()
    for key in ("DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        selected_env.pop(key, None)
    selected_env["DOCKER_HOST"] = endpoint
    engine_id = docker(["info", "--format", "{{.ID}}"], env=selected_env)
    ids = docker(["ps", "-aq", "--filter", "label=com.docker.compose.project=" + PROJECT], env=selected_env)
    volumes = docker(["volume", "ls", "-q", "--filter", "label=com.docker.compose.project=" + PROJECT], env=selected_env)
    if not args.deploy:
        print(json.dumps({"project": PROJECT, "existing_containers": len(ids.split()),
            "existing_volumes": len(volumes.split()), "deployment_performed": False}))
        return 0
    if ids or volumes:
        raise ValueError("existing_demo_no_recreate_or_volume_reuse")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 18110))
    images = {}
    for key, tag in (("app", APP_IMAGE), ("postgres", PG_IMAGE)):
        values = json.loads(docker(["image", "inspect", tag, "--format", "{{json .RepoDigests}}"], env=selected_env))
        repository = tag.rsplit(":", 1)[0]
        matches = [item for item in values if item.startswith(repository + "@sha256:")]
        if len(matches) == 1:
            images[key] = {"tag": tag, "digest": matches[0]}
        elif key == "app" and not matches:
            record = json.loads((PROJECT_ROOT / "runtime/vikunja-image-import/verified-import.json").read_text(encoding="utf-8"))
            image_id = docker(["image", "inspect", tag, "--format", "{{.Id}}"], env=selected_env)
            if (record.get("tag") != APP_IMAGE or record.get("all_layers_verified") is not True
                    or record.get("source") != "official_ghcr_via_host_network"
                    or record.get("config_image_id") != image_id):
                raise ValueError("verified_import_mismatch")
            images[key] = {"tag": tag, "digest": image_id,
                "registry_digest": record["registry_digest"], "reference_type": "verified_config_image_id"}
        else:
            raise ValueError("image_digest_missing_or_ambiguous")
    if LOCK.exists():
        if json.loads(LOCK.read_text(encoding="utf-8"))["images"] != images:
            raise ValueError("locked_images_changed")
    else:
        LOCK.write_text(json.dumps({"images": images}, indent=2) + "\n", encoding="utf-8")
    selected_env.update(REOPS_VIKUNJA_IMAGE=images["app"]["digest"],
        REOPS_VIKUNJA_POSTGRES_IMAGE=images["postgres"]["digest"],
        REOPS_VIKUNJA_DB_PASSWORD=secrets.token_urlsafe(32),
        REOPS_VIKUNJA_SERVICE_SECRET=secrets.token_urlsafe(48))
    # Quiet validation does not print interpolated configuration.
    docker(["compose", "-f", str(COMPOSE), "config", "--quiet"], env=selected_env)
    # The upstream scratch image runs as UID 1000 but does not own a fresh volume.
    # One fixed helper has only this new files volume; no network or database mount.
    files_volume = PROJECT + "_demo_files"
    docker(["volume", "create", "--label", "com.docker.compose.project=" + PROJECT,
        "--label", "com.docker.compose.volume=demo_files", files_volume], env=selected_env)
    docker(["run", "--rm", "--network", "none", "--user", "0", "--mount",
        "type=volume,src=" + files_volume + ",dst=/demo", "--entrypoint", "chown",
        images["postgres"]["digest"], "1000:1000", "/demo"], env=selected_env)
    docker(["compose", "-f", str(COMPOSE), "up", "-d", "--pull", "never", "--no-build"],
           env=selected_env, timeout=120)
    selected_env.clear()
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=2) as client:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                if client.get("http://127.0.0.1:18110/api/v1/info").status_code == 200:
                    print(json.dumps({"project": PROJECT, "deployment_performed": True,
                        "url": "http://127.0.0.1:18110", "fault_injected": False,
                        "compose_sha256": hashlib.sha256(COMPOSE.read_bytes()).hexdigest()}))
                    return 0
            except httpx.HTTPError:
                pass
            time.sleep(1)
    raise ValueError("app_readiness_unconfirmed_preserve_containers_for_inspection")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # No response text, environment or subprocess arguments in the error output.
        print(json.dumps({"passed": False, "error_type": type(error).__name__}))
        raise SystemExit(1) from None
