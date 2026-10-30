"""短期访问令牌续期：旋转 Cookie 仅在内存，写请求不重放。"""
import json

import httpx
import pytest

from scripts.vikunja_baseline import BusinessSession


@pytest.mark.parametrize("trigger", ["proactive", "expired_read", "failed_refresh", "expired_write"])
def test_refresh_and_no_automatic_write_replay(trigger):
    calls, rows = [], {}
    refreshed = False
    def handle(request):
        nonlocal refreshed
        path = request.url.path
        calls.append((request.method, path))
        if path.endswith("/register"):
            return httpx.Response(200, json={"id": 1})
        if path.endswith("/login"):
            return httpx.Response(200, json={"token": "old-fixture"}, headers=[
                ("Set-Cookie", "vikunja_refresh_token=first-fixture; Path=/api/v1/user/token/refresh; Secure; HttpOnly"),
                ("Set-Cookie", "vikunja_refresh_token=v2-fixture; Path=/api/v2/user/token/refresh; Secure; HttpOnly")])
        if path.endswith("/user/token/refresh"):
            assert request.headers["Cookie"] == "vikunja_refresh_token=first-fixture"
            assert not request.headers.get("Authorization")
            if trigger == "failed_refresh":
                return httpx.Response(401, json={"message": "offline refusal"})
            refreshed = True
            return httpx.Response(200, json={"token": "new-fixture"}, headers={
                "Set-Cookie": "vikunja_refresh_token=rotated-fixture; Path=/api/v1/user/token/refresh; Secure; HttpOnly"})
        if path == "/api/v1/projects":
            return httpx.Response(201, json={"id": 1})
        if request.method == "PUT":
            rows[1] = {"id": 1, "project_id": 1, **json.loads(request.content)}
            return httpx.Response(201, json=rows[1])
        if request.method == "POST":
            return httpx.Response(401, json={"message": "offline expiry"})
        if trigger == "expired_read" and not refreshed:
            return httpx.Response(401, json={"message": "offline expiry"})
        return httpx.Response(200, json=rows[1])

    session = BusinessSession(transport=httpx.MockTransport(handle))
    try:
        calls.clear()
        if trigger in {"proactive", "failed_refresh"}:
            session._auth_next_refresh = 0
        if trigger == "expired_write":
            with pytest.raises(ValueError):
                session.update()
            assert calls == [("POST", "/api/v1/tasks/1")]
        elif trigger == "failed_refresh":
            assert session.read() == (None, None)
            assert calls == [("POST", "/api/v1/user/token/refresh")]
        else:
            assert session.read() == (200, True)
            assert calls.count(("POST", "/api/v1/user/token/refresh")) == 1
            assert calls.count(("GET", "/api/v1/tasks/1")) == (2 if trigger == "expired_read" else 1)
            assert session.client.cookies.get("vikunja_refresh_token", domain="127.0.0.1",
                path="/api/v1/user/token/refresh") == "rotated-fixture"
    finally:
        session.close()
    assert not list(session.client.cookies)
    assert "Authorization" not in session.client.headers


@pytest.mark.parametrize("failure", ["task_read_timeout", "connect_timeout", "refresh_timeout"])
def test_only_an_actual_task_read_timeout_is_measured_as_failed_business(failure):
    title = None
    def handle(request):
        nonlocal title
        path = request.url.path
        if path.endswith("/register"):
            return httpx.Response(200, json={"id": 1})
        if path.endswith("/login"):
            return httpx.Response(200, json={"token": "fixture"}, headers={"Set-Cookie":
                "vikunja_refresh_token=fixture; Path=/api/v1/user/token/refresh; HttpOnly"})
        if path == "/api/v1/projects":
            return httpx.Response(201, json={"id": 1})
        if request.method == "PUT":
            title = json.loads(request.content)["title"]
            return httpx.Response(201, json={"id": 1, "project_id": 1, "title": title})
        if failure == "connect_timeout":
            raise httpx.ConnectTimeout("offline", request=request)
        raise httpx.ReadTimeout("offline", request=request)
    session = BusinessSession(transport=httpx.MockTransport(handle))
    try:
        if failure == "refresh_timeout":
            session._auth_next_refresh = 0
        assert session.read_observation() == ((None, False, "read_timeout")
            if failure == "task_read_timeout" else (None, None, None))
    finally:
        session.close()
