"""真实隔离业务基线：仅新账号/新项目，认证信息只驻留内存。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
from uuid import uuid4

import httpx
from reops_agent.contracts import PROJECT_ROOT

BASE_URL = "http://127.0.0.1:18090"


class BusinessSession:
    def __init__(self):
        self.client = httpx.Client(base_url=BASE_URL, timeout=5, trust_env=False,
                                   follow_redirects=False)
        self.project_id = "reops-db-" + uuid4().hex[:12]
        username, password = "demo-" + uuid4().hex, secrets.token_urlsafe(24)
        register = self.client.post("/api/auth/register", json={"username": username, "password": password})
        register.raise_for_status()
        self.owner = register.json()["user"]["id"]
        self.client.cookies.clear()
        login = self.client.post("/api/auth/login", json={"username": username, "password": password})
        login.raise_for_status()
        # 响应中的cookie/token/password均不落证据。
        self.password = None
        response = self.client.post("/api/projects", json={"project_id": self.project_id,
            "research_direction": "ReOps 数据库中断与业务持久化验证（本轮新测试数据）", "paper_type": "system"})
        response.raise_for_status()
        self.project_db_id = response.json()["id"]

    def read(self):
        response = self.client.get("/api/projects/" + self.project_id)
        valid = False
        if response.status_code == 200:
            value = response.json()
            valid = (value.get("id") == self.project_db_id and value.get("owner_user_id") == self.owner
                     and value.get("project_id") == self.project_id)
        return response.status_code, valid

    def write_probe(self, suffix):
        response = self.client.post("/api/projects", json={
            "project_id": self.project_id + "-" + suffix, "research_direction": "恢复验证新写入",
            "paper_type": "system"})
        return response.status_code == 201 and response.json().get("owner_user_id") == self.owner

    def read_probe(self, suffix):
        response = self.client.get("/api/projects/" + self.project_id + "-" + suffix)
        return response.status_code == 200 and response.json().get("owner_user_id") == self.owner

    def close(self):
        self.client.cookies.clear()
        self.client.close()


def main():
    session = BusinessSession()
    try:
        code, valid = session.read()
        listing = session.client.get("/api/projects")
        listing.raise_for_status()
        with httpx.Client(base_url=BASE_URL, trust_env=False, timeout=5) as outsider:
            unauthorized = outsider.get("/api/projects/" + session.project_id).status_code
            health = outsider.get("/health").json()
        checks = {"authenticated_read": code == 200 and valid,
            "list_persisted_project": any(item["id"] == session.project_db_id for item in listing.json()),
            "fresh_write": session.write_probe("baseline"),
            "fresh_readback": session.read_probe("baseline"),
            "unauthenticated_denied": unauthorized == 401,
            "generation_disabled": health.get("generation_enabled") is False}
        report = {"source": "real", "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": "ResearchLoop-AI隔离演示环境", "new_test_data_only": True,
            "project_id": session.project_id, "project_db_id": session.project_db_id,
            "owner_user_id": session.owner, "checks": checks, "passed": all(checks.values()),
            "repair_model_calls": 0, "research_generation_calls": 0,
            "database_fault_tested": False}
        directory = PROJECT_ROOT / "runtime/researchloop-baselines" / uuid4().hex
        directory.mkdir(parents=True)
        (directory / "baseline.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True))
        return 0 if report["passed"] else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
