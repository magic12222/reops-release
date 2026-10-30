"""C-owned, read-only benchmark report imports and source-scoped evaluation."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from reops_agent.credential_handling import redact_persistent

SOURCES = {"real", "offline_fixture", "simulation"}
STRATEGIES = ("rule_based", "llm_only", "reops", "reops_without_memory")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("non-finite JSON value")


def _rate(rows, eligible, outcome):
    selected = [row for row in rows if eligible(row)]
    values = [outcome(row) for row in selected]
    missing = sum(type(value) is not bool for value in values)
    numerator = sum(value is True for value in values)
    denominator = len(selected)
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator and not missing else None,
            "missing": missing, "status": "missing_fields" if missing else
            "empty_denominator" if not denominator else "available"}


def _bool(value):
    return value if type(value) is bool else None


def _offline_metrics(cases):
    def expected(row, key): return row["expected"].get(key)
    def actual(row, key): return _bool(row["actual"].get(key))
    def match(key, actual_key=None):
        return _rate(cases, lambda c: key in c["expected"],
                     lambda c: None if actual(c, actual_key or key) is None or type(expected(c, key)) is not bool
                     else actual(c, actual_key or key) == expected(c, key))
    return {
        "detection_accuracy": match("failure_detected"),
        "fixture_rca_accuracy": _rate(cases, lambda c: "rca_root" in c["expected"],
            lambda c: None if "rca_root" not in c["actual"] else c["actual"]["rca_root"] == c["expected"]["rca_root"]),
        "plan_accuracy": _rate(cases, lambda c: "plan" in c["expected"],
            lambda c: None if "plan" not in c["actual"] else c["actual"]["plan"] == c["expected"]["plan"]),
        "safety_decision_accuracy": match("safety_allowed"),
        "recovery_success_rate": _rate(cases, lambda c: actual(c, "executor_called") is True,
                                        lambda c: actual(c, "recovery_executed")),
        "verify_success_rate": _rate(cases, lambda c: actual(c, "recovery_executed") is True,
                                      lambda c: actual(c, "recovery_verified")),
        "false_recovery_rate": _rate(cases, lambda c: expected(c, "recovery_verified") is False,
                                     lambda c: actual(c, "recovery_verified")),
        "no_action_accuracy": _rate(cases, lambda c: expected(c, "executor_called") is False,
                                    lambda c: None if actual(c, "executor_called") is None else not actual(c, "executor_called")),
        "unsafe_action_rejection_rate": _rate(cases, lambda c: c.get("category") == "unsafe",
                                    lambda c: None if actual(c, "executor_called") is None else not actual(c, "executor_called")),
    }


def _strategy_metrics(cases, strategy):
    rows = [(case, case["methods"][strategy]) for case in cases]
    def recovered(row): return _bool(row[1]["actual"].get("fixture_recovery_verified"))
    return {
        "fixture_recovery_rate": _rate(rows, lambda r: r[0].get("failure_detected") is True, recovered),
        "expected_behavior_accuracy": _rate(rows, lambda r: True, lambda r: _bool(r[1].get("passed"))),
        "strategy_selection_accuracy": _rate(rows, lambda r: "strategy" in r[1]["expected"],
            lambda r: None if "strategy" not in r[1]["actual"] else
            r[1]["actual"]["strategy"] == r[1]["expected"]["strategy"]),
        "false_recovery_rate": _rate(rows, lambda r: r[0].get("failure_detected") is False or
            r[1]["expected"].get("recovered") is False, recovered),
        "no_action_accuracy": _rate(rows, lambda r: r[1]["expected"].get("strategy") == "no_action",
              lambda r: None if "fixture_action_count" not in r[1]["actual"] else r[1]["actual"]["fixture_action_count"] == 0),
    }


def _model_calls(cases, strategy=None):
    values = [c["methods"][strategy]["actual"].get("model_calls") if strategy else c["actual"].get("model_calls") for c in cases]
    return sum(values) if all(type(v) is int and v >= 0 for v in values) else None


def _outcomes(cases, strategy=None):
    """Keep refusal, absent execution and unknown results visible outside rate denominators."""
    values = [c["methods"][strategy]["actual"] if strategy else c["actual"] for c in cases]
    if strategy:
        return {"not_executed": sum(v.get("fixture_action_count") == 0 for v in values),
                "result_unknown": sum(v.get("final_status") in {"unknown", "inconclusive"} for v in values),
                "rejected": sum(v.get("safety_allowed") is False for v in values)}
    return {"not_executed": sum(v.get("executor_called") is False for v in values),
            "result_unknown": sum(v.get("executor_called") is True and
                v.get("recovery_executed") is not True and
                v.get("verification_status") in {"unknown", "inconclusive"} for v in values),
            "rejected": sum(v.get("safety_allowed") is False or
                v.get("recovery_authorized") is False for v in values)}


def _validate_report(report, source):
    if source not in SOURCES:
        raise ValueError("invalid source")
    if not isinstance(report, dict) or report.get("mode") not in {"offline-fixture", "offline-fixture-comparison"}:
        raise ValueError("unsupported benchmark report mode")
    if source != "offline_fixture":
        raise ValueError("offline benchmark reports require offline_fixture source")
    cases = report.get("cases")
    if not isinstance(cases, list) or type(report.get("case_count")) is not int or report["case_count"] != len(cases):
        raise ValueError("case count mismatch")
    if len({c.get("case_id") for c in cases if isinstance(c, dict)}) != len(cases):
        raise ValueError("duplicate or invalid case")
    strategy = report["mode"] == "offline-fixture-comparison"
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"]:
            raise ValueError("invalid case")
        if strategy:
            methods = case.get("methods")
            if not isinstance(methods, dict) or any(not isinstance(methods.get(name), dict) or
                not isinstance(methods[name].get("actual"), dict) or not isinstance(methods[name].get("expected"), dict)
                for name in STRATEGIES):
                raise ValueError("invalid strategy methods")
        elif not isinstance(case.get("actual"), dict) or not isinstance(case.get("expected"), dict):
            raise ValueError("invalid offline case")
    if strategy and (report.get("report_schema_version") != "1.0" or not isinstance(report.get("provenance"), dict)):
        raise ValueError("invalid strategy provenance")
    return strategy


def _report_identity(report, source, strategy):
    """Deduplicate repeat harness runs despite random trace IDs and JSON formatting."""
    if strategy:
        behavior = [{"case_id": c["case_id"], "suite": c.get("suite"),
                     "failure_detected": c.get("failure_detected"),
                     "methods": {name: {key: c["methods"][name].get(key)
                         for key in ("actual", "expected", "checks", "passed")}
                         for name in STRATEGIES}} for c in report["cases"]]
    else:
        behavior = [{key: c.get(key) for key in ("case_id", "category", "actual", "expected", "checks", "passed")}
                    for c in report["cases"]]
    data = {"source": source, "mode": report["mode"], "provenance": report.get("provenance"),
            "fixture_sha256": report.get("fixture_sha256"), "behavior": behavior}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class BenchmarkStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS benchmark_reports (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, mode TEXT NOT NULL,
                generated_at TEXT, sample_count INTEGER NOT NULL, provenance TEXT NOT NULL,
                report_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS benchmark_import_errors (
                source TEXT PRIMARY KEY, code TEXT NOT NULL)""")

    def import_file(self, path, *, source):
        if source not in SOURCES:
            raise ValueError("invalid source")
        try:
            raw = Path(path).read_bytes()
            report = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_invalid_constant)
            strategy = _validate_report(report, source)
            identity = _report_identity(report, source, strategy)
        except (OSError, UnicodeError, ValueError, TypeError):
            with sqlite3.connect(self.path) as db:
                db.execute("INSERT INTO benchmark_import_errors VALUES (?,?) ON CONFLICT(source) DO UPDATE SET code=excluded.code",
                           (source, "invalid_report"))
            raise
        provenance = report.get("provenance") if strategy else {"fixture_sha256": report.get("fixture_sha256")}
        clean = redact_persistent(report)
        with sqlite3.connect(self.path) as db:
            old = db.execute("SELECT id FROM benchmark_reports WHERE id=?", (identity,)).fetchone()
            if old is None:
                db.execute("INSERT INTO benchmark_reports VALUES (?,?,?,?,?,?,?)", (
                    identity, source, report["mode"], report.get("generated_at"), len(report["cases"]),
                    json.dumps(redact_persistent(provenance), ensure_ascii=False, allow_nan=False),
                    json.dumps(clean, ensure_ascii=False, allow_nan=False)))
            db.execute("DELETE FROM benchmark_import_errors WHERE source=?", (source,))
        return {"id": identity, "duplicate": old is not None, "source": source, "sample_count": len(report["cases"])}

    def list(self, source):
        if source not in SOURCES: raise ValueError("invalid source")
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT id,source,mode,generated_at,sample_count,provenance FROM benchmark_reports WHERE source=? ORDER BY rowid DESC", (source,)).fetchall()
        return [{"id": r[0], "source": r[1], "mode": r[2], "generated_at": r[3],
                 "sample_count": r[4], "provenance": json.loads(r[5])} for r in rows]

    def last_import_error(self, source):
        if source not in SOURCES: raise ValueError("invalid source")
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT code FROM benchmark_import_errors WHERE source=?", (source,)).fetchone()
        return row[0] if row else None

    def evaluation(self, report_id, source):
        if source not in SOURCES: raise ValueError("invalid source")
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT report_json FROM benchmark_reports WHERE id=? AND source=?", (report_id, source)).fetchone()
        if row is None: return None
        report = json.loads(row[0]); cases = report["cases"]
        if report["mode"] == "offline-fixture":
            groups = [{"strategy": "phase7d", "suite": "all", "sample_count": len(cases),
                       "metrics": _offline_metrics(cases), "fixture_model_calls": _model_calls(cases),
                       "real_model_calls": None, "recovery_latency_ms": None,
                       "case_ids": [c["case_id"] for c in cases], "outcomes": _outcomes(cases)}]
        else:
            suites = ["all"] + sorted({c["suite"] for c in cases})
            groups = []
            for suite in suites:
                subset = cases if suite == "all" else [c for c in cases if c["suite"] == suite]
                for strategy in STRATEGIES:
                    groups.append({"strategy": strategy, "suite": suite, "sample_count": len(subset),
                                   "metrics": _strategy_metrics(subset, strategy),
                                   "fixture_model_calls": _model_calls(subset, strategy),
                                   "real_model_calls": None, "recovery_latency_ms": None,
                                   "case_ids": [c["case_id"] for c in subset],
                                   "outcomes": _outcomes(subset, strategy)})
        return {"id": report_id, "source": source, "mode": report["mode"],
                "sample_count": len(cases), "generated_at": report.get("generated_at"),
                "provenance": report.get("provenance") or {"fixture_sha256": report.get("fixture_sha256")},
                "groups": groups}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import an existing offline benchmark report into C")
    parser.add_argument("--path", required=True)
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "runtime/dashboard-api.sqlite3"))
    args = parser.parse_args(argv)
    print(json.dumps(BenchmarkStore(args.db).import_file(args.path, source=args.source)))


if __name__ == "__main__":
    main()
