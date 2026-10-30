import { describe, expect, it } from 'vitest';
import { evidenceFields, evidencePreview, eventStatus, stageSummary, runName, preferredRunId, shortIdentifier, traceName } from './traceExplorer';
import type { EventRecord, RunRecord } from '../types/dashboard';

const event: EventRecord = { event_id: 'offline-step', run_id: 'offline-run', incident_id: 'offline-incident', trace_id: 'offline-trace',
  case_id: null, ordinal: 0, parent_event_id: null, stage: 'recovery_execution', status: null, timestamp: null,
  message: 'Execution', source: 'offline_fixture', origin: 'decision_trace', original_event_id: 'original',
  data: { step: 'Execution', value: { execution_status: 'failed', executor_called: false } } };

describe('evidence display boundaries', () => {
  it('opens the recovery trace ahead of later cleanup without hiding or upgrading cleanup', () => {
    const cleanup = { id: 'cleanup', trace_id: 'trace-cleanup-one', status: 'unknown', case_id: null, fault_id: null } as RunRecord;
    const recovery = { ...cleanup, id: 'recovery', trace_id: 'trace-c4-one', status: 'recovered' } as RunRecord;
    const runs = [cleanup, recovery];
    expect(preferredRunId(runs)).toBe('recovery');
    expect(runName(cleanup)).toBe('环境善后（独立轨迹）');
    expect(runName(recovery)).toBe('C4 受控恢复轨迹');
    expect(runName({ ...cleanup, case_id: 'case-original_name' })).toBe('original name');
    expect(preferredRunId([cleanup])).toBe('cleanup');
    expect(preferredRunId([])).toBeNull();
    expect(runs).toEqual([cleanup, recovery]);
    expect(cleanup.status).toBe('unknown');
  });
  it('unwraps only recorded decision trace evidence without deriving status', () => {
    expect(evidenceFields(event)).toEqual([['execution_status', 'failed'], ['executor_called', false]]);
    expect(eventStatus(event.status)).toBe('状态未提供');
    expect(eventStatus('success')).toBe('事件成功');
    expect(event.data.value).toEqual({ execution_status: 'failed', executor_called: false });
  });
  it('preserves null, false, empty values and unknown fields', () => {
    expect(evidenceFields({ ...event, origin: 'trace_journal', data: { custom: null, executed: false, error: '', value: {} } }))
      .toEqual([['custom', null], ['executed', false], ['error', ''], ['value', {}]]);
    expect(evidencePreview(false)).toBe('false');
    expect(evidencePreview(null)).toBe('null');
    expect(evidenceFields({ ...event, data: {} })).toEqual([]);
  });
  it('uses supplied case/fault names and never invents a missing scenario', () => {
    const identifiers = { case_id: 'case-postgres_restart_success', fault_id: 'fault-api_stopped' } as RunRecord;
    expect(runName(identifiers)).toBe('postgres restart success');
    expect(runName({ ...identifiers, case_id: null })).toBe('api stopped');
    expect(runName({ ...identifiers, case_id: null, fault_id: null })).toBe('未命名运行');
    expect(runName({ ...identifiers, case_id: 'case-' })).toBe('case-');
    expect(shortIdentifier('run-32c030e7d5f760015c958ef5')).toBe('run-32c0…958ef5');
    expect(shortIdentifier('run-1')).toBe('run-1');
  });
  it('distinguishes recorded substeps without adding events or interpreting results', () => {
    expect(traceName({ ...event, stage: 'recovery_decision', message: 'Safety decision' })).toBe('Safety');
    expect(traceName({ ...event, stage: 'recovery_decision', message: 'Action' })).toBe('Decide');
    expect(traceName({ ...event, stage: 'recovery_decision', message: 'Unknown message' })).toBe('Decide');
    expect(traceName({ ...event, message: 'constructor' })).toBe('Execute');
    expect(traceName({ ...event, origin: 'trace_journal', message: 'Safety decision' })).toBe('Execute');
    expect(event.status).toBeNull();
  });
  it('uses only a recorded sentence and does not turn nested execution data into a conclusion', () => {
    expect(stageSummary(event)).toBe('');
    expect(stageSummary({ ...event, data: { value: { reason: 'Recorded safety rejection', executor_called: false } } }))
      .toBe('Recorded safety rejection');
    expect(stageSummary({ ...event, data: { value: { summary: '', reason: null, root_cause: 'postgres_service_down' } } }))
      .toBe('postgres_service_down');
    expect(stageSummary({ ...event, data: { value: { summary: { invented: true }, status: 'recovered' } } }))
      .toBe('');
    expect(stageSummary({ ...event, message: 'Recorded custom tool failure' })).toBe('Recorded custom tool failure');
    expect(stageSummary({ ...event, message: '', data: {} })).toBe('');
  });
});
