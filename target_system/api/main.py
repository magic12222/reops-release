"""Disposable demonstration workload; control plane lives outside this service."""
import json
import logging
import os
import time
from datetime import datetime, timezone

import psycopg
import redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("reops.workload")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def emit(step, status, **fields):
    logger.info(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                            "source": "api", "step": step, "status": status, **fields}))


def connect_db():
    # The test profile changes the actual connection password, not the response.
    bad = os.getenv("REOPS_DB_PROFILE") == "bad_password"
    return psycopg.connect(host=os.getenv("POSTGRES_HOST", "postgres"),
                           dbname=os.getenv("POSTGRES_DB", "reops"),
                           user=os.getenv("POSTGRES_USER", "reops"),
                           password="deliberately-invalid" if bad else os.environ["POSTGRES_PASSWORD"],
                           connect_timeout=2)


def cache():
    return redis.Redis(host=os.getenv("REDIS_HOST", "redis"), socket_connect_timeout=2,
                       socket_timeout=2, decode_responses=True)


def check_dependencies():
    services = {}
    for name in ("postgres", "redis"):
        started = time.monotonic()
        try:
            if name == "postgres":
                with connect_db() as conn:
                    conn.execute("SELECT 1").fetchone()
            else:
                with cache() as client:
                    client.ping()
            services[name] = {"status": "healthy", "message": None}
        except Exception as exc:
            # Do not serialize credentials or raw driver connection strings.
            services[name] = {"status": "unhealthy", "message": type(exc).__name__}
        services[name]["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
    return services


app = FastAPI(title="ReOps target workload")


@app.get("/health/live")
def live():
    return {"status": "healthy"}


@app.get("/health")
def health():
    services = check_dependencies()
    healthy = all(s["status"] == "healthy" for s in services.values())
    return JSONResponse({"status": "healthy" if healthy else "unhealthy", "services": services},
                        status_code=200 if healthy else 503)


@app.get("/users")
def users(request: Request):
    trace_id = request.headers.get("X-Trace-ID", "unassigned")[:128]
    # Always touch both dependencies: a warm cache must not hide PostgreSQL Down.
    step = "database_query"
    try:
        with connect_db() as conn:
            rows = conn.execute("SELECT id, name FROM users ORDER BY id").fetchall()
        emit(step, "succeeded", trace_id=trace_id)
        step = "cache_write"
        with cache() as client:
            client.set("reops:last_user_count", len(rows), ex=60)
        emit(step, "succeeded", trace_id=trace_id)
        return {"users": [{"id": row[0], "name": row[1]} for row in rows]}
    except Exception as exc:
        emit(step, "failed", trace_id=trace_id, error_type=type(exc).__name__,
             sqlstate=getattr(exc, "sqlstate", None))
        return JSONResponse({"error": "dependency_failure", "step": step,
                             "error_type": type(exc).__name__}, status_code=503)
