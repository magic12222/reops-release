"""把既有 B 真实 Memory 接入 C，或导出/导入可迁移的脱敏证据包；不运行实验。"""

import argparse
import hashlib
import json
import re
import os
from pathlib import Path

from dashboard_api.import_data import import_jsonl
from dashboard_api.normalize import from_experience_update
from dashboard_api.store import Store
from reops_agent.credential_handling import redact_persistent

ROOT = Path(__file__).resolve().parents[1]
MEMORIES = ("runtime/phase7d-memory.jsonl", "runtime/phase8b/memory.jsonl")


def read_memories(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_evidence_key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite_evidence")

    records = [json.loads(line, object_pairs_hook=unique, parse_constant=invalid)
               for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    for record in records:
        data = record.get("data", {})
        if data.get("real_model") is not True or data.get("real_observation") is not True:
            raise ValueError("explicit_real_evidence_required")
        from_experience_update(record, source="real")
    return records


def sync_history(root, db):
    # Only these known online Memory files; never scan test/audit directories as real.
    inputs = [(root / name, read_memories(root / name))
              for name in MEMORIES if (root / name).is_file()]
    store = Store(db)
    imported = 0
    for path, records in inputs:
        imported += import_jsonl(store, path, kind="experience-jsonl", source="real")
    return {"status": "ready" if imported else "no_local_evidence",
            "files": len(inputs), "records_read": imported,
            "real_runs": store.list_runs(source="real")[1],
            "model_calls": 0, "recovery_actions": 0}


def export_bundle(root, folder):
    if folder.exists():
        raise ValueError("export_destination_already_exists")
    records = []
    seen = {}
    for name in MEMORIES:
        path = root / name
        if not path.is_file():
            continue
        for raw in read_memories(path):
            record = redact_persistent(raw)
            from_experience_update(record, source="real")
            if record["event_id"] in seen:
                if seen[record["event_id"]] != record:
                    raise ValueError("conflicting_export_event")
                continue
            seen[record["event_id"]] = record
            records.append(record)
    if not records:
        raise ValueError("no_local_real_evidence")
    body = "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in records).encode("utf-8")
    protected = [value for key, value in os.environ.items()
                 if key.endswith(("_API_KEY", "_TOKEN", "_PASSWORD", "_SECRET")) and len(value) >= 8]
    local_env = root / ".env"
    if local_env.is_file():
        for line in local_env.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.partition("=")
            value = value.strip().strip("\"'")
            if separator and key.strip().endswith(("_API_KEY", "_TOKEN", "_PASSWORD", "_SECRET")) and len(value) >= 8:
                protected.append(value)
    if (re.search(rb"-----BEGIN .*PRIVATE KEY-----|\b(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{20,}", body)
            or any(value.encode("utf-8") in body for value in protected)):
        raise ValueError("unredacted_evidence_rejected")
    manifest = {"format": "reops-b-dashboard-evidence-v1", "source": "real",
                "source_is_operator_assertion": True, "historical_evidence": True,
                "file": "memory.jsonl", "sha256": hashlib.sha256(body).hexdigest(),
                "records": len(records), "contains_credentials_or_authorization_db": False}
    folder.mkdir(parents=True)
    (folder / "memory.jsonl").write_bytes(body)
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "README.md").write_text(
        "# B 历史证据数据包\n\n这是历史真实运行的脱敏副本，不代表接收机器当前系统健康。"
        "source 为操作者声明，SHA256 仅校验完整性，不是来源认证。"
        "不含 .env、密钥或授权数据库，导入不会调用模型、Docker 或恢复。\n\n"
        "在更新后的 ReOps 根目录导入：\n\n```powershell\n"
        "python -m scripts.sync_b_dashboard --bundle 数据包目录\n"
        "python -m scripts.run_dashboard\n```\n\n"
        "前端 Agent 选择 REAL 并刷新；不要选择内置静态 OFFLINE FIXTURE。\n", encoding="utf-8")
    return manifest


def import_bundle(folder, db):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("format") != "reops-b-dashboard-evidence-v1"
            or manifest.get("source") != "real" or manifest.get("file") != "memory.jsonl"):
        raise ValueError("invalid_evidence_manifest")
    path = folder / "memory.jsonl"
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get("sha256"):
        raise ValueError("evidence_hash_mismatch")
    records = read_memories(path)
    if type(manifest.get("records")) is not int or len(records) != manifest["records"]:
        raise ValueError("evidence_count_mismatch")
    store = Store(db)
    imported = import_jsonl(store, path, kind="experience-jsonl", source="real")
    return {"status": "ready", "records_read": imported,
            "real_runs": store.list_runs(source="real")[1],
            "model_calls": 0, "recovery_actions": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--export", type=Path)
    action.add_argument("--bundle", type=Path)
    parser.add_argument("--db", type=Path, default=ROOT / "runtime/dashboard-api.sqlite3")
    args = parser.parse_args()
    try:
        if args.export:
            result = export_bundle(ROOT, args.export.resolve())
        elif args.bundle:
            result = import_bundle(args.bundle.resolve(), args.db.resolve())
        else:
            result = sync_history(ROOT, args.db.resolve())
    except Exception as error:
        # Validation exceptions can include original evidence. Do not print their bodies.
        print(json.dumps({"status": "error", "error_type": type(error).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
