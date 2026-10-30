/** ResearchLoop独立只读台账；缺失usage不填0，未调用模型需有完整零调用证据。 */
export type JsonObject = Record<string, unknown>;
export interface DatabaseExperiment {
  id: string; scenario: 'researchloop_stopped_postgres'; source: 'real';
  incident_id: string; trace_id: string;
  state: 'waiting_authorization' | 'finished'; result: 'passed' | 'failed' | 'rejected' | 'unknown';
  review_required: boolean; created_at: string; report?: JsonObject;
}
export const object = (value: unknown): value is JsonObject => typeof value === 'object' && value !== null && !Array.isArray(value);
const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0;

export async function readDatabaseExperiments(signal?: AbortSignal): Promise<DatabaseExperiment[]> {
  const response = await fetch('/api/v1/researchloop/experiments', {
    cache: 'no-store', credentials: 'omit', redirect: 'error', mode: 'same-origin', signal,
  });
  if (!response.ok) throw new Error('database_ledger_unavailable');
  const value: unknown = await response.json();
  if (!object(value) || value.scenario !== 'researchloop_stopped_postgres'
      || !['operator_terminal_only', 'operator_terminal_or_browser_confirmation'].includes(String(value.execution)) || !Array.isArray(value.experiments)
      || !value.experiments.every(item => object(item) && text(item.id) && text(item.incident_id)
        && text(item.trace_id) && text(item.created_at) && item.source === 'real'
        && item.scenario === value.scenario && ['waiting_authorization', 'finished'].includes(String(item.state))
        && ['passed', 'failed', 'rejected', 'unknown'].includes(String(item.result))
        && typeof item.review_required === 'boolean' && (item.report === undefined || object(item.report)))) {
    throw new Error('database_ledger_invalid');
  }
  return value.experiments as DatabaseExperiment[];
}

export function repairUsage(report?: JsonObject): { input: number; output: number; total: number; source: string } | null {
  if (!report || !object(report.repair_usage) || !object(report.measurements)) return null;
  const usage = report.repair_usage;
  if (!count(usage.input_tokens) || !count(usage.output_tokens)
      || !Number.isSafeInteger(usage.input_tokens + usage.output_tokens)) return null;
  if (usage.source === 'no_model_calls') {
    if (report.diagnosis_source !== 'memory/rule-supported' || report.model_calls !== 0
        || report.measurements.provider_attempts !== 0 || !Array.isArray(report.measurements.requests)
        || report.measurements.requests.length !== 0 || usage.input_tokens !== 0 || usage.output_tokens !== 0) return null;
  } else if (usage.source === 'server_usage') {
    const raw = report.measurements.usage;
    if (!count(report.model_calls) || report.model_calls === 0 || !object(raw) || raw.source !== 'server_usage'
        || raw.input_tokens !== usage.input_tokens || raw.output_tokens !== usage.output_tokens) return null;
  } else return null;
  return { input: usage.input_tokens, output: usage.output_tokens,
    total: usage.input_tokens + usage.output_tokens, source: usage.source };
}

export function freshBusinessVerifications(report?: JsonObject): number {
  if (!report || !Array.isArray(report.verify_observations)) return 0;
  const samples = report.verify_observations;
  if (report.recovery_verified !== true || samples.length !== 2 || !samples.every(sample =>
    object(sample) && sample.incident_id === report.incident_id && sample.trace_id === report.trace_id
    && text(sample.observation_id) && object(sample.business) && sample.business.read_valid === true
    && sample.business.database_sql_valid === true && sample.business.probe_read_valid === true)
    || samples[0].observation_id === samples[1].observation_id || samples[0].business.write_valid !== true) return 0;
  return 2;
}

export function recoveryLatency(report?: JsonObject): number | null {
  if (!report || freshBusinessVerifications(report) !== 2 || !object(report.measurements)) return null;
  const value = report.measurements.recovery_latency_ms;
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value / 1000 : null;
}

export function memoryHits(report?: JsonObject): string[] {
  return report && Array.isArray(report.memory_hit_event_ids) && report.memory_hit_event_ids.every(text)
    ? report.memory_hit_event_ids : [];
}
