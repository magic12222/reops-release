import type { AgentEvent, TraceStep } from '../types/agent';
import type { EventRecord, Provenance, RunRecord } from '../types/dashboard';
import type { SystemPhase } from '../types/system';
import { getLocale } from '../i18n';

const phaseMap: Record<AgentEvent['stage'], SystemPhase> = {
  observe: 'failed', failure_detection: 'detect', localization: 'locate', root_cause_analysis: 'reason',
  recovery_decision: 'decide', recovery_execution: 'execute', verification: 'verify', experience_update: 'learn',
};

/** Central adapter for future shared AgentEvent streams. Completion is NOT inferred from a timer. */
export function eventToTrace(event: AgentEvent, startedAt: string): TraceStep {
  const value = (key: string) => typeof event.data[key] === 'string' ? event.data[key] as string : '未提供';
  return { event, at: Math.max(0, Date.parse(event.timestamp) - Date.parse(startedAt)),
    phase: phaseMap[event.stage], title: event.stage.replaceAll('_', ' '), subtitle: event.message,
    input: value('input'), reason: value('reason'), tool: value('tool'), result: value('result') };
}

const stageLabels: Record<EventRecord['stage'], string> = {
  observe: 'Observation', failure_detection: 'Failure detection', localization: 'Localization',
  root_cause_analysis: 'Root cause analysis', recovery_decision: 'Recovery decision',
  recovery_execution: 'Recovery execution', verification: 'Verification', experience_update: 'Experience update',
};

export const provenanceLabels: Record<Provenance, string> = {
  real: 'REAL · 实际证据', offline_fixture: 'OFFLINE FIXTURE · 离线样例', simulation: 'SIMULATION · 模拟数据',
};

export const runStatusLabels: Record<RunRecord['status'], string> = {
  unknown: '未知', pending: '待开始', observing: '观测中', diagnosing: '诊断中',
  waiting_authorization: '等待人工授权', executing: '执行中', verifying: '核验中',
  recovered: '已验证恢复', failed: '恢复失败', inconclusive: '证据不足',
};

export function formatEvidenceTime(value: string | null): string {
  if (!value) return '无独立时间戳';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间不可解析' : date.toLocaleString(getLocale(), { hour12: false });
}

export interface ReadTraceStep { event: EventRecord; title: string; time: string }

/** C read events are not shared AgentEvents: synthetic steps may lack status/time. */
export function toReadTrace(run: RunRecord, events: EventRecord[]): ReadTraceStep[] {
  if (events.some(event => event.run_id !== run.id || event.incident_id !== run.incident_id
      || event.trace_id !== run.trace_id || event.source !== run.source)) {
    throw new Error('trajectory_correlation_mismatch');
  }
  const sorted = [...events].sort((a, b) => a.ordinal - b.ordinal);
  if (new Set(sorted.map(event => event.ordinal)).size !== sorted.length
      || new Set(sorted.map(event => event.event_id)).size !== sorted.length) {
    throw new Error('trajectory_order_conflict');
  }
  return sorted.map(event => ({ event, title: stageLabels[event.stage], time: formatEvidenceTime(event.timestamp) }));
}
