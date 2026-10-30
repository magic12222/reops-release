"""Explicit single-process A+B host and existing read-only workbench routes."""
from pathlib import Path

from fastapi import FastAPI

from dashboard_api.workbench import install_workbench_routes
from reops_agent.authorization import AuthorizationGate
from . import a_adapter, b_adapter
from .a_docker import TARGET_ID
from .a_monitor import TargetMonitor
from .b_a_port import WorkbenchAPort
from .b_runtime import BRuntime, TargetPolicy
from .b_store import BStore, now


class WorkbenchHost:
    def __init__(self, directory, *, monitor=None, provider=None, model="unknown", execute=False,
                 gate=None, source="real"):
        self.directory = Path(directory)
        self.monitor = monitor or TargetMonitor()
        self.provider, self.model, self.execute = provider, model, execute
        self.gate = gate or AuthorizationGate(self.directory / "authorizations.sqlite3")
        self.source = source
        self.store = self.runtime = None
        self.last_id = None
        self.started = False

    def start(self, *, watching=False, select=True):
        if self.started:
            raise RuntimeError("b_host_already_started")
        try:
            if select:
                self.monitor.select()
            self.store = BStore(self.directory / "state.sqlite3", source=self.source)
            from .vikunja_target import VikunjaMonitor, TARGET_ID as VIKUNJA_TARGET
            from .b_vikunja import PROFILE, BUSINESS_ENDPOINT, VikunjaAPort
            if isinstance(self.monitor, VikunjaMonitor):
                port = VikunjaAPort(self.monitor)
                policy = TargetPolicy(VIKUNJA_TARGET, VIKUNJA_TARGET, "isolated-demo",
                    allowed_actions=(("start_service", "postgres"),), business_endpoint=BUSINESS_ENDPOINT, profile=PROFILE)
            else:
                port = WorkbenchAPort(self.monitor)
                policy = TargetPolicy(TARGET_ID, "reops-lab", "docker-local", allowed_actions=(("start_service", "web"),), profile="a_workbench_start")
            self.runtime = BRuntime(self.store, port, policy,
                gate=self.gate, provider=self.provider, model=self.model, execute=self.execute,
                a_timeout=30, action_timeout=90, sample_max_age=60)
            a_adapter.install(self.monitor)
            b_adapter.install(self.store)
            if watching:
                self.monitor.start()
            self.started = True
        except BaseException:
            self.close()
            raise

    def tick(self):
        if not self.started or not self.runtime:
            raise RuntimeError("b_host_not_started")
        if getattr(self, "suspended", lambda: False)():
            return None
        targets = self.monitor.read_targets()
        if not targets.targets or targets.targets[0].monitoring != "watching":
            return None
        observation = self.monitor.latest_observation()
        if observation is None or observation["observation_id"] == self.last_id:
            return None
        self.last_id = observation["observation_id"]
        try:
            return self.runtime.notify(self.runtime.policy.target_id, observation)
        except (ValueError, TimeoutError, RuntimeError):
            return self.runtime.observation_failed(self.runtime.policy.target_id)

    def close(self):
        try:
            self.monitor.close()
        finally:
            a_adapter.uninstall(self.monitor)
            if self.store is not None:
                b_adapter.uninstall(self.store)
            self.started = False

    def export(self):
        """Explicit operator export; fixture source remains fixture."""
        from .b_store import read_feed
        from .contracts import Snapshot
        feed = read_feed(self.store.path, allow_fixture=self.source == "offline_fixture")
        targets = self.monitor.read_targets()
        return Snapshot(schema_version="0.1", source=self.source, generated_at=now(),
            a_status=targets.status, b_status=feed.status, targets=targets.targets,
            incidents=feed.incidents, experiences=feed.experiences)


def create_app():
    # Lifecycle is owned by the explicit operator host, never a request handler.
    app = FastAPI(title="ReOps integrated A/B workbench (read only)")
    install_workbench_routes(app)
    return app
