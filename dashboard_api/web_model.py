"""本机网页模型配置：当前服务进程内存，不回显或持久化Key。"""
from dataclasses import replace
from datetime import datetime, timezone
import os
from threading import RLock
import time
from uuid import uuid4

import httpx
from reops_agent.nexent_provider import NexentConfig, _private_sdk_logs

BASE = "http://aigw.dlut.edu.cn/v1"
MODEL = "DeepSeek-V3.1-W8A8"


def existing_config():
    names = ("NEXENT_API_BASE", "NEXENT_MODEL_ID", "NEXENT_API_KEY", "REOPS_ALLOW_DLUT_HTTP")
    values = {name: os.environ.get(name, "") for name in names}
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as registry:
                for name in names:
                    try:
                        values[name] = winreg.QueryValueEx(registry, name)[0]
                    except OSError:
                        pass
        except OSError:
            pass
    if (not all(isinstance(value, str) for value in values.values())
            or values["NEXENT_API_BASE"].rstrip("/") != BASE or values["NEXENT_MODEL_ID"] != MODEL
            or values["REOPS_ALLOW_DLUT_HTTP"] != "1" or not values["NEXENT_API_KEY"]):
        return None
    try:
        return NexentConfig(BASE, MODEL, values["NEXENT_API_KEY"], max_output_tokens=512, allow_dlut_http=True)
    except ValueError:
        return None


class WebModel:
    def __init__(self, config=None):
        self.lock = RLock()
        self.config = config
        self.source = "existing_local" if config else "none"
        self.verified = False
        self.checks = []

    def status(self):
        with self.lock:
            return {"configured": self.config is not None, "verified": self.verified,
                "source": self.source, "model": self.config.model_id if self.config else MODEL,
                "endpoint": self.config.api_base if self.config else BASE,
                "storage": "server_process_memory", "inference_performed": False,
                "checks": [dict(item) for item in self.checks]}

    def _record_check(self, started, success, reason=None):
        self.checks.append({"id": uuid4().hex, "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": success, "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "error": reason, "request_type": "GET /models", "model": self.config.model_id})
        self.checks = self.checks[-20:]

    def set_key(self, value):
        if (not isinstance(value, str) or not 8 <= len(value) <= 2048
                or any(char.isspace() or ord(char) < 32 for char in value)):
            raise ValueError("model_key_invalid_format")
        with self.lock:
            self.config = NexentConfig(BASE, MODEL, value, max_output_tokens=512, allow_dlut_http=True)
            self.source, self.verified = "server_session", False

    def verify(self, transport=None):
        with self.lock:
            if self.config is None:
                raise ValueError("model_key_missing")
            self.verified = False
            started = time.monotonic()
            try:
                from .model_endpoints import public_transport, validate_endpoint
                validate_endpoint(self.config.api_base)
                with _private_sdk_logs(), httpx.Client(timeout=10, trust_env=False, follow_redirects=False,
                        transport=transport or public_transport()) as client:
                    response = client.get(self.config.api_base.rstrip("/") + "/models", headers={"Authorization": "Bearer " + self.config.api_key})
                    if response.status_code != 200:
                        raise ValueError("model_authentication_rejected" if response.status_code in (401, 403)
                                         else "model_gateway_rejected")
                    value = response.json()
                    items = value.get("data") if isinstance(value, dict) else None
                    if not isinstance(items, list) or not any(isinstance(item, dict) and item.get("id") == self.config.model_id for item in items):
                        raise ValueError("model_not_available")
            except ValueError as error:
                if str(error) in {"model_authentication_rejected", "model_gateway_rejected", "model_not_available"}:
                    self._record_check(started, False, str(error))
                    raise ValueError(str(error)) from None
                self._record_check(started, False, "model_gateway_unavailable")
                raise ValueError("model_gateway_unavailable") from None
            except Exception:
                self._record_check(started, False, "model_gateway_unavailable")
                raise ValueError("model_gateway_unavailable") from None
            self.verified = True
            self._record_check(started, True)
            return self.status()

    def for_run(self):
        with self.lock:
            if self.config is None or not self.verified:
                raise ValueError("model_connection_not_verified")
            return replace(self.config, enable_real_model=True)
