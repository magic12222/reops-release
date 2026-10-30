export interface VikunjaState {
  monitor_offer_id?:string|null;
  available: boolean; demo_busy: boolean;
  automation: { mode: 'observe' | 'automatic'; state: string; offer_id: string | null;
    dependency_offer_id?: string | null; plan_id?: 'database_only' | 'vikunja_dependency_v1';
    dependency_plan?: {id:string;max_database_starts_per_incident:number;max_application_starts_per_incident:number;sql_timeout_seconds:number;business_timeout_seconds:number;order:string[]};
    remaining_actions: number; remaining_seconds: number; inflight: boolean;
    policy: { duration_hours: number; max_actions: number; cooldown_seconds: number; action: string; model_calls: number; fault_injection: boolean };
    events: { timestamp: string; event: string; reason?:string; step?:string; source?:string; trace_id?:string; incident_id?:string; check?:number; observation_id?:string }[] };
  demo: { id: string; state: string; pending: { id: string; expires_at: number } | null;
    result: { passed: boolean; recovery_verified?: boolean; cleanup_extra_starts?: number;
      b_agent_closed_loop?: boolean; memory_written?: boolean; diagnosis_source?: string } | null } | null;
}
const object = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
export function parseVikunjaState(value: unknown): VikunjaState {
  if (!object(value) || typeof value.available !== 'boolean' || typeof value.demo_busy !== 'boolean' || !object(value.automation)) throw new Error('Recovery status could not be read.');
  const a = value.automation;
  if(value.monitor_offer_id!==undefined&&value.monitor_offer_id!==null&&(typeof value.monitor_offer_id!=='string'||!value.monitor_offer_id||value.monitor_offer_id.length>128))throw new Error('Monitoring approval scope could not be validated.');
  if (a.plan_id !== undefined && !['database_only','vikunja_dependency_v1'].includes(String(a.plan_id))) throw new Error('Unknown recovery plan.');
  if (a.dependency_plan !== undefined) {
    const p=a.dependency_plan;
    if (!object(p) || p.id!=='vikunja_dependency_v1' || p.max_database_starts_per_incident!==1 || p.max_application_starts_per_incident!==1
      || p.sql_timeout_seconds!==45 || p.business_timeout_seconds!==45 || JSON.stringify(p.order)!==JSON.stringify(['start_postgres','wait_sql','start_exited_app_if_confirmed','two_fresh_business_checks'])
      || !(a.dependency_offer_id===null || typeof a.dependency_offer_id==='string')) throw new Error('Dependency recovery scope could not be validated.');
  }
  if (a.plan_id==='vikunja_dependency_v1' && !a.dependency_plan) throw new Error('Dependency recovery scope is missing.');
  if (!['observe','automatic'].includes(String(a.mode)) || typeof a.state !== 'string'
    || !(a.offer_id === null || typeof a.offer_id === 'string') || typeof a.inflight !== 'boolean'
    || !Number.isFinite(a.remaining_actions) || !Number.isFinite(a.remaining_seconds)
    || !object(a.policy) || a.policy.duration_hours !== 8 || a.policy.max_actions !== 3
    || a.policy.cooldown_seconds !== 60 || a.policy.action !== (a.plan_id==='vikunja_dependency_v1'?'postgres_sql_then_conditional_app_start':'start_service(postgres)')
    || a.policy.model_calls !== 0 || a.policy.fault_injection !== false
    || !Array.isArray(a.events) || a.events.length > 512
    || a.events.some(e => !object(e) || typeof e.timestamp !== 'string' || typeof e.event !== 'string'
      || ['reason','step','source','trace_id','incident_id','observation_id'].some(key=>e[key]!==undefined&&typeof e[key]!=='string'))) throw new Error('Recovery policy could not be validated.');
  const d = value.demo;
  if (d !== null && (!object(d) || typeof d.id !== 'string' || typeof d.state !== 'string'
    || !(d.pending === null || (object(d.pending) && typeof d.pending.id === 'string' && Number.isFinite(d.pending.expires_at)))
    || !(d.result === null || (object(d.result) && typeof d.result.passed === 'boolean')))) throw new Error('Demonstration status could not be validated.');
  return value as unknown as VikunjaState;
}
export function createVikunjaClient(fetcher: typeof fetch = (...args) => fetch(...args)) {
  let token = '';
  async function request(operation: string, payload?: Record<string, unknown>, signal?: AbortSignal) {
    if (!token) {
      const r = await fetcher('/api/v1/workbench/control/status', {credentials:'same-origin',cache:'no-store',redirect:'error',mode:'same-origin',signal});
      const v: unknown = await r.json();
      if (!r.ok || !object(v) || typeof v.csrf !== 'string') throw new Error('Refresh the monitoring connection and try again.');
      token = v.csrf;
    }
    const response = await fetcher('/api/v1/workbench/control/vikunja/' + operation, {
      method: payload ? 'POST' : 'GET', credentials:'same-origin', cache:'no-store', redirect:'error', mode:'same-origin', signal,
      ...(payload ? {headers:{'Content-Type':'application/json','X-ReOps-Monitor-Token':token},body:JSON.stringify(payload)} : {}) });
    if (!response.ok) throw new Error(response.status === 403 ? 'Session expired. Refresh the connection.' : 'The target state changed. Refresh and try again.');
    return parseVikunjaState(await response.json());
  }
  return {status:(signal?: AbortSignal) => request('status',undefined,signal),
    enable:(offer: string) => request('enable',{approved:true,offer_id:offer}),
    enableDependency:(offer: string) => request('enable-dependency',{approved:true,offer_id:offer,plan_id:'vikunja_dependency_v1'}),
    startAutomatic:(offer: string) => request('start-automatic',{approved:true,offer_id:offer,plan_id:'vikunja_dependency_v1'}),
    disable:() => request('disable',{}), demo:() => request('demo',{}),
    approve:(job: string,confirmation: string) => request('approve',{approved:true,job_id:job,confirmation_id:confirmation}),
    cancel:(job: string) => request('cancel',{job_id:job})};
}
