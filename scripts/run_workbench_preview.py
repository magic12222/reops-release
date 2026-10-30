"""独立工作台服务；--monitoring 仅启用显式只读目标监控，不加载模型或恢复权限。"""
import argparse
from fastapi import FastAPI
import uvicorn
from dashboard_api.workbench import install_workbench_routes
from dashboard_api.workbench_control import MonitorControl, install_monitor_routes


def create_app(*, monitoring=False, agent=False, control=None, discovery=False):
    control = control or MonitorControl(enabled=monitoring, agent=agent, discovery=discovery)
    app = FastAPI(title="ReOps workbench preview", lifespan=lambda app: control.lifespan())
    install_workbench_routes(app)
    install_monitor_routes(app, control)
    app.state.workbench_control = control
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monitoring", action="store_true", help="允许网页显式选择、开始或暂停监控，不操作目标进程")
    parser.add_argument("--agent", action="store_true", help="接通B持久诊断与经验读取，须配合--monitoring；模型和恢复均关闭")
    args = parser.parse_args()
    if args.agent and not args.monitoring:
        parser.error("--agent requires --monitoring")
    uvicorn.run(create_app(monitoring=args.monitoring, agent=args.agent, discovery=args.monitoring), host="127.0.0.1", port=8021, workers=1)
