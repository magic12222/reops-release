/** Same-origin, read-only C API client. No A control URL or credentials enter the browser. */
import type { EventPage, EventRecord, Provenance, RunPage, RunRecord, SystemStatus } from '../types/dashboard';

type Fetcher = typeof fetch;
type ObjectValue = Record<string, unknown>;
const API = '/api/v1';
const sources = ['real', 'offline_fixture', 'simulation'];
const runStatuses = ['unknown', 'pending', 'observing', 'diagnosing', 'waiting_authorization', 'executing', 'verifying', 'recovered', 'failed', 'inconclusive'];
const stages = ['observe', 'failure_detection', 'localization', 'root_cause_analysis', 'recovery_decision', 'recovery_execution', 'verification', 'experience_update'];
const componentStates = ['healthy', 'unhealthy', 'unknown', 'unavailable'];

export type ApiErrorCode = 'unavailable' | 'not_found' | 'http_error' | 'invalid_response';
export class DashboardApiError extends Error {
  constructor(public readonly code: ApiErrorCode) { super(code); }
}

const record = (value: unknown): value is ObjectValue => typeof value === 'object' && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0;
const optionalText = (value: unknown) => value === null || text(value);
const optionalCount = (value: unknown) => value === null || (typeof value === 'number' && Number.isInteger(value) && value >= 0);
const member = (value: unknown, options: string[]) => typeof value === 'string' && options.includes(value);

export function validRun(value: unknown): value is RunRecord {
  if (!record(value)) return false;
  return text(value.id) && text(value.incident_id) && text(value.trace_id)
    && member(value.source, sources) && member(value.status, runStatuses)
    && optionalText(value.case_id) && optionalText(value.fault_id)
    && optionalText(value.started_at) && optionalText(value.finished_at)
    && optionalCount(value.model_calls) && optionalCount(value.action_count)
    && (value.recovery_latency_ms === null || typeof value.recovery_latency_ms === 'number' && Number.isFinite(value.recovery_latency_ms) && value.recovery_latency_ms >= 0)
    && (value.success === null || typeof value.success === 'boolean') && record(value.metadata);
}

export function validEvent(value: unknown): value is EventRecord {
  if (!record(value)) return false;
  return text(value.event_id) && text(value.run_id) && text(value.incident_id) && text(value.trace_id)
    && optionalText(value.case_id) && optionalText(value.parent_event_id)
    && optionalText(value.timestamp) && optionalText(value.original_event_id)
    && typeof value.ordinal === 'number' && Number.isInteger(value.ordinal) && value.ordinal >= 0
    && member(value.stage, stages) && member(value.source, sources)
    && member(value.origin, ['trace_journal', 'decision_trace', 'experience_update'])
    && (value.status === null || member(value.status, ['started', 'success', 'failed', 'skipped', 'waiting_human']))
    && text(value.message) && record(value.data);
}

async function read(path: string, signal?: AbortSignal, fetcher: Fetcher = fetch): Promise<unknown> {
  let response: Response;
  try {
    response = await fetcher(`${API}${path}`, { method: 'GET', signal, cache: 'no-store',
      credentials: 'omit', mode: 'same-origin', redirect: 'error' });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new DashboardApiError('unavailable');
  }
  if (response.status === 404) throw new DashboardApiError('not_found');
  if (!response.ok) throw new DashboardApiError('http_error');
  try { return await response.json(); }
  catch { throw new DashboardApiError('invalid_response'); }
}

export async function readSystemStatus(signal?: AbortSignal, fetcher?: Fetcher): Promise<SystemStatus> {
  const value = await read('/system/status', signal, fetcher);
  if (!record(value) || !member(value.status, ['healthy', 'degraded', 'unknown', 'unavailable'])
      || value.source !== 'real' || !record(value.components)
      || !['api', 'postgres', 'redis', 'users', 'control'].every(key => member((value.components as ObjectValue)[key], componentStates))) {
    throw new DashboardApiError('invalid_response');
  }
  return value as unknown as SystemStatus;
}

export async function readRuns(source: Provenance, signal?: AbortSignal, fetcher?: Fetcher): Promise<RunPage> {
  const value = await read(`/runs?source=${source}&limit=50&offset=0`, signal, fetcher);
  if (!record(value) || !Array.isArray(value.items) || !value.items.every(validRun)
      || !value.items.every(item => item.source === source)
      || !optionalCount(value.total) || value.total === null
      || !optionalCount(value.limit) || value.limit === null
      || !optionalCount(value.offset) || value.offset === null) {
    throw new DashboardApiError('invalid_response');
  }
  return value as unknown as RunPage;
}

export async function readRun(runId: string, signal?: AbortSignal, fetcher?: Fetcher): Promise<RunRecord> {
  const value = await read(`/runs/${encodeURIComponent(runId)}`, signal, fetcher);
  if (!validRun(value) || value.id !== runId) throw new DashboardApiError('invalid_response');
  return value;
}

export async function readEvents(runId: string, signal?: AbortSignal, fetcher?: Fetcher): Promise<EventPage> {
  const value = await read(`/runs/${encodeURIComponent(runId)}/events`, signal, fetcher);
  if (!record(value) || value.run_id !== runId || !Array.isArray(value.items)
      || !value.items.every(validEvent) || !optionalCount(value.total) || value.total !== value.items.length) {
    throw new DashboardApiError('invalid_response');
  }
  return value as unknown as EventPage;
}
