import type {Incident,WorkbenchEvent} from './contract';
import type {VikunjaState} from './vikunjaClient';
type Automation=VikunjaState['automation'];
const stages:Record<string,[WorkbenchEvent['stage'],string]>={fault_confirmed:['failure_detection','Fault confirmed'],dependency_observed:['observe','Fresh target observation'],recovery_started:['recovery_decision','Recovery strategy selected'],dependency_action_reserved:['recovery_decision','Action authorized'],dependency_safety_passed:['recovery_decision','Safety checks passed'],database_started:['recovery_execution','Database started'],sql_wait_started:['verification','Waiting for readiness'],sql_probe:['verification','SQL probe'],sql_ready:['verification','SQL ready'],application_exit_confirmed:['localization','Dependent exit confirmed'],application_started:['recovery_execution','Application started'],application_start_skipped:['recovery_execution','Application remained running'],verification_started:['verification','Verifying business'],business_check:['verification','Business check'],verification_passed:['verification','Fresh business and SQL check'],recovery_verified:['verification','Recovery verified'],recovery_requires_attention:['verification','Recovery needs attention'],dependency_action_failed:['recovery_execution','Action failed or uncertain']};

// Live monitor projection only. Never claims a persisted B experience or model conversation.
export function liveRecoveryIncidents(a:Automation):Incident[] {
  const groups=new Map<string,typeof a.events>();
  for(const event of a.events)if(event.trace_id&&stages[event.event])groups.set(event.trace_id,[...(groups.get(event.trace_id)??[]),event]);
  return [...groups].flatMap(([trace,rows])=>{
    if(rows[0].event!=='fault_confirmed'||!rows[0].incident_id)return [];
    const failed=rows.some(row=>['recovery_requires_attention','dependency_action_failed'].includes(row.event));
    const checks=rows.filter(row=>row.event==='verification_passed');
    const verified=!failed&&rows.some(row=>row.event==='recovery_verified')&&checks.length>=2&&new Set(checks.map(row=>row.observation_id).filter(Boolean)).size>=2;
    return [{id:rows[0].incident_id,target_id:'reops-vikunja-demo',trace_id:trace,title:'Automatic recovery',started_at:rows[0].timestamp,status:failed?'failed':verified?'recovered':a.inflight?'executing':'unknown',diagnosis_source:'rule',summary:'Live monitoring event projection; not a persisted B experience.',experience_ids:[],model_calls:[],verification:{status:verified?'passed':failed?'failed':'pending',checks:checks.map(row=>'observation_id='+row.observation_id)},events:rows.map((row,index)=>({id:`live:${trace}:${index}:${row.event}`,sequence:index,timestamp:row.timestamp,stage:stages[row.event][0],title:stages[row.event][1],detail:'Actual monitoring event. B persistence and model messages are separate sources.',status:['dependency_action_failed','recovery_requires_attention'].includes(row.event)?'failed':'succeeded',evidence:['source=live_monitor_events',...Object.entries(row).filter(([key])=>['event','reason','step','source','check','observation_id'].includes(key)).map(([key,value])=>`${key}=${value}`)]}))} as Incident];
  });
}

export function createExecutionFollower(){
  let armed=false,initialized=false;const seen=new Set<string>();
  return {arm(a:Automation){initialized=true;armed=true;const approval=a.events.map(e=>e.event).lastIndexOf('policy_approved');a.events.slice(0,approval<0?a.events.length:approval+1).forEach(e=>{if(e.trace_id)seen.add(e.trace_id);});},observe(a:Automation){
    if(!initialized){initialized=true;armed=a.mode==='automatic';a.events.forEach(e=>{if(e.trace_id)seen.add(e.trace_id);});return armed&&a.inflight?a.events.filter(e=>e.event==='fault_confirmed'&&e.trace_id).at(-1)?.trace_id??null:null;}
    if(a.mode==='automatic')armed=true;
    const next=a.events.filter(e=>e.event==='fault_confirmed'&&e.trace_id&&!seen.has(e.trace_id)).at(-1);
    a.events.forEach(e=>{if(e.trace_id)seen.add(e.trace_id);});
    if(armed&&next?.trace_id){armed=a.mode==='automatic';return next.trace_id;}
    if(a.mode!=='automatic')armed=false;
    return null;
  }};
}

type Run = Pick<Incident,'trace_id'|'started_at'|'status'>;
export function createRunFollower(){
  let initialized=false;const seen=new Set<string>();
  return {observe(runs:Run[],selectedTrace:string|null,enabled=true):string|null{
    if(!runs.length)return null;
    const ordered=[...runs].filter(run=>Number.isFinite(Date.parse(run.started_at))).sort((a,b)=>Date.parse(b.started_at)-Date.parse(a.started_at));
    const selected=ordered.find(run=>run.trace_id===selectedTrace);
    const fresh=ordered.filter(run=>!seen.has(run.trace_id));
    const first=!initialized;initialized=true;
    ordered.forEach(run=>seen.add(run.trace_id));
    if(!enabled)return null;
    // Catch an in-flight run already present on the first response, but keep an
    // explicit missing/history trace when no newer recovery is actually active.
    const next=first?selected&&ordered.find(run=>['observing','diagnosing','executing','verifying'].includes(run.status)):fresh[0];
    if(!next||next.trace_id===selectedTrace)return null;
    if(selected&&Date.parse(next.started_at)<Date.parse(selected.started_at))return null;
    return next.trace_id;
  }};
}

export function recoveryPolicyNotice(a:Automation):string|null{
  const last=a.events.filter(e=>e.event.startsWith('policy_')).at(-1);
  if(a.mode==='automatic')return 'Approval confirmed. Automatic recovery is enabled. Execution opens when a new recovery begins.';
  if(last?.event==='policy_disabled')return last.reason==='monitor_paused_or_target_changed'?'Automatic recovery was disabled after monitoring or the approved target changed. Review the target and approve again.':'Automatic recovery is off.';
  return null;
}
