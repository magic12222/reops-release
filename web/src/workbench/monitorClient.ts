import { parseSnapshot } from './contract';
import type { Target } from './contract';
export interface MonitorStatus { enabled: boolean; busy: boolean; targets: Target[];
  unified_monitoring?:boolean;
  recovery_available?: boolean;
  dependency_records?: 'not_loaded'|'ready'|'conflict_or_unavailable';
  agent?: { enabled: boolean; state: 'disabled' | 'ready' | 'error'; execution_enabled: false; model_enabled: false } }
const object = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const errors: Record<string,string> = {
  monitor_target_unavailable: 'Target unavailable. Check Docker, the running API and its project ownership.',
  monitor_rate_limited: 'Please wait a moment before the next monitoring command.',
  monitor_operation_busy: 'A monitoring operation is still in progress.',
  monitor_session_invalid: 'Monitoring session expired. Refresh the connection before retrying.',
  monitor_operations_disabled: 'Start the dashboard with workbench monitoring enabled.',
  unavailable: 'Monitoring service is unavailable. Your previous data has not been replaced.',
  invalid_response: 'Monitoring response could not be validated.',
};
export class MonitorError extends Error {
  constructor(public code: string) { super(errors[code] ?? 'The monitoring request was rejected.'); }
}
export function createMonitorClient(fetcher: typeof fetch = (...args) => fetch(...args)) {
  let token = '';
  async function call(operation: 'status' | 'select' | 'start' | 'pause', signal?: AbortSignal): Promise<MonitorStatus> {
    const write = operation !== 'status';
    let response: Response;
    try {
      response = await fetcher('/api/v1/workbench/control/' + operation, { method: write ? 'POST' : 'GET',
        signal, credentials: 'same-origin', cache: 'no-store', redirect: 'error', mode: 'same-origin',
        ...(write ? { headers: { 'Content-Type':'application/json', 'X-ReOps-Monitor-Token': token }, body: '{}' } : {}) });
    } catch { throw new MonitorError('unavailable'); }
    let value: unknown;
    try { value = await response.json(); } catch { throw new MonitorError('invalid_response'); }
    if (!response.ok) throw new MonitorError(object(value) && typeof value.detail === 'string' ? value.detail : 'rejected');
    if (!object(value) || typeof value.enabled !== 'boolean' || typeof value.busy !== 'boolean' || !object(value.feed)) throw new MonitorError('invalid_response');
    const feed = value.feed;
    let targets: Target[];
    try { targets = parseSnapshot({ schema_version:'0.1', source:'real', generated_at:new Date().toISOString(),
      a_status:feed.status, b_status:'not_connected', targets:feed.targets, incidents:[], experiences:[] },'real').targets;
    } catch { throw new MonitorError('invalid_response'); }
    if (!write) {
      if (typeof value.csrf !== 'string' || !value.csrf) throw new MonitorError('invalid_response');
      token = value.csrf;
    }
    let agent: MonitorStatus['agent'];
    if (value.agent !== undefined) {
      const a = value.agent;
      if (!object(a) || typeof a.enabled !== 'boolean' || !['disabled','ready','error'].includes(String(a.state))
        || a.execution_enabled !== false || a.model_enabled !== false) throw new MonitorError('invalid_response');
      agent = { enabled:a.enabled, state:a.state as 'disabled' | 'ready' | 'error', execution_enabled:false, model_enabled:false };
    }
    if (value.recovery_available !== undefined && typeof value.recovery_available !== 'boolean') throw new MonitorError('invalid_response');
    if(value.unified_monitoring!==undefined&&typeof value.unified_monitoring!=='boolean')throw new MonitorError('invalid_response');
    if(value.dependency_records!==undefined&&!['not_loaded','ready','conflict_or_unavailable'].includes(String(value.dependency_records)))throw new MonitorError('invalid_response');
    return { enabled:value.enabled, busy:value.busy, targets, ...(agent ? { agent } : {}),
      ...(value.unified_monitoring===true?{unified_monitoring:true}:{}),
      ...(value.dependency_records?{dependency_records:value.dependency_records as MonitorStatus['dependency_records']}:{}),
      ...(value.recovery_available === true ? {recovery_available:true} : {}) };
  }
  return { status:(signal?: AbortSignal) => call('status',signal), command:(operation: 'select' | 'start' | 'pause') => call(operation) };
}
