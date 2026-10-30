"""C 所有：装配 A/B 快照，统一校验关联，不触发任何监控或恢复副作用。"""

from datetime import datetime, timezone

from fastapi import HTTPException

from workbench import a_adapter, b_adapter
from workbench.contracts import Snapshot


def read_snapshot() -> Snapshot:
    a = a_adapter.read_targets()
    b = b_adapter.read_agent()
    from workbench.legacy_knowledge import historical_targets
    historical = historical_targets(b.incidents)
    return Snapshot(schema_version="0.1", source="real",
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    a_status=a.status, b_status=b.status,
                    targets=[*a.targets,*historical], incidents=b.incidents, experiences=b.experiences)


def install_workbench_routes(app):
    @app.get("/api/v1/workbench/snapshot", response_model=Snapshot)
    def snapshot():
        try:
            return read_snapshot()
        except Exception:
            # 生产者异常可能携带原始上下文；固定错误不向浏览器泄漏它。
            raise HTTPException(503, "workbench_snapshot_unavailable") from None
