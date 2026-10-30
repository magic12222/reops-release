"""固定依赖恢复的离线时序、身份、批准、预算与不确定失败回归。"""
from dataclasses import replace
import json
import sqlite3
from threading import Event, Thread

import pytest

from test_vikunja_web import healthy_monitor, web
from test_workbench_control import headers
from dashboard_api.vikunja_control import RECOVERY
from workbench.vikunja_automation import VikunjaAutomation
from workbench.vikunja_dependency import PLAN, DependencyRun, dependency_failure
from workbench.vikunja_target import VikunjaDocker
from workbench.a_docker import TargetError
from reops_agent.authorization import AuthorizationError


def test_status_keeps_publishing_real_events_while_recovery_holds_execution_lock(tmp_path, monkeypatch):
    monitor, backend, automation, _ = fixture(tmp_path, monkeypatch)
    entered, release, read_done = Event(), Event(), Event()
    start = backend.start_dependency
    def blocked_start(*args):
        entered.set()
        assert release.wait(3)
        return start(*args)
    backend.start_dependency = blocked_start
    worker = Thread(target=lambda: trigger(monitor, automation))
    reader_result = []
    def read_status():
        reader_result.append(automation.status('reader'))
        read_done.set()
    worker.start()
    try:
        assert entered.wait(2)
        reader = Thread(target=read_status)
        reader.start()
        assert read_done.wait(.5), 'status waited for the recovery execution lock'
        value = reader_result[0]
        assert value['inflight'] and value['state'] == 'recovering'
        assert value['offer_id'] is None and value['dependency_offer_id'] is None
        assert any(event['event'] == 'fault_confirmed' for event in value['events'])
        assert not any(event['event'] == 'recovery_verified' for event in value['events'])
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert automation.status()['state'] == 'watching'


def fixture(tmp_path, monkeypatch, *, dead=True):
    monitor = healthy_monitor()
    backend = monitor.backend
    original = backend.inspect
    backend.app_alive = True
    backend.epoch = original().app_started_at
    backend.calls = []
    backend.sql_ready = True
    backend.exit_valid = True
    backend.inspect = lambda: replace(original(), running=backend.app_alive, app_started_at=backend.epoch)
    backend.database_stop_time = lambda identity: "2026-10-28T00:00:00Z"
    backend.dependency_exit = lambda *args: {"database_finished_at":"2026-10-28T00:00:00Z",
        "app_finished_at":"2026-10-28T00:00:25Z", "source":"docker_state_and_events"} if backend.exit_valid else False
    backend.sql_probe = lambda identity: not backend.stopped and backend.sql_ready
    def start(identity, service, epoch, evidence):
        assert identity == backend.identity and epoch == backend.epoch
        backend.calls.append(service)
        if service == "postgres":
            assert backend.stopped
            backend.stopped = False
        else:
            assert service == "app" and not backend.app_alive and backend.sql_probe(identity) and evidence
            backend.app_alive = True
            backend.epoch = "2026-10-28T00:01:00Z"
    backend.start_dependency = start
    automation = VikunjaAutomation(monitor, tmp_path)
    automation.enable("owner", automation.status("owner")["dependency_offer_id"], plan_id=PLAN)
    backend.stopped, backend.app_alive = True, not dead
    clock = [0.0]
    def sleep(seconds): clock[0] += seconds
    import workbench.vikunja_automation as module
    monkeypatch.setattr(module, "DependencyRun", lambda owner, context: DependencyRun(owner, context, clock=lambda:clock[0], sleep=sleep))
    return monitor, backend, automation, clock


def trigger(monitor, automation):
    for _ in range(2):
        monitor.observe("incident-test", "trace-test")
        automation.tick()


@pytest.mark.parametrize("dead", [False, True])
def test_two_fresh_failures_recover_ordered_dependency_and_two_fresh_business_checks(tmp_path, monkeypatch, dead):
    m, b, a, _ = fixture(tmp_path, monkeypatch, dead=dead)
    trigger(m, a)
    assert b.calls == (["postgres", "app"] if dead else ["postgres"])
    assert a.active and a.actions == 1 and a.state == "watching"
    names = [e["event"] for e in a.events]
    ordered = ["fault_confirmed", "database_started", "sql_ready",
        "application_started" if dead else "application_start_skipped", "verification_started", "recovery_verified"]
    assert [names.index(e) for e in ordered] == sorted(names.index(e) for e in ordered)
    final = a.events[-1]
    assert len(set(final["observations"])) == 2 and final["model_calls"] == 0
    with sqlite3.connect(tmp_path / "authorizations.sqlite3") as db:
        assert db.execute("select count(*) from reservations").fetchone()[0] == len(b.calls)
    a.tick()
    assert len(b.calls) == (2 if dead else 1)


def test_application_can_exit_during_database_start_and_sql_wait(tmp_path, monkeypatch):
    m, b, a, _ = fixture(tmp_path, monkeypatch, dead=False)
    start = b.start_dependency
    def exit_during_start(*args):
        start(*args)
        if args[1] == "postgres": b.app_alive = False
    b.start_dependency = exit_during_start
    trigger(m, a)
    assert b.calls == ["postgres", "app"] and a.events[-1]["event"] == "recovery_verified"


@pytest.mark.parametrize("failure", ["no_exit_proof", "sql", "business", "identity", "app_epoch", "uncertain_start", "audit"])
def test_failure_stops_without_replay_or_false_success(tmp_path, monkeypatch, failure):
    m, b, a, _ = fixture(tmp_path, monkeypatch)
    if failure == "no_exit_proof": b.exit_valid = False
    if failure == "sql": b.sql_ready = False
    if failure == "business": m.business.read = lambda: (401, False)
    if failure == "identity": b.identity = replace(b.identity, app_id="e"*64)
    if failure == "app_epoch": b.epoch = "2026-10-28T00:00:26Z"
    if failure == "uncertain_start":
        def uncertain(*args):
            b.calls.append(args[1]); b.stopped = False
            raise TimeoutError()
        b.start_dependency = uncertain
    if failure == "audit":
        record = a.record
        def fail(event, **fields):
            if event == "dependency_action_reserved": raise OSError()
            record(event, **fields)
        a.record = fail
    trigger(m, a)
    assert not a.active and a.state == ("observe" if failure in {"identity","app_epoch"} else "attention")
    assert "recovery_verified" not in [e["event"] for e in a.events]
    previous = list(b.calls)
    trigger(m, a)
    assert b.calls == previous
    if failure in {"no_exit_proof", "identity", "app_epoch", "audit"}: assert not b.calls
    if failure in {"sql", "uncertain_start"}: assert b.calls == ["postgres"]


def test_new_plan_cannot_be_enabled_by_old_or_other_session_offer(tmp_path):
    m = healthy_monitor(); a = VikunjaAutomation(m, tmp_path)
    status = a.status("owner")
    for owner, offer, plan in [("owner",status["offer_id"],PLAN),
        ("other",status["dependency_offer_id"],PLAN), ("owner",status["dependency_offer_id"],"database_only")]:
        with pytest.raises(ValueError): a.enable(owner, offer, plan_id=plan)
    a.enable("owner", status["offer_id"])
    assert a.plan_id == "database_only"


def test_old_policy_does_not_recover_exited_application(tmp_path, monkeypatch):
    m, b, a, _ = fixture(tmp_path, monkeypatch)
    a.plan_id = "database_only"
    trigger(m, a)
    assert not b.calls and not a.actions


@pytest.mark.parametrize("bound", ["expired", "paused", "generation", "budget", "cooldown", "business_identity"])
def test_policy_bounds_apply_before_dependency_mutations(tmp_path, monkeypatch, bound):
    m, b, a, _ = fixture(tmp_path, monkeypatch)
    if bound == "expired": a.deadline = a.clock() - 1
    elif bound == "paused": m._watching = False
    elif bound == "generation": m._generation += 1
    elif bound == "budget": a.actions = 3
    elif bound == "business_identity": m.business.task_id += 1
    else: a.last_action = a.clock()
    trigger(m, a)
    assert not b.calls


def test_new_route_requires_new_plan_and_session_offer(web):
    client, control, _ = web
    h = headers(client)
    s = client.get(RECOVERY + "/status").json()["automation"]
    data = {"approved":True, "offer_id":s["dependency_offer_id"], "plan_id":PLAN}
    assert client.post(RECOVERY + "/enable-dependency", headers=h, json=data | {"offer_id":s["offer_id"]}).status_code == 409
    assert client.post(RECOVERY + "/enable-dependency", headers=h, json=data | {"plan_id":"other"}).status_code == 409
    assert client.post(RECOVERY + "/enable-dependency", headers=h, json=data | {"command":"anything"}).status_code == 422
    assert not control.recovery.automation.active
    assert client.post(RECOVERY + "/enable-dependency", headers=h, json=data).status_code == 200
    assert control.recovery.automation.plan_id == PLAN


def test_stopped_app_is_measured_failure_without_fake_http(tmp_path, monkeypatch):
    m, _, _, _ = fixture(tmp_path, monkeypatch)
    sample = m.observe("incident-test", "trace-test")
    assert sample["request"]["status_code"] is None
    assert sample["request"]["failure_kind"] == "container_stopped" and dependency_failure(sample)
    assert not sample["sampling_error"]


@pytest.mark.parametrize("event", ["stop", "kill", "restart", "start", "destroy", "oom", "missing_die"])
def test_docker_cascade_evidence_rejects_explicit_application_actions(event):
    from test_vikunja import IDENTITY
    backend = VikunjaDocker()
    from workbench.vikunja_target import Inspection
    backend.inspect = lambda: Inspection(IDENTITY, False, False, "exited", "2026-10-27T00:00:00Z")
    def run(args, **kwargs):
        if args[0] == "events": return "" if event == "missing_die" else "die\n" + event
        return json.dumps({"exit":1,"oom":False,"finished":
            "2026-10-28T00:00:25Z" if args[-1] == IDENTITY.app_id else "2026-10-28T00:00:00Z"})
    backend._run = run
    assert backend.dependency_exit(IDENTITY,"2026-10-27T00:00:00Z") is False


def test_dependency_gate_rejects_nonrecovery_and_replayed_consumption(tmp_path, monkeypatch):
    m, _, a, _ = fixture(tmp_path, monkeypatch)
    a.inflight = True
    run = DependencyRun(a, {"incident_id":"incident-test","trace_id":"trace-test"})
    with pytest.raises((AuthorizationError, ValueError)): run.gate.request("model", {})
    from test_vikunja import action
    run.binding = {"plan_id":PLAN,"policy_id":a.policy_id,"step":"postgres","scope":a.scope,
                   "monitor_generation":a.generation,"max_actions":1,"action":action(),
                   "business":{"project_id":m.business.project_id,"task_id":m.business.task_id,"app_started_at":a.app_started_at}}
    g = run.gate.request("recovery",run.binding)
    run.gate.consume(g,"recovery",run.binding,operation_id="dependency-test")
    with pytest.raises(AuthorizationError): run.gate.consume(g,"recovery",run.binding,operation_id="dependency-test")


@pytest.mark.parametrize("exit_code,oom,app_finished,pg_finished,events,valid", [
    (1,False,"2026-10-28T00:00:25Z","2026-10-28T00:00:00Z","die",True),
    (0,False,"2026-10-28T00:00:25Z","2026-10-28T00:00:00Z","die",False),
    (137,False,"2026-10-28T00:00:25Z","2026-10-28T00:00:00Z","die",False),
    (1,True,"2026-10-28T00:00:25Z","2026-10-28T00:00:00Z","die",False),
    (1,False,"2026-10-27T23:59:00Z","2026-10-28T00:00:00Z","die",False),
])
def test_exit_evidence_requires_non_oom_exit_one_after_database(exit_code,oom,app_finished,pg_finished,events,valid):
    from test_vikunja import IDENTITY
    from workbench.vikunja_target import Inspection
    b = VikunjaDocker()
    b.inspect = lambda: Inspection(IDENTITY,False,False,"exited","2026-10-27T00:00:00Z")
    def run(args, **kwargs):
        if args[0] == "events": return events
        return json.dumps({"exit":exit_code,"oom":oom,"finished":app_finished if args[-1]==IDENTITY.app_id else pg_finished})
    b._run = run
    assert bool(b.dependency_exit(IDENTITY,"2026-10-27T00:00:00Z")) is valid


@pytest.mark.parametrize("service,running,pg,sql,evidence,allowed", [
    ("postgres",True,False,False,None,True),
    ("postgres",True,True,True,None,False),
    ("app",True,True,True,{"database_finished_at":"time"},False),
    ("app",False,False,True,{"database_finished_at":"time"},False),
    ("app",False,True,False,{"database_finished_at":"time"},False),
    ("app",False,True,True,{"database_finished_at":"time"},True),
    ("web",False,True,True,None,False),
])
def test_docker_start_boundary_never_restarts_running_application(service,running,pg,sql,evidence,allowed):
    from test_vikunja import IDENTITY
    from workbench.vikunja_target import Inspection
    b=VikunjaDocker();calls=[]
    b.inspect=lambda: Inspection(IDENTITY,running,pg,"running" if pg else "exited","epoch")
    b.sql_probe=lambda identity: sql
    b.dependency_exit=lambda *args: evidence
    b._run=lambda args,**kwargs: calls.append(args)
    if allowed:
        b.start_dependency(IDENTITY,service,"epoch",evidence)
        assert calls==[["start",IDENTITY.postgres_id if service=="postgres" else IDENTITY.app_id]]
    else:
        with pytest.raises(TargetError): b.start_dependency(IDENTITY,service,"epoch",evidence)
        assert calls==[]


def test_sql_transient_failure_is_polled_and_never_starts_app_early(tmp_path,monkeypatch):
    m,b,a,_=fixture(tmp_path,monkeypatch)
    count=[0]
    def sql(identity):
        count[0]+=1
        if count[0]<3: raise TargetError("starting")
        return True
    b.sql_probe=sql
    trigger(m,a)
    assert b.calls==["postgres","app"] and a.events[-1]["event"]=="recovery_verified"


def test_expiration_after_audit_or_consumption_cannot_start_container(tmp_path,monkeypatch):
    m,b,a,_=fixture(tmp_path,monkeypatch)
    record=a.record
    def expire(event,**fields):
        record(event,**fields)
        if event=="dependency_action_reserved": a.deadline=a.clock()-1
    a.record=expire
    trigger(m,a)
    assert not b.calls and not a.active


def test_revocation_during_sql_wait_prevents_following_application_start(tmp_path,monkeypatch):
    m,b,a,_=fixture(tmp_path,monkeypatch)
    def revoke(identity):
        a.disable()
        return True
    b.sql_probe=revoke
    trigger(m,a)
    assert b.calls==["postgres"] and not a.active
    assert "recovery_verified" not in [e["event"] for e in a.events]
