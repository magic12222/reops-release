import { describe, expect, it } from 'vitest';
import { evidenceFactText, evidencePresentation, stageFact } from './evidencePresentation';
import { agentFixtures } from './agentFixtures';
import type { EventRecord } from '../types/dashboard';

describe('compact evidence from recorded fields', () => {
  it('condenses actual Detect evidence while keeping additional support and complete raw data', () => {
    const event = agentFixtures[0].events[1];
    const original = structuredClone(event);
    expect(stageFact(event)?.text).toBe('HTTP 500 · connection refused: postgres:5432');
    const view = evidencePresentation(event);
    expect(view.summary).toBe('检测到故障');
    expect(view.facts).toEqual([{ key: 'evidence', label: '检测依据', value: ['postgres service health is unhealthy'] }]);
    expect(event).toEqual(original);
    const wrapped = { ...event, origin: 'decision_trace' as const, data: { value: event.data } };
    expect(stageFact(wrapped)).toEqual(stageFact(event));
    expect(evidencePresentation(wrapped)).toEqual(view);
  });

  it('preserves negation, absent signals and the recorded detection result', () => {
    const event = { ...agentFixtures[0].events[1], data: { failure_detected: false,
      evidence: ['API log contains no connection refused signal.', 'HTTP 500 not observed'] } };
    expect(stageFact(event)?.text).toBe('no connection refused signal. · HTTP 500 not observed');
    expect(evidencePresentation(event).summary).toBe('未检测到故障');
    expect(evidencePresentation(event).facts).toEqual([]);
    expect(stageFact({ ...event, data: { failure_detected: true, evidence: [null, {}, ''] } })).toBeUndefined();
    expect(stageFact({ ...event, data: {} })).toBeUndefined();
    expect(stageFact({ ...event, data: { evidence: ['{"status":"failed"}'], summary: '{"status":"failed"}' } })).toBeUndefined();
  });

  it('renders recorded booleans as outcomes without changing the underlying values', () => {
    expect(evidenceFactText({ key: 'health_check_passed', label: '健康检查', value: false })).toBe('未通过');
    expect(evidenceFactText({ key: 'business_request_passed', label: '业务验证', value: true })).toBe('通过');
    expect(evidenceFactText({ key: 'requires_approval', label: '需要审批', value: false })).toBe('否');
    expect(evidenceFactText({ key: 'exit_code', label: '退出码', value: 0 })).toBe('0');
    const verify = evidencePresentation(agentFixtures[1].events[4]);
    expect(verify.facts.find(fact => fact.key === 'health_check_passed')?.value).toBe(false);
  });

  it('covers recorded summaries and outcomes without manufacturing missing stage evidence', () => {
    const event = { ...agentFixtures[2].events[1], stage: 'experience_update' as const, data: { final_status: 'inconclusive' } };
    expect(stageFact(event)?.text).toBe('证据不足');
    expect(stageFact({ ...event, data: { summary: 'A recorded memory update.' } })?.text).toBe('A recorded memory update.');
    expect(stageFact({ ...event, data: { summary: 'Verification' } })).toBeUndefined();
    expect(stageFact({ ...event, data: { summary: 'Learn' } })).toBeUndefined();
    expect(stageFact({ ...event, data: { summary: 'Long evidence. '.repeat(40) } })).toBeUndefined();
  });

  it('gives the stage one recorded fact and reserves result details for evidence', () => {
    const execute = agentFixtures[0].events[5];
    expect(stageFact(execute)).toEqual({ text: 'restart_service → postgres', keys: ['action', 'target'] });
    expect(stageFact(agentFixtures[0].events[6])?.text).toBe('已验证恢复');
    expect(stageFact(agentFixtures[1].events[4])?.text).toBe('未恢复');
    expect(stageFact(agentFixtures[2].events[1])).toBeUndefined();
    expect(stageFact(agentFixtures[2].events[2])).toBeUndefined();
    const partial = { ...execute, data: { action: 'restart_service', target: null, exit_code: 0 } };
    expect(stageFact(partial)).toBeUndefined();
    expect(evidencePresentation(partial).facts.map(fact => fact.key)).toContain('action');
    const wrapped = { ...execute, origin: 'decision_trace' as const, data: { value: execute.data } };
    expect(stageFact(wrapped)).toEqual(stageFact(execute));
    for (const fixture of agentFixtures) for (const event of fixture.events) {
      expect(evidencePresentation(event).facts.some(fact => stageFact(event)?.keys.includes(fact.key))).toBe(false);
    }
  });

  it('selects different evidence for observation, diagnosis, execution and verification', () => {
    const events = agentFixtures[0].events;
    expect(evidencePresentation(events[0]).facts.map(fact => fact.key)).toEqual([
      'request.latency_ms', 'services', 'metrics',
    ]);
    const reason = evidencePresentation(events[3]);
    expect(reason.summary).toBe('');
    expect(reason.facts.map(fact => fact.key)).not.toContain('root_cause'); // already in the recorded sentence
    expect(reason.facts.map(fact => fact.key)).toContain('confidence');
    expect(evidencePresentation(events[5]).facts.map(fact => fact.key)).toEqual([
      'execution_status', 'exit_code', 'duration_ms',
    ]);
    expect(evidencePresentation(events[6]).facts.map(fact => fact.key)).toEqual([
      'evidence', 'health_check_passed', 'business_request_passed',
    ]);
    for (const fixture of agentFixtures) for (const event of fixture.events) {
      expect(evidencePresentation(event).facts.length).toBeLessThanOrEqual(3);
    }
  });

  it('retains false and zero without equating tool success with successful recovery', () => {
    const events = agentFixtures[1].events;
    const execution = evidencePresentation(events[3]);
    expect(execution.facts.find(fact => fact.key === 'exit_code')?.value).toBe(0);
    expect(execution.status).toBeNull();
    const verify = evidencePresentation(events[4]);
    expect(verify.status).toBe('failed');
    expect(verify.facts.filter(fact => fact.value === false)).toHaveLength(3);
    expect(verify.summary).toBe(events[4].message);
  });

  it('does not invent missing evidence, time, state or a conclusion from the stage', () => {
    const missing = agentFixtures[2].events[1];
    expect(evidencePresentation(missing)).toEqual({ summary: missing.message, facts: [], status: null });
    const technical: EventRecord = { ...missing, message: 'Verification', origin: 'decision_trace',
      data: { value: { status: null, confidence: null, evidence: [] } } };
    expect(evidencePresentation(technical)).toEqual({ summary: '', facts: [], status: null });
  });

  it('keeps an isolated failed verification check visible among otherwise passing checks', () => {
    const event = { ...agentFixtures[0].events[6], status: null, data: { verification_status: 'not_recovered',
      health_check_passed: true, business_request_passed: true, fault_cleared: false, evidence: ['A recorded check remains negative.'] } };
    const view = evidencePresentation(event);
    expect(view.facts[0]).toMatchObject({ key: 'fault_cleared', value: false });
    expect(view.facts.length).toBeLessThanOrEqual(3);
    expect(evidenceFactText(view.facts[0])).toBe('未清除');
    expect(stageFact(event)?.text).toBe('未恢复');
  });

  it('deduplicates repeated text and keeps unknown fields available without changing raw data', () => {
    const event: EventRecord = { ...agentFixtures[0].events[3], message: 'RCA evidence', origin: 'decision_trace',
      data: { value: { summary: 'Recorded diagnostic sentence.', component: 'web', affected_component: 'web',
        custom_signal: 'probe disagrees', constructor: 'own recorded field',
        observation_id: 'raw-observation', stdout: 'long log\n'.repeat(50) } } };
    const original = structuredClone(event);
    const view = evidencePresentation(event);
    expect(stageFact(event)?.text).toBe('Recorded diagnostic sentence.');
    expect(view.summary).toBe('');
    expect(view.facts.map(fact => fact.key)).toEqual(['component', 'custom_signal', 'constructor']);
    expect(view.facts.at(-1)?.label).toBe('constructor');
    expect(event).toEqual(original);
  });

  it('maps only exact known diagnoses and preserves the raw record and independent support', () => {
    const event = agentFixtures[0].events[3], original = structuredClone(event);
    expect(stageFact(event)?.text).toBe('PostgreSQL 服务不可用');
    const view = evidencePresentation(event);
    expect(view.summary).toBe('');
    expect(view.facts.map(fact => fact.key)).toEqual(['evidence', 'failed_component', 'confidence']);
    expect(view.facts.map(evidenceFactText)).toEqual([
      'GET /users returned HTTP 500；API log contains connection refused: postgres:5432 · 共 3 条', 'PostgreSQL', '94%',
    ]);
    expect(event).toEqual(original);
    const unfamiliar = { ...event, data: { root_cause: 'possibly_postgres_service_down' } };
    expect(stageFact(unfamiliar)?.text).toBe('possibly_postgres_service_down');
    // A mismatched or extended message must not be suppressed as a restatement.
    expect(evidencePresentation(unfamiliar).summary).toBe(event.message);
    const important = { ...event, message: `${event.message} Recovery attempt failed.` };
    expect(evidencePresentation(important).summary).toBe(important.message);
  });

  it('keeps contradictory and unsuccessful results visible and never infers verification from execution', () => {
    const execute = agentFixtures[1].events[3];
    expect(evidencePresentation(execute).summary).toBe(execute.message);
    expect(evidenceFactText(evidencePresentation(execute).facts[0])).toBe('执行成功');
    const contradictory = { ...agentFixtures[0].events[6], data: { status: 'not_recovered', health_check_passed: false } };
    expect(evidencePresentation(contradictory).summary).toBe(contradictory.message);
    expect(evidencePresentation(contradictory).facts[0]).toMatchObject({ key: 'health_check_passed', value: false });
  });
});
