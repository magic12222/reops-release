import { t } from '../i18n';
import type { EventRecord, RunRecord } from '../types/dashboard';

export function shortIdentifier(value: string) {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

/** Only prettifies supplied identifiers; never infers a diagnosis or a result. */
export function runName(run: RunRecord): string {
  const name = run.case_id || run.fault_id;
  if (name) return name.replace(/^(case|fault)[-_]/, '').replaceAll('_', ' ') || name;
  if (run.trace_id?.startsWith('trace-cleanup-')) return t("环境善后（独立轨迹）");
  if (run.trace_id?.startsWith('trace-c4-')) return t("C4 受控恢复轨迹");
  if (run.trace_id?.startsWith('trace-researchloop-')) return t("ResearchLoop 数据库恢复轨迹");
  return t("未命名运行");
}

/** Keep cleanup available, but prefer the recovery trace when opening the list. */
export function preferredRunId(runs: readonly RunRecord[]): string | null {
  return (runs.find(run => !run.trace_id.startsWith('trace-cleanup-')) ?? runs[0])?.id ?? null;
}

const shortStages: Record<EventRecord['stage'], string> = {
  observe: 'Observe', failure_detection: 'Detect', localization: 'Locate', root_cause_analysis: 'Reason',
  recovery_decision: 'Decide', recovery_execution: 'Execute', verification: 'Verify', experience_update: 'Learn',
};
const recordedSteps: Record<string, string> = {
  Observation: 'Observe', 'Failure detected': 'Detect', Diagnosis: 'Locate', 'RCA evidence': 'Reason',
  'Memory evidence': 'Memory', 'Nexent recommendation': 'Recommend', 'Safety decision': 'Safety',
  Action: 'Decide', Execution: 'Execute', Verification: 'Verify', 'Final status': 'Outcome',
};
export function traceName(event: EventRecord) {
  return event.origin === 'decision_trace' && Object.prototype.hasOwnProperty.call(recordedSteps, event.message)
    ? recordedSteps[event.message] : shortStages[event.stage];
}

/** Use a recorded sentence only. No conclusions from stage, status, or playback. */
export function stageSummary(event: EventRecord): string {
  const fields = new Map(evidenceFields(event));
  for (const key of ['summary', 'reason', 'root_cause', 'message']) {
    const value = fields.get(key);
    if (typeof value === 'string' && value.trim()) return value;
  }
  // Technical step names carry no sentence-level evidence; the inspector keeps them intact.
  return event.message === event.stage || Object.prototype.hasOwnProperty.call(recordedSteps, event.message)
    || /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/.test(event.message) ? '' : event.message;
}

export const eventStatusLabels: Record<NonNullable<EventRecord['status']>, string> = {
  started: "已开始", success: "事件成功", failed: "事件失败", skipped: "已跳过", waiting_human: "等待人工",
};

export function eventStatus(status: EventRecord['status']) {
  return t(status === null ? '状态未提供' : eventStatusLabels[status]);
}

/** A display preview, never a diagnosis or inferred execution result. */
export function evidencePreview(value: unknown): string {
  if (value === null) return 'null';
  if (Array.isArray(value)) return t('{0} 项 · {1}', value.length, JSON.stringify(value).slice(0, 180));
  if (typeof value === 'object') return Object.entries(value as Record<string, unknown>)
    .slice(0, 4).map(([key, item]) => `${key}: ${typeof item === 'object' && item !== null
      ? Array.isArray(item) ? t('[{0} 项]', item.length) : '{…}' : String(item)}`).join(' · ') || '{}';
  return String(value);
}

/** decision_trace's value contains the original step evidence; no new fields are invented. */
export function evidenceFields(event: EventRecord): [string, unknown][] {
  const value = event.data.value;
  if (event.origin === 'decision_trace' && typeof value === 'object' && value !== null && !Array.isArray(value)) {
    return Object.entries(value);
  }
  return Object.entries(event.data);
}

export const EVENT_PLAYBACK_MS = 1400;
