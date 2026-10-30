import time
import re
import math
import uuid
from datetime import datetime, timezone

import httpx


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix):
    return f"{prefix}-{uuid.uuid4().hex}"


class Observer:
    def __init__(self, tools, base_url="http://127.0.0.1:18000", client=None):
        self.tools = tools
        self.base_url = base_url
        self.client = client

    def observe(self, incident_id, trace_id, case_id=None):
        if self.client is not None:
            return self._observe(self.client, incident_id, trace_id, case_id)
        with httpx.Client(timeout=8, trust_env=False) as client:
            return self._observe(client, incident_id, trace_id, case_id)

    def _observe(self, client, incident_id, trace_id, case_id):
        before = self._liveness()
        services = {name: {"status": "unknown", "message": "No dependency probe available"}
                    for name in ("api", "postgres", "redis")}
        logs = []
        try:
            response = client.get(self.base_url + "/health/live")
            services["api"] = {"status": "healthy" if response.status_code == 200 else "unhealthy"}
        except httpx.HTTPError:
            logs.append({"source": "observer", "message": "API live probe unavailable"})
            services["api"] = {"status": "unhealthy", "message": "API unreachable"}
        try:
            response = client.get(self.base_url + "/health")
            body = response.json() if response.status_code in (200, 503) else {}
            dependencies = body.get("services", {}) if isinstance(body, dict) else {}
            if not isinstance(dependencies, dict):
                dependencies = {}
            for name in ("postgres", "redis"):
                value = dependencies.get(name)
                if (isinstance(value, dict) and isinstance(value.get("status"), str)
                        and value["status"] in {"healthy", "unhealthy", "degraded", "unknown"}):
                    # 探针自由文本不成为停止证据，也不落盘潜在凭据。
                    services[name] = {"status": value["status"], "message": "health probe " + value["status"]}
                    latency = value.get("latency_ms")
                    if type(latency) in (int, float) and math.isfinite(latency) and latency >= 0:
                        services[name]["latency_ms"] = latency
        except (httpx.HTTPError, ValueError):
            logs.append({"source": "observer", "message": "Dependency health probe unavailable"})
        started = time.monotonic()
        status_code = None
        failure = {}
        try:
            response = client.get(self.base_url + "/users", headers={"X-Trace-ID": trace_id})
            status_code = response.status_code
            if status_code == 503:
                try:
                    body = response.json()
                    # Carry only workload evidence, never arbitrary response bodies/secrets.
                    if isinstance(body, dict):
                        failure = {key: body[key][:128] for key in ("step", "error_type")
                                   if isinstance(body.get(key), str)}
                except ValueError:
                    pass
        except httpx.HTTPError:
            logs.append({"source": "observer", "message": "Business request unavailable"})
        latency = round((time.monotonic() - started) * 1000, 2)
        after = self._liveness()
        liveness, metrics, conflicts = {}, {}, []
        for name in services:
            first, last = before[name], after[name]
            consistent = (first["identity_confirmed"] and last["identity_confirmed"]
                          and first["container_id"] == last["container_id"] and first["up"] == last["up"])
            up = last["up"] if consistent else None
            changed = (first["identity_confirmed"] and last["identity_confirmed"]
                       and (first["container_id"] != last["container_id"] or first["up"] != last["up"]))
            probe_conflict = (up == 0 and (services[name]["status"] == "healthy"
                              or name == "api" and status_code == 200))
            if changed or probe_conflict:
                up = None
                conflicts.append(name + ":liveness_samples_disagree" if changed else name + ":probe_liveness_disagree")
            metrics[name + "_up"] = up
            liveness[name] = {"source": "docker_state", "identity_confirmed": bool(consistent),
                "state": "running" if up == 1 else "stopped" if up == 0 else "unknown"}
        if services["api"]["status"] == "unhealthy" and status_code == 200:
            conflicts.append("api:probe_samples_disagree")
        for name in services:
            result = self.tools.get_logs(name, tail=30)
            if result["exit_code"] != 0:
                logs.append({"source": "observer", "message": f"{name}: log collection unavailable"})
            for line in (result["stdout"] + result["stderr"]).splitlines()[-30:]:
                logs.append({"source": name, "message": line[:2000]})
        return {"schema_version": "1.0", "observation_id": identifier("obs"),
                "incident_id": incident_id, "trace_id": trace_id, "case_id": case_id,
                "timestamp": now(), "system": {"name": "reops-demo", "environment": "docker-local"},
                "services": services, "request": {"method": "GET", "endpoint": "/users",
                "status_code": status_code, "latency_ms": latency, **failure}, "logs": logs,
                "service_liveness": liveness, "observation_conflicts": conflicts,
                "metrics": {"business_latency_ms": latency, **metrics}}

    def _liveness(self):
        unknown = {"up": None, "identity_confirmed": False, "container_id": None}
        sample = getattr(self.tools, "get_service_liveness", None)
        values = {}
        for name in ("api", "postgres", "redis"):
            value = unknown
            if callable(sample) and self.base_url == "http://127.0.0.1:18000":
                try:
                    candidate = sample(name)
                    if (isinstance(candidate, dict) and candidate.get("source") == "docker_state"
                            and candidate.get("identity_confirmed") is True
                            and isinstance(candidate.get("container_id"), str)
                            and re.fullmatch(r"[a-f0-9]{64}", candidate["container_id"])
                            and (candidate.get("up") is None or type(candidate["up"]) is int and candidate["up"] in (0, 1))):
                        value = {key: candidate[key] for key in ("up", "identity_confirmed", "container_id")}
                except (OSError, ValueError, TypeError, KeyError):
                    pass
            values[name] = value
        return values
