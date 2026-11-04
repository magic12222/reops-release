"""Vikunja持续监控与网页范围批准；可显式接通B，启动时模型和自动恢复关闭。"""
import argparse
import errno
import json
import os
from getpass import getpass

import uvicorn

from dashboard_api.vikunja_control import VikunjaMonitorControl, install_vikunja_routes
from scripts.run_workbench_preview import create_app
from scripts.vikunja_baseline import BusinessSession, baseline
from workbench.vikunja_target import VikunjaDocker, VikunjaMonitor


class MonitoringPortInUse(OSError):
    """A fixed local monitoring port is occupied; do not expose raw OS details."""


def check_monitoring_port():
    import socket
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", 8021))
        except OSError as error:
            if error.errno == errno.EADDRINUSE or getattr(error, "winerror", None) == 10048:
                raise MonitoringPortInUse() from None
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="明确创建新演示数据并启动8021；与原预览互斥")
    parser.add_argument("--login", action="store_true", help="使用已有演示账号；密码仅从本次进程内存或密码输入读取")
    parser.add_argument("--paused", action="store_true", help="录制准备：连接目标后等待网页点击开启业务监控")
    parser.add_argument("--agent", action="store_true", help="接通Vikunja专用B诊断/经验；已批准演示走原恢复范围，模型关闭")
    parser.add_argument("--import-baseline", action="store_true", help="仅将SHA256固定的已验收原件投影为历史经验，不重放")
    parser.add_argument('--history-read-only', action='store_true', help='原8021只读查询既存BStore及固定归档；不创建演示业务数据')
    parser.add_argument('--live-monitoring', action='store_true', help='实时Vikunja业务监控与历史查询；新独立任务基线，无模型/恢复')
    parser.add_argument('--lan-ip', help='查询模式可选：明确私网IPv4，TLS移动入口8443')
    parser.add_argument('--lan-cidr', help='查询模式可选：明确允许的私网子网，最多4096个地址')
    parser.add_argument('--usb-access', action='store_true', help='查询模式另提供回环TLS8443，供已授权hdc USB转发')
    args = parser.parse_args()
    if args.history_read_only or args.live_monitoring:
        if args.history_read_only and args.live_monitoring:
            parser.error('--history-read-only and --live-monitoring are mutually exclusive')
        if args.serve or args.login or args.paused or args.agent or args.import_baseline:
            parser.error('read API modes cannot enable recovery controls or agent')
        from scripts.serve_history_access import serve
        serve(lan_ip=args.lan_ip, lan_cidr=args.lan_cidr, usb_access=args.usb_access,
              **({'live_monitoring': True} if args.live_monitoring else {}))
        return 0
    if args.lan_ip or args.lan_cidr or args.usb_access:
        parser.error('--lan-ip/--lan-cidr/--usb-access require --history-read-only or --live-monitoring')
    if args.import_baseline and (not args.agent or not args.serve):
        parser.error("--import-baseline requires --serve --agent")
    inspection = VikunjaDocker().inspect()
    if not args.serve:
        print(json.dumps({"target_id": "reops-vikunja-demo", "scope": inspection.identity.binding(),
            "app_running": inspection.running, "postgres_running": inspection.postgres_running,
            "business_tested": False, "model_calls": 0, "fault_injected": False}))
        return 0
    # Check port before writing demo data; never terminate another preview process.
    check_monitoring_port()
    credentials = {}
    if args.login:
        username = os.environ.pop("REOPS_VIKUNJA_LOGIN_USER", None)
        password = os.environ.pop("REOPS_VIKUNJA_LOGIN_PASSWORD", None)
        credentials = {"username": username or input("演示账号: "), "password": password or getpass("密码: ")}
        password = None
    session = BusinessSession(**credentials)
    credentials.clear()
    monitor = None
    try:
        report = baseline(session)
        if not report["passed"]:
            raise ValueError("business_baseline_failed")
        monitor = VikunjaMonitor(session)
        # --serve explicitly starts continuous observation of this fixed target.
        # Recovery permissions remain off until a separate browser click.
        monitor.select()
        if not args.paused:
            monitor.start()
        if args.import_baseline:
            from workbench.b_store import BStore
            from workbench.b_vikunja_archive import import_verified_baseline
            from reops_agent.contracts import PROJECT_ROOT
            imported = import_verified_baseline(BStore(PROJECT_ROOT / "runtime/vikunja-b/state.sqlite3"))
            print(json.dumps({"historical_baseline_projection": imported, "original_b_agent_closed_loop": False}), flush=True)
        control = VikunjaMonitorControl(monitor, agent=args.agent, discovery=True)
        app = create_app(monitoring=True, control=control)
        install_vikunja_routes(app, control)
        print(json.dumps({"baseline": report, "monitoring": "paused_until_browser_start" if args.paused else "continuous_until_paused_or_service_stopped",
                          "automatic_recovery": "off_until_explicit_browser_click"}), flush=True)
        uvicorn.run(app, host="127.0.0.1", port=8021, workers=1)
    finally:
        try:
            if monitor is not None:
                monitor.close()
        finally:
            session.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MonitoringPortInUse:
        print(json.dumps({"passed": False, "error": "monitoring_port_in_use", "port": 8021,
            "message": "8021端口已被占用。若ReOps已运行，请直接打开http://127.0.0.1:5174/workbench；不要重复启动。需要重启时请先在原监控终端按Ctrl+C。"}, ensure_ascii=False))
        raise SystemExit(1) from None
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}))
        raise SystemExit(1) from None
