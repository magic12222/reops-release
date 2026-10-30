import sharedEvents from '../../../shared/examples/agent_events.example.json';
import observation from '../../../shared/examples/observation.example.json';
import diagnosis from '../../../shared/examples/diagnosis.example.json';
import action from '../../../shared/examples/recovery_action.example.json';
import result from '../../../shared/examples/recovery_result.example.json';
import type { EventRecord, RunRecord } from '../types/dashboard';

// Read-only illustrations. These records never describe a live execution.
const source = 'offline_fixture' as const;
const success: RunRecord = {
  id: 'fixture-postgres-recovered', incident_id: 'incident-001', trace_id: 'trace-001',
  case_id: 'case-postgres-down-001', fault_id: null, source, status: 'recovered',
  started_at: sharedEvents[0].timestamp, finished_at: sharedEvents.at(-1)!.timestamp,
  model_calls: null, action_count: 1, recovery_latency_ms: null, success: true,
  metadata: { fixture_kind: 'shared_contract_mock', simulated: true,
    basis: 'shared/examples/{agent_events,observation,diagnosis,recovery_action,recovery_result}.example.json' },
};
const payloads: Partial<Record<EventRecord['stage'], Record<string, unknown>>> = {
  observe: observation, failure_detection: { failure_detected: diagnosis.failure_detected, evidence: diagnosis.evidence },
  localization: { failed_component: diagnosis.failed_component, failed_step: diagnosis.failed_step },
  root_cause_analysis: diagnosis, recovery_decision: action,
  recovery_execution: { action: action.action, target: action.target, execution_status: result.execution_status,
    exit_code: result.exit_code, stdout: result.stdout, stderr: result.stderr, duration_ms: result.duration_ms },
  verification: result.verification,
};
const successEvents: EventRecord[] = sharedEvents.map((event, ordinal) => ({
  event_id: `fixture-${event.event_id}`, run_id: success.id, incident_id: event.incident_id, trace_id: event.trace_id,
  case_id: event.case_id, ordinal, parent_event_id: event.parent_event_id ? `fixture-${event.parent_event_id}` : null,
  stage: event.stage as EventRecord['stage'], status: event.status as EventRecord['status'],
  timestamp: event.timestamp, message: event.message, source, origin: 'trace_journal',
  original_event_id: event.event_id, data: { ...event.data, ...payloads[event.stage as EventRecord['stage']] },
}));

const failed: RunRecord = {
  id: 'fixture-web-not-recovered', incident_id: 'fixture-incident-failed', trace_id: 'fixture-trace-failed',
  case_id: 'case-web-verification-failed', fault_id: null, source, status: 'failed',
  started_at: '2026-10-02T09:12:00+08:00', finished_at: '2026-10-02T09:12:12+08:00',
  model_calls: null, action_count: 1, recovery_latency_ms: null, success: false,
  metadata: { fixture_kind: 'frontend_illustration', simulated: true,
    basis: 'benchmarks/offline/scenarios.json: still_unhealthy',
    note: 'Illustrative history, not an output of the benchmark or a live service.' },
};
const partial: RunRecord = {
  id: 'fixture-partial-diagnosis', incident_id: 'fixture-incident-partial', trace_id: 'fixture-trace-partial',
  case_id: 'case-incomplete-diagnosis', fault_id: null, source, status: 'diagnosing',
  started_at: '2026-10-03T14:05:00+08:00', finished_at: null,
  model_calls: null, action_count: null, recovery_latency_ms: null, success: null,
  metadata: { fixture_kind: 'frontend_illustration', simulated: true,
    note: 'Partial illustrative snapshot; missing records and results must not be inferred.' },
};
function event(run: RunRecord, ordinal: number, stage: EventRecord['stage'], status: EventRecord['status'],
  timestamp: string | null, message: string, data: Record<string, unknown>, parent: number | null): EventRecord {
  return { event_id: `${run.id}-event-${ordinal}`, run_id: run.id, incident_id: run.incident_id,
    trace_id: run.trace_id, case_id: run.case_id, ordinal, parent_event_id: parent === null ? null : `${run.id}-event-${parent}`,
    stage, status, timestamp, message, source, origin: 'trace_journal', original_event_id: null, data };
}
const failedEvents = [
  event(failed, 0, 'observe', 'success', failed.started_at,
    '模拟观测：业务请求返回 HTTP 503。', { request: { endpoint: '/users', status_code: 503 }, service: 'web' }, null),
  event(failed, 1, 'failure_detection', 'success', '2026-10-02T09:12:01+08:00',
    '模拟检测：Web 服务健康检查持续失败。', { failure_detected: true, evidence: ['GET /users: HTTP 503', 'web health: unhealthy'] }, 0),
  event(failed, 2, 'recovery_decision', 'success', '2026-10-02T09:12:03+08:00',
    '模拟决策：选择白名单中的服务重启。', { action: 'restart_service', target: 'web',
      reason: '样例中 Web 健康检查失败，选择受限重启；执行结果仍需独立验证。' }, 1),
  event(failed, 3, 'recovery_execution', 'success', '2026-10-02T09:12:08+08:00',
    '模拟工具记录：重启返回成功，尚未确认业务恢复。', { action: 'restart_service', target: 'web',
      execution_status: 'succeeded', exit_code: 0,
      stdout: ['[OFFLINE FIXTURE] Historical tool output; no command was executed.',
        'restart requested for allowlisted target: web', 'executor result: succeeded',
        'health probe 1: HTTP 503', 'health probe 2: HTTP 503',
        'business probe: GET /users returned HTTP 503',
        'Do not equate successful restart with successful recovery.'].join('\n'), stderr: '' }, 2),
  event(failed, 4, 'verification', 'failed', failed.finished_at,
    '模拟验证失败：重启后业务请求仍为 HTTP 503。', { status: 'not_recovered', health_check_passed: false,
      business_request_passed: false, fault_cleared: false,
      evidence: ['web health remains unhealthy', 'GET /users returned HTTP 503 after restart'] }, 3),
];
const partialEvents = [
  event(partial, 0, 'observe', 'success', partial.started_at,
    '模拟部分记录：请求延迟升高，尚未形成恢复结论。', { request: { endpoint: '/users', latency_ms: 1800 }, logs: [] }, null),
  event(partial, 2, 'localization', null, null,
    '模拟部分记录：此事件未提供独立时间、状态或结构化证据。', {}, 0),
  event(partial, 5, 'root_cause_analysis', 'started', '2026-10-03T14:05:05+08:00',
    '模拟诊断尚未完成；缺失事件不补齐。', { root_cause: null, confidence: null, evidence: [] }, 2),
];

export const agentFixtures = [
  { run: success, events: successEvents }, { run: failed, events: failedEvents }, { run: partial, events: partialEvents },
];
