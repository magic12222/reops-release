"""持久化边界故障注入：没有真实模型、Docker或进程终止。"""
import json
import os
import sqlite3
from unittest.mock import Mock, patch

import pytest

from reops_agent.memory import RecoveryMemory
from reops_agent.mocks import recovery_mock
from reops_agent.recovery import recover
from reops_agent.recovery_smoke import fault_recovery
from reops_agent.trace_journal import TraceJournal
from test_recovery_smoke import rig, run, provider


@pytest.mark.parametrize('step', ['model_authorization','rca','planner','safety','authorization','executor_started'])
def test_each_pre_execution_audit_failure_blocks_mutation(rig,step):
    original=rig[3].record
    def record(stage,current,*args):
        if current==step:raise OSError('offline-disk-failure')
        return original(stage,current,*args)
    rig[3].record=record
    model=provider();report=run(rig,model,execute_recovery=True)
    assert not report['executor_called'] and rig[1].restarts==[]
    rig[5].assert_not_called()
    assert report.get('error')
    assert model.complete.call_count==(0 if step=='model_authorization' else 1)


@pytest.mark.parametrize('step', ['executor_result','post_recovery_observation','verify','memory'])
def test_post_execution_audit_failure_never_replays_mutation(rig,step):
    original=rig[3].record
    def record(stage,current,*args):
        if current==step:raise OSError('offline-disk-failure')
        return original(stage,current,*args)
    rig[3].record=record
    model=provider();report=run(rig,model,execute_recovery=True)
    assert rig[1].restarts==['web'] and rig[5].call_count==1
    assert report.get('error')
    if step in ('executor_result','post_recovery_observation'):
        assert not report['recovery_verified']
    # Same operation/trace remains consumed even if a new grant is requested.
    again=run(rig,model,execute_recovery=True)
    assert not again['executor_called']
    assert rig[1].restarts==['web'] and model.complete.call_count==1


def test_consumed_recovery_is_not_reusable_after_pre_action_audit_failure(rig):
    original=rig[3].record
    def record(stage,step,*args):
        if step=='executor_started':raise OSError('offline-disk-failure')
        return original(stage,step,*args)
    rig[3].record=record
    report=run(rig,execute_recovery=True)
    assert report['recovery_authorized'] and not report['executor_called']
    with sqlite3.connect(rig[2].ledger) as db:
        operations=[row[0].split(':')[0] for row in db.execute('SELECT operation_id FROM reservations')]
    assert sorted(operations)==['model','recovery']
    assert rig[1].restarts==[]


def test_memory_sync_failure_is_not_acknowledged_as_delivery(rig):
    # Replace only memory's os binding; journal's real sync continues normally.
    sync=Mock(wraps=os);sync.fsync=Mock(side_effect=OSError('offline-sync-failure'))
    with patch('reops_agent.memory.os',sync):
        report=run(rig,execute_recovery=True)
    assert report['recovery_verified'] and not report['memory_written']
    assert report['error']=='memory_or_final_audit_write_failed'
    assert rig[1].restarts==['web']
    # A failed sync can leave an appended row. Do not claim rollback or erase it.
    assert rig[4].path.exists()


def test_memory_success_returns_only_after_sync(tmp_path):
    memory=RecoveryMemory(tmp_path/'memory.jsonl');pre,succeeds=recovery_mock('postgres_restart_success')
    sync=Mock(wraps=os)
    with patch('reops_agent.memory.os',sync):
        report=recover(pre,execution_succeeds=succeeds,memory=memory)
    assert report['memory_written'] and sync.fsync.call_count==1
    assert json.loads(memory.path.read_text(encoding='utf-8'))['event_id']==report['agent_event']['event_id']


def test_journal_sync_failure_does_not_advance_in_memory_parent_chain(tmp_path):
    journal=TraceJournal({'incident_id':'incident-test','trace_id':'trace-test'},tmp_path/'audit.jsonl')
    with patch('reops_agent.trace_journal.os.fsync',side_effect=OSError('offline-sync-failure')):
        with pytest.raises(OSError):journal.record('observe','before','started',{})
    assert journal.events==[]


def test_experiment_audit_failure_before_injection_never_calls_cleanup(rig):
    rig[1].healthy=True
    original=rig[3].record
    def record(stage,step,*args):
        if step=='fixture_fault_injection':raise OSError('offline-disk-failure')
        return original(stage,step,*args)
    rig[3].record=record
    model=provider()
    report=fault_recovery(rig[1],model,gate=rig[2],journal=rig[3],memory=rig[4],
        model_identifier='offline-test',execute_recovery=True,executor_factory=rig[5],verify_timeout=0,poll_interval=0)
    assert not report['fault_injection_attempted'] and report['cleanup_outcome']=='not_run'
    assert rig[1].injections==0 and rig[1].restarts==[]
    model.complete.assert_not_called()


def test_memory_sync_failure_keeps_cleanup_separate_and_acceptance_false(rig):
    rig[1].healthy=True
    sync=Mock(wraps=os);sync.fsync=Mock(side_effect=OSError('offline-sync-failure'))
    with patch('reops_agent.memory.os',sync):
        report=fault_recovery(rig[1],provider(),gate=rig[2],journal=rig[3],memory=rig[4],
            model_identifier='offline-test',execute_recovery=True,executor_factory=rig[5],verify_timeout=0,poll_interval=0)
    assert report['recovery_verified'] and report['cleanup_outcome']=='succeeded'
    assert not report['memory_written'] and not report['acceptance_passed']
    assert rig[1].restarts==['web']  # 健康cleanup没有额外restart。


def test_injection_timeout_after_state_change_runs_only_independent_cleanup(rig):
    rig[1].healthy=True
    original=rig[1].inject_web_failure_test_only
    def uncertain(**kwargs):
        original(**kwargs)
        raise TimeoutError('offline-unknown-stop-result')
    rig[1].inject_web_failure_test_only=uncertain
    model=provider()
    report=fault_recovery(rig[1],model,gate=rig[2],journal=rig[3],memory=rig[4],
        model_identifier='offline-test',execute_recovery=True,executor_factory=rig[5],verify_timeout=0,poll_interval=0)
    assert report['fault_injection_attempted'] and report['cleanup_outcome']=='succeeded'
    assert report['final_observation']['request']['status_code']==200
    assert not report['recovery_executed'] and not report['recovery_verified'] and not report['acceptance_passed']
    assert rig[1].injections==1 and rig[1].restarts==['web']
    model.complete.assert_not_called();rig[5].assert_not_called()
