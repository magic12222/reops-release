"""启动本机 Dashboard API，并在服务端连接既有 A 控制面。"""

import os
import argparse
import json
from pathlib import Path

import uvicorn

from scripts.run_control import load_local_token
from scripts.sync_b_dashboard import ROOT, sync_history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument('--mobile-read-only', action='store_true', help='仅在原8020提供移动只读查询；不导入、不启动监控/模型/恢复')
    parser.add_argument("--researchloop-web", action="store_true", help="启用本机ResearchLoop网页逐项人工授权入口")
    parser.add_argument("--workbench-monitoring", action="store_true", help="启用本机工作台的显式目标选择与监控控制，不开放恢复")
    parser.add_argument("--workbench-agent", action="store_true", help="同进程接通B持久诊断，须配合--workbench-monitoring；不启用模型和恢复")
    args = parser.parse_args()
    if args.mobile_read_only:
        if args.researchloop_web or args.workbench_monitoring or args.workbench_agent:
            parser.error('--mobile-read-only cannot enable model or monitoring controls')
        configured = os.getenv('REOPS_B_STATE_DB', '')
        if not configured or not Path(configured).resolve().is_relative_to(ROOT) or not Path(configured).is_file():
            parser.error('REOPS_B_STATE_DB must point to an existing database inside this project')
        uvicorn.run('dashboard_api.api:create_mobile_read_app', factory=True,
                    host='127.0.0.1', port=8020, workers=1)
        return
    if args.workbench_agent and not args.workbench_monitoring:
        parser.error("--workbench-agent requires --workbench-monitoring")
    if args.workbench_agent:
        os.environ["REOPS_WORKBENCH_AGENT"] = "1"
    if args.workbench_monitoring:
        os.environ["REOPS_WORKBENCH_MONITORING"] = "1"
    if args.researchloop_web:
        os.environ["REOPS_RESEARCHLOOP_WEB"] = "1"
    load_local_token()
    os.environ.setdefault("REOPS_C_TARGET_URL", "http://127.0.0.1:18000")
    os.environ.setdefault("REOPS_C_CONTROL_URL", "http://127.0.0.1:8010")
    # C4 is the dashboard's supported B execution entry; its journal is not a test log.
    if not os.getenv("REOPS_C_JOURNAL_PATH") and not os.getenv("REOPS_C_JOURNAL_SOURCE"):
        os.environ["REOPS_C_JOURNAL_PATH"] = str(ROOT / "runtime/c4-audit.jsonl")
        os.environ["REOPS_C_JOURNAL_SOURCE"] = "real"
    if not args.skip_history:
        db = os.getenv("REOPS_C_DB_PATH", str(ROOT / "runtime/dashboard-api.sqlite3"))
        try:
            print(json.dumps({"b_history": sync_history(ROOT, db)}), flush=True)
        except Exception as error:
            raise SystemExit("B history import failed: " + type(error).__name__) from None
    uvicorn.run("dashboard_api.api:create_app", factory=True,
                host="127.0.0.1", port=8020, workers=1)


if __name__ == "__main__":
    main()
