"""本机只读软件目录与基础存活监控；不读取命令行、凭据、环境或业务内容。"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import platform
import re
import shutil
import subprocess
from threading import Event, RLock, Thread
import time

from tools.system_tools import find_docker

INTERVAL = 10
MAX_WATCHES = 64
MAX_RECORDS = 2000
WINDOWS_QUERY = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$processes = @(Get-Process | ForEach-Object {
    $memory = $null
    try { $memory = $_.WorkingSet64 } catch {}
    [pscustomobject]@{ pid = $_.Id; name = $_.ProcessName; windowed = ($_.MainWindowHandle -ne 0); memory_bytes = $memory }
})
$serviceSource = 'ready'
try {
    $services = @(Get-CimInstance -ClassName Win32_Service -Property Name,DisplayName,State,ProcessId -Filter "State='Running'" |
        ForEach-Object { [pscustomobject]@{ name = $_.Name; display_name = $_.DisplayName; pid = $_.ProcessId } })
} catch { $services = @(); $serviceSource = 'unavailable' }
$portSource = 'ready'
try {
    $listeners = @(Get-NetTCPConnection -State Listen |
        ForEach-Object { [pscustomobject]@{ pid = $_.OwningProcess; port = $_.LocalPort } })
} catch { $listeners = @(); $portSource = 'unavailable' }
@{ processes = $processes; services = $services; listeners = $listeners; services_state = $serviceSource; ports_state = $portSource } | ConvertTo-Json -Depth 4 -Compress
'''
DOCKER_FORMAT = r'{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}","ports":"{{.Ports}}","project":"{{.Label "com.docker.compose.project"}}","service":"{{.Label "com.docker.compose.service"}}"}'


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(value, limit=160):
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value)).strip()[:limit]


def count(value):
    return value if type(value) is int and value >= 0 else None


def identifier(kind, name):
    return kind + ":" + sha256(name.casefold().encode("utf-8")).hexdigest()[:24]


def windows_records(data):
    """Positive field selection; never pass a whole OS object to a response."""
    ports = {}
    for row in data.get("listeners", []):
        if count(row.get("pid")) is not None and type(row.get("port")) is int and 0 < row["port"] < 65536:
            ports.setdefault(row["pid"], set()).add(row["port"])
    groups = {}
    for row in data.get("processes", []):
        name, pid = clean(row.get("name", "")), count(row.get("pid"))
        if not name or pid is None:
            continue
        key = name.casefold()
        item = groups.setdefault(key, {"id": identifier("process", name), "kind": "process", "name": name,
            "pids": [], "ports": [], "instances": 0, "memory_bytes": 0, "windowed": False,
            "image": None, "project": None, "service": None})
        item["pids"].append(pid)
        item["instances"] += 1
        item["windowed"] = item["windowed"] or row.get("windowed") is True
        memory = count(row.get("memory_bytes"))
        item["memory_bytes"] = item["memory_bytes"] + memory if memory is not None and item["memory_bytes"] is not None else None
        item["ports"] = sorted(set(item["ports"]) | ports.get(pid, set()))
    records = list(groups.values())
    for row in data.get("services", []):
        name = clean(row.get("name", ""))
        if not name:
            continue
        pid = count(row.get("pid"))
        records.append({"id": identifier("service", name), "kind": "service", "name": clean(row.get("display_name") or name),
            "pids": [pid] if pid is not None else [], "ports": sorted(ports.get(pid, set())), "instances": 1,
            "memory_bytes": None, "windowed": False, "image": None, "project": None, "service": name})
    return records


def collect_local_software(runner=subprocess.run):
    sources = {"process": "unavailable", "service": "unavailable", "container": "unavailable", "ports": "unavailable"}
    records = []
    def run(args, timeout=8, env=None):
        result = runner(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            shell=False, timeout=timeout, **({"env": env} if env is not None else {}))
        if result.returncode != 0 or len(result.stdout.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("local_discovery_unavailable")
        return result.stdout
    if platform.system() == "Windows":
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if executable:
            try:
                value = json.loads(run([executable, "-NoProfile", "-NonInteractive", "-Command", WINDOWS_QUERY]))
                records.extend(windows_records(value))
                sources.update(process="ready", service="ready" if value.get("services_state") == "ready" else "unavailable",
                    ports="ready" if value.get("ports_state") == "ready" else "unavailable")
            except Exception:
                pass  # OS errors may contain sensitive context. Never return them.
    docker = find_docker()
    if docker:
        try:
            env = os.environ.copy()
            for key in ("DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
                env.pop(key, None)
            endpoint = run([docker, "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], env=env, timeout=3).strip()
            if not re.fullmatch(r"npipe:////\./pipe/[\w.-]+|unix:///[^\s]+", endpoint):
                raise ValueError("local_docker_only")
            raw = run([docker, "--host", endpoint, "ps", "--no-trunc", "--format", DOCKER_FORMAT], env=env, timeout=4)
            for line in raw.splitlines():
                row = json.loads(line)
                if not re.fullmatch(r"[a-f0-9]{64}", str(row.get("id", ""))):
                    continue
                # Ports only, not interface addresses; no endpoint probing.
                numbers = {int(value) for value in re.findall(r":(\d+)->\d+/tcp", row.get("ports", ""))}
                records.append({"id": "container:" + row["id"], "kind": "container", "name": clean(row.get("name", "")),
                    "pids": [], "ports": sorted(value for value in numbers if 0 < value < 65536), "instances": 1,
                    "memory_bytes": None, "windowed": False, "image": clean(row.get("image", "")),
                    "project": clean(row.get("project", "")) or None, "service": clean(row.get("service", "")) or None})
            sources["container"] = "ready"
        except Exception:
            pass
    records.sort(key=lambda item: (not item["windowed"], not bool(item["ports"]), item["kind"] != "container", item["name"].casefold()))
    return {"records": records[:MAX_RECORDS], "sources": sources, "omitted": max(0, len(records) - MAX_RECORDS)}


class LocalSoftwareCatalog:
    def __init__(self, *, enabled=False, collector=collect_local_software, interval=INTERVAL):
        if type(enabled) is not bool or type(interval) is not int or not 1 <= interval <= 60:
            raise ValueError("invalid_local_discovery_configuration")
        self.enabled, self.collector, self.interval = enabled, collector, interval
        self.lock, self.stop = RLock(), Event()
        self.thread = None
        self.records, self.watches = {}, {}
        self.sources = {key: "unavailable" for key in ("process", "service", "container", "ports")}
        self.generated_at, self.sample_clock = None, None
        self.state = "starting" if enabled else "disabled"
        self.omitted = 0

    def start(self):
        if not self.enabled or self.thread is not None:
            return
        def follow():
            while not self.stop.is_set():
                self.sample()
                self.stop.wait(self.interval)
        self.thread = Thread(target=follow, name="local-software-catalog", daemon=True)
        self.thread.start()

    def sample(self):
        value = {}
        try:
            value = self.collector()
            records, sources = {row["id"]: deepcopy(row) for row in value["records"]}, value["sources"]
        except Exception:
            records, sources = {}, {key: "unavailable" for key in self.sources}
        sampled = now()
        with self.lock:
            self.records, self.sources = records, sources
            self.generated_at, self.sample_clock = sampled, time.monotonic()
            self.state = "ready" if all(value == "ready" for value in sources.values()) else "partial" if any(value == "ready" for value in sources.values()) else "unavailable"
            self.omitted = value.get("omitted", 0) if self.state != "unavailable" else 0
            for key, watch in self.watches.items():
                current = records.get(key)
                alive = True if current else False if sources.get(watch["record"]["kind"]) == "ready" and not self.omitted else None
                if current:
                    watch["record"], watch["last_seen_at"] = deepcopy(current), sampled
                watch["alive"] = alive
                watch["history"] = (watch["history"] + [{"timestamp": sampled, "alive": alive}])[-12:]

    def watch(self, key, watching):
        with self.lock:
            if not self.enabled:
                raise ValueError("catalog_disabled")
            if not watching:
                self.watches.pop(key, None)
                return
            if key in self.watches:
                return
            if self.sample_clock is None or time.monotonic() - self.sample_clock > self.interval * 3 or key not in self.records:
                raise ValueError("software_not_currently_discovered")
            if len(self.watches) >= MAX_WATCHES:
                raise ValueError("basic_monitor_limit_reached")
            self.watches[key] = {"record": deepcopy(self.records[key]), "alive": True, "last_seen_at": self.generated_at,
                "history": [{"timestamp": self.generated_at, "alive": True}]}

    def read(self):
        with self.lock:
            stale = self.sample_clock is not None and time.monotonic() - self.sample_clock > self.interval * 3
            result = {"source": "real", "state": "stale" if stale else self.state, "generated_at": self.generated_at,
                "interval_seconds": self.interval, "records": list(self.records.values()), "sources": self.sources,
                "watches": list(self.watches.values()), "omitted": self.omitted,
                "capabilities": ["liveness", "listener_ports", "working_set"], "recovery_available": False}
            result = deepcopy(result)
            if stale:
                for watch in result["watches"]: watch["alive"] = None
            return result

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=20)
