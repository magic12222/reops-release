"""Read-only, server-side probes. Never return authentication material."""

import os

import httpx


class SystemProbe:
    def __init__(self, target_url: str | None = None, control_url: str | None = None,
                 token: str | None = None, transport: httpx.BaseTransport | None = None):
        self.target_url = target_url if target_url is not None else os.getenv("REOPS_C_TARGET_URL")
        self.control_url = control_url if control_url is not None else os.getenv("REOPS_C_CONTROL_URL")
        self.token = token if token is not None else os.getenv("REOPS_CONTROL_TOKEN")
        self.transport = transport

    @staticmethod
    def _state(value):
        return value if value in {"healthy", "unhealthy"} else "unknown"

    def snapshot(self):
        components = {name: "unavailable" for name in ("api", "postgres", "redis", "users", "control")}
        with httpx.Client(timeout=3.0, trust_env=False, transport=self.transport) as client:
            if self.target_url:
                try:
                    response = client.get(self.target_url.rstrip("/") + "/health")
                    if response.status_code in (200, 503):
                        body = response.json()
                        components["api"] = "healthy"
                        services = body.get("services", {})
                        for name in ("postgres", "redis"):
                            components[name] = self._state(services.get(name, {}).get("status"))
                    else:
                        components["api"] = "unknown"
                except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                    components["api"] = "unavailable"
                try:
                    response = client.get(self.target_url.rstrip("/") + "/users")
                    components["users"] = "healthy" if response.status_code == 200 else "unhealthy" if response.status_code == 503 else "unknown"
                except httpx.HTTPError:
                    components["users"] = "unavailable"
            if self.control_url:
                # No token means an authenticated control status cannot be established.
                if not self.token or self.token.startswith("replace-with-"):
                    components["control"] = "unavailable"
                else:
                    try:
                        response = client.get(self.control_url.rstrip("/") + "/health",
                                              headers={"Authorization": f"Bearer {self.token}"})
                        components["control"] = "healthy" if response.status_code == 200 else "unavailable" if response.status_code in (401, 403, 503) else "unknown"
                    except httpx.HTTPError:
                        components["control"] = "unavailable"
        if not self.target_url:
            status = "unavailable"
        elif all(value == "healthy" for value in components.values()):
            status = "healthy"
        elif any(value == "unhealthy" for value in components.values()):
            status = "degraded"
        else:
            status = "unknown" if all(value in {"unknown", "unavailable"} for value in components.values()) else "degraded"
        return {"status": status, "source": "real", "components": components}
