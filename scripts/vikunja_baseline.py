"""真实 Vikunja 演示账号与任务读写；认证信息只驻留当前进程。"""
from datetime import datetime, timezone
import json
import secrets
import time
from threading import RLock
from uuid import uuid4

import httpx

from reops_agent.contracts import PROJECT_ROOT

BASE_URL = "http://127.0.0.1:18110"


def now():
    return datetime.now(timezone.utc).isoformat()


class BusinessSession:
    def __init__(self, *, transport=None, username=None, password=None):
        self.client = httpx.Client(base_url=BASE_URL, timeout=3, trust_env=False,
            follow_redirects=False, transport=transport)
        self._auth_lock = RLock()
        self._auth_next_refresh = float("inf")
        self._last_response_path = None
        self._last_read_error = None
        self.marker = "reops-" + uuid4().hex[:16]
        self.project_id = self.task_id = None
        self.probe_id = None
        self.probe_title = None
        try:
            if username is None:
                username, password = self.marker, secrets.token_urlsafe(24)
                self.request("POST", "/api/v1/register", {"username": username,
                    "email": self.marker + "@example.invalid", "password": password}, expected=(200, 201))
            elif not isinstance(username, str) or not username or not isinstance(password, str) or not password:
                raise ValueError("demo_login_required")
            login = self.request("POST", "/api/v1/login", {"username": username, "password": password})
            password = None
            token = login.get("token")
            if not isinstance(token, str) or not token:
                raise ValueError("demo_login_invalid")
            self.client.headers["Authorization"] = "Bearer " + token
            self._auth_next_refresh = time.monotonic() + 480
            project = self.request("PUT", "/api/v1/projects", {"title": "团队发布计划 " + self.marker}, expected=(200, 201))
            self.project_id = self.identifier(project)
            self.original_title = "发布前业务核对 " + self.marker
            task = self.request("PUT", f"/api/v1/projects/{self.project_id}/tasks",
                {"title": self.original_title}, expected=(200, 201))
            self.task_id = self.identifier(task)
        except Exception:
            self.close()
            raise ValueError("demo_session_preparation_failed") from None

    @staticmethod
    def identifier(value):
        identifier = value.get("id") if isinstance(value, dict) else None
        if type(identifier) is not int or identifier <= 0:
            raise ValueError("invalid_business_identifier")
        return identifier

    def response(self, method, path, payload=None):
        with self._auth_lock:
            if ("Authorization" in self.client.headers
                    and path != "/api/v1/user/token/refresh"
                    and time.monotonic() >= self._auth_next_refresh):
                self._refresh()
            code, value = self._response(method, path, payload)
            # Only a read can be repeated after auth expiry; never replay a write.
            if code == 401 and method == "GET" and "Authorization" in self.client.headers:
                self._refresh()
                return self._response(method, path, payload)
            return code, value

    def _refresh(self):
        cookie = self.client.cookies.get("vikunja_refresh_token", domain="127.0.0.1",
            path="/api/v1/user/token/refresh")
        if not isinstance(cookie, str) or not cookie:
            raise ValueError("demo_session_refresh_unavailable")
        # The upstream cookie may be Secure. Explicitly send it only to the fixed
        # loopback refresh endpoint; no redirect or external origin is possible.
        code, value = self._response("POST", "/api/v1/user/token/refresh",
            headers={"Cookie": "vikunja_refresh_token=" + cookie, "Authorization": ""})
        token = value.get("token") if isinstance(value, dict) else None
        if code != 200 or not isinstance(token, str) or not token:
            raise ValueError("demo_session_refresh_failed")
        self.client.headers["Authorization"] = "Bearer " + token
        self._auth_next_refresh = time.monotonic() + 480

    def _response(self, method, path, payload=None, *, headers=None):
        # Never log auth headers, cookies, response text or HTTP exceptions.
        self._last_response_path = path
        with self.client.stream(method, path, json=payload,
                                headers={"Cache-Control": "no-cache", "Accept-Encoding": "identity",
                                         **(headers or {})}) as response:
            content = bytearray()
            started = time.monotonic()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 65536 or time.monotonic() - started > 3:
                    return response.status_code, None
            try:
                return response.status_code, json.loads(content)
            except (ValueError, UnicodeError):
                return response.status_code, None

    def request(self, method, path, payload=None, *, expected=(200,)):
        code, value = self.response(method, path, payload)
        if code not in expected or not isinstance(value, dict):
            raise ValueError("business_request_failed")
        return value

    def _read(self, task_id, title):
        with self._auth_lock:
            return self._read_locked(task_id, title)

    def _read_locked(self, task_id, title):
        self._last_read_error = None
        self._last_response_path = None
        path = f"/api/v1/tasks/{task_id}"
        try:
            code, task = self.response("GET", path)
            valid = (code == 200 and isinstance(task, dict) and task.get("id") == task_id
                     and task.get("project_id") == self.project_id and task.get("title") == title)
            return code, valid
        except httpx.ReadTimeout:
            if self._last_response_path == path:
                self._last_read_error = "read_timeout"
                return None, False
            return None, None
        except (httpx.HTTPError, ValueError):
            return None, None

    def read(self):
        return self._read(self.task_id, self.original_title)

    def read_observation(self):
        with self._auth_lock:
            code, valid = self.read()
            return code, valid, self._last_read_error

    def update(self):
        title = self.original_title + "（已核对）"
        task = self.request("POST", f"/api/v1/tasks/{self.task_id}", {"title": title})
        if task.get("project_id") != self.project_id or task.get("title") != title:
            return False
        self.original_title = title
        return self.read() == (200, True)

    def write_probe(self):
        # A failed/uncertain write is never automatically repeated.
        if self.probe_title is not None:
            raise ValueError("write_probe_already_attempted")
        self.probe_title = "恢复后新增任务 " + uuid4().hex
        task = self.request("PUT", f"/api/v1/projects/{self.project_id}/tasks",
            {"title": self.probe_title}, expected=(200, 201))
        self.probe_id = self.identifier(task)
        return task.get("project_id") == self.project_id and task.get("title") == self.probe_title

    def read_probe(self):
        return self.probe_id is not None and self._read(self.probe_id, self.probe_title) == (200, True)

    def close(self):
        with self._auth_lock:
            self.client.headers.pop("Authorization", None)
            self.client.cookies.clear()
            self.client.close()


def baseline(session):
    checks = {"original_task_read": session.read() == (200, True),
        "task_update_readback": session.update(), "fresh_task_write": session.write_probe(),
        "fresh_task_readback": session.read_probe()}
    with httpx.Client(base_url=BASE_URL, trust_env=False, follow_redirects=False, timeout=3) as outsider:
        checks["unauthenticated_denied"] = outsider.get(f"/api/v1/tasks/{session.task_id}").status_code in (401, 403)
    return {"source": "real", "timestamp": now(), "target_id": "reops-vikunja-demo",
        "project_id": session.project_id, "task_id": session.task_id, "probe_id": session.probe_id,
        "checks": checks, "passed": all(checks.values()), "model_calls": 0, "fault_injected": False}


def main():
    session = BusinessSession()
    try:
        report = baseline(session)
        directory = PROJECT_ROOT / "runtime/vikunja-baselines" / uuid4().hex
        directory.mkdir(parents=True)
        (directory / "baseline.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report))
        return 0 if report["passed"] else 1
    finally:
        session.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}))
        raise SystemExit(1) from None
