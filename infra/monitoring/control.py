"""Local authenticated control plane; run a single uvicorn worker on loopback."""
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field

from infra.monitoring.observer import Observer, identifier, now
from tools.system_tools import ROOT, SystemTools


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS objects (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT)")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def put(self, key, body):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO objects VALUES (?, ?)", (key, json.dumps(body)))

    def get(self, key):
        with self.connect() as db:
            row = db.execute("SELECT body FROM objects WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    case_id: str | None = Field(default=None, max_length=128)


def empty_verification():
    return {"status": "not_run", "checked_at": None, "health_check_passed": None,
            "fault_cleared": None, "business_request_passed": None, "evidence": []}


class Executor:
    def __init__(self, tools, observer, store, verify_timeout=20):
        self.tools, self.observer, self.store = tools, observer, store
        self.verify_timeout = verify_timeout
        self.lock = threading.Lock()
        schema = json.loads((ROOT / "shared/recovery_action.schema.json").read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def observe(self, context):
        observation = self.observer.observe(context["incident_id"], context["trace_id"], context.get("case_id"))
        self.store.put(observation["observation_id"], observation)
        return observation

    def execute(self, action):
        errors = list(self.validator.iter_errors(action))
        if errors:
            raise HTTPException(422, "RecoveryAction does not match shared schema")
        digest = hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()
        with self.lock:
            with self.store.connect() as db:
                # Reserve before the side effect, including across processes/restarts.
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT digest, result FROM actions WHERE id=?", (action["action_id"],)).fetchone()
                if row:
                    if row[0] != digest:
                        raise HTTPException(409, "action_id already used for a different payload")
                    if row[1] is None:
                        raise HTTPException(409, "Action in progress or interrupted; inspect system before retrying")
                    return json.loads(row[1])
                db.execute("INSERT INTO actions VALUES (?, ?, NULL)", (action["action_id"], digest))
            result = self._execute(action)
            with self.store.connect() as db:
                db.execute("UPDATE actions SET result=? WHERE id=?", (json.dumps(result), action["action_id"]))
            self.store.put(result["result_id"], result)
            return result

    def _execute(self, action):
        started = time.monotonic()
        result = {"schema_version": "1.0", "result_id": identifier("result"),
                  "incident_id": action["incident_id"], "trace_id": action["trace_id"],
                  "case_id": action.get("case_id"), "action_id": action["action_id"],
                  "timestamp": now(), "execution_status": "rejected", "exit_code": None,
                  "stdout": "", "stderr": "", "duration_ms": 0,
                  "post_observation_id": None, "verification": empty_verification()}
        operation = action["action"]
        target = action["target"]
        params = action["parameters"]
        reason = None
        if action["requires_approval"] or action["risk"] >= 0.7:
            reason = "Human approval required; automatic executor cannot approve actions"
        elif operation in {"start_service", "stop_service", "restart_service"}:
            if target not in {"api", "postgres", "redis"} or params:
                reason = "Service action requires an allowlisted target and empty parameters"
        elif operation == "reconfigure":
            if target != "api" or params != {"profile": "normal"}:
                reason = "Only api profile=normal is allowed for configuration recovery"
        elif operation == "no_action" and not params:
            result["execution_status"] = "skipped"
            return result
        else:
            reason = "Action is not supported by the A executor"
        # Shared permits extension fields, but executable requests cannot hide commands there.
        def contains_command(value):
            if isinstance(value, dict):
                return any(k.lower() in {"command", "shell", "script"} or contains_command(v)
                           for k, v in value.items())
            return isinstance(value, list) and any(contains_command(v) for v in value)
        if contains_command(action):
            reason = "Command fields are forbidden"
        if reason:
            result["stderr"] = reason
            return result
        output = (self.tools.set_database_profile("normal") if operation == "reconfigure"
                  else self.tools.operate(operation.removesuffix("_service"), target))
        result.update(output)
        result["execution_status"] = "succeeded" if output["exit_code"] == 0 else "failed"
        deadline = time.monotonic() + self.verify_timeout
        while True:
            observation = self.observe(action)
            healthy = (not observation.get("observation_conflicts")
                       and all(s["status"] == "healthy" for s in observation["services"].values()))
            business = observation["request"]["status_code"] == 200
            result["post_observation_id"] = observation["observation_id"]
            # A supplies measured evidence; B remains responsible for final incident verification.
            result["verification"] = {"status": "recovered" if healthy and business else "not_recovered",
                "checked_at": now(), "health_check_passed": healthy, "fault_cleared": None,
                "business_request_passed": business, "evidence": [
                    f"Observation {observation['observation_id']}",
                    f"GET /users returned {observation['request']['status_code']}",
                    "A checks service/business health; B must confirm the incident root cause is cleared"]}
            if healthy and business or output["exit_code"] != 0 or operation == "stop_service" or time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        result["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
        return result


def create_app(tools=None, observer=None, store=None, token=None, verify_timeout=20):
    tools = tools or SystemTools()
    observer = observer or Observer(tools)
    token = token if token is not None else os.getenv("REOPS_CONTROL_TOKEN", "")
    store = store or Store(ROOT / "runtime/control.sqlite3")
    executor = Executor(tools, observer, store, verify_timeout)

    def authenticate(authorization: str = Header(default="")):
        if not token or token.startswith("replace-with-"):
            raise HTTPException(503, "Configure a private REOPS_CONTROL_TOKEN first")
        if not hmac.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(401, "Invalid bearer token")

    app = FastAPI(title="ReOps A control plane", dependencies=[Depends(authenticate)])

    @app.get("/health")
    def control_health():
        return {"status": "healthy", "scope": "control-plane-only"}

    @app.post("/observations")
    def observe(context: Context):
        return executor.observe(context.model_dump())

    @app.get("/observations/{observation_id}")
    def get_observation(observation_id: str):
        value = store.get(observation_id)
        if not value or "observation_id" not in value:
            raise HTTPException(404, "Observation not found")
        return value

    @app.get("/services/{service}/status")
    def status(service: str):
        try:
            return tools.get_service_status(service)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/services/{service}/logs")
    def logs(service: str, tail: int = 100):
        try:
            return tools.get_logs(service, tail)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/actions")
    def execute(action: dict):
        return executor.execute(action)

    @app.post("/faults/{fault_id}")
    def inject(fault_id: str, context: Context):
        from fault_injection.service_failure import inject_fault
        with executor.lock:
            try:
                result = inject_fault(tools, fault_id, context.model_dump())
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            store.put(result["injection_id"], result)
            return result

    return app
