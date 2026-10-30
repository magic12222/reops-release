"""隔离数据库场景正式终端入口；默认只读，--run仍需原人类挑战。"""
import argparse
from dataclasses import replace
import json
import os
import sys
from uuid import uuid4

from dashboard_api.experiments import ExperimentLedger
from dashboard_api.researchloop import DatabaseLedger
from dashboard_api.live import DashboardEventSink, JournalFollower
from dashboard_api.store import Store
from reops_agent.authorization import AuthorizationGate
from reops_agent.contracts import PROJECT_ROOT
from reops_agent.credential_handling import redact_persistent
from reops_agent.memory import RecoveryMemory
from reops_agent.nexent_provider import NexentConfig, NexentRCAProvider
from reops_agent.researchloop_backend import ResearchLoopBackend, healthy
from reops_agent.researchloop_recovery import run_database
from reops_agent.trace_journal import TraceJournal
from scripts.researchloop_baseline import BusinessSession


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(redact_persistent(value), stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--experience-fast-path", action="store_true")
    args = parser.parse_args(argv)
    if not args.run:
        # 不建账号/不写库/不读凭据；只核对部署归属和进程健康。
        backend = ResearchLoopBackend(None)
        print(json.dumps({"mode": "read-only", "scope": backend.scope(),
            "database_business_baseline_tested": False, "model_calls": 0, "faults": 0}))
        return 0
    if not sys.stdin.isatty():
        raise SystemExit("database_experiment_requires_original_interactive_terminal")
    db_path = os.getenv("REOPS_C_DB_PATH", str(PROJECT_ROOT / "runtime/dashboard-api.sqlite3"))
    if ExperimentLedger(db_path).has_hold():
        raise SystemExit("C4_requires_operator_inspection")
    ledger = DatabaseLedger(db_path)
    if any(item.get("review_required") is not False for item in ledger.list()):
        raise SystemExit("database_experiment_requires_operator_inspection")
    # 加载配置不代表调用；每次模型调用仍在Gate消费之后。
    config = replace(NexentConfig.from_env(), max_output_tokens=512)
    config.require_real_model()
    if config.api_base.rstrip("/") != "http://aigw.dlut.edu.cn/v1" or config.model_id != "DeepSeek-V3.1-W8A8":
        raise SystemExit("database_model_scope_rejected")
    context = {"incident_id": "incident-researchloop-" + uuid4().hex,
               "trace_id": "trace-researchloop-" + uuid4().hex}
    directory = PROJECT_ROOT / "runtime/researchloop-evidence" / context["trace_id"]
    directory.mkdir(parents=True, exist_ok=False)
    write_new(directory / "request.json", {**context, "scenario": "researchloop_stopped_postgres",
        "experience_fast_path_requested": args.experience_fast_path, "max_model_calls": 1,
        "max_output_tokens": 512, "max_fault_injections": 1, "max_recovery_actions": 1})
    business = BusinessSession()
    try:
        backend = ResearchLoopBackend(business)
        baseline = backend.observe({"schema_version": "1.0", **context})
        if not healthy(baseline):
            raise SystemExit("database_business_baseline_failed_no_injection")
        record = ledger.claim_new(context)
        sink = DashboardEventSink(Store(db_path), source="real")
        class PublishingJournal(TraceJournal):
            def record(self, *items, **kwargs):
                event = super().record(*items, **kwargs)
                sink.publish(event)
                return event
        journal = PublishingJournal(context, PROJECT_ROOT / "runtime/researchloop-audit.jsonl")
        report = run_database(backend, NexentRCAProvider(config), gate=AuthorizationGate(
            PROJECT_ROOT / "runtime/researchloop-authorizations.sqlite3"), journal=journal,
            memory=RecoveryMemory(PROJECT_ROOT / "runtime/researchloop-memory.jsonl"),
            model_identifier=config.model_id, execute=True, fast_path=args.experience_fast_path)
        saved = False
        try:
            write_new(directory / "report.json", report)
            saved = True
            # 将独立cleanup也通过原归一化通道导入；不复制原授权库。
            JournalFollower(sink, journal.path).poll()
        finally:
            finished = ledger.finish(record["id"], report, saved=saved)
        print(json.dumps({"experiment_id": record["id"], "result": finished["result"],
            "review_required": finished["review_required"], "trace_id": context["trace_id"],
            "model_calls": report["model_calls"], "repair_usage": report["repair_usage"]}))
        return 0 if finished["result"] == "passed" else 1
    finally:
        business.close()


if __name__ == "__main__":
    raise SystemExit(main())
