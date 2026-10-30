import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {describe,it,expect} from 'vitest';
import {createExecutionFollower,createRunFollower,liveRecoveryIncidents,recoveryPolicyNotice} from './liveRecovery';
import type {VikunjaState} from './vikunjaClient';
function state():VikunjaState['automation']{return {mode:'automatic',state:'watching',offer_id:null,inflight:false,remaining_actions:3,remaining_seconds:100,policy:{duration_hours:8,max_actions:3,cooldown_seconds:60,action:'start_service(postgres)',model_calls:0,fault_injection:false},events:[{event:'fault_confirmed',timestamp:'2026-10-28T01:00:00Z',trace_id:'old',incident_id:'old-incident'},{event:'recovery_requires_attention',timestamp:'2026-10-28T01:01:00Z',trace_id:'old',incident_id:'old-incident'},{event:'policy_approved',timestamp:'2026-10-28T02:00:00Z'}]};}
describe('follow an approved recovery',()=>{
 it('waits for a new real trace and navigates only once',()=>{const a=state(),f=createExecutionFollower();f.arm(a);expect(f.observe(a)).toBeNull();a.events.push({event:'fault_confirmed',timestamp:'2026-10-28T02:01:00Z',trace_id:'new',incident_id:'new-incident'});expect(f.observe(a)).toBe('new');expect(f.observe(a)).toBeNull();});
 it('does not redirect historical records or a revoked policy',()=>{const a=state(),f=createExecutionFollower();expect(f.observe(a)).toBeNull();a.mode='observe';expect(f.observe(a)).toBeNull();a.events.push({event:'fault_confirmed',timestamp:'2026-10-28T02:01:00Z',trace_id:'new'});expect(f.observe(a)).toBeNull();});
 it('handles a run that began before the approval response finished',()=>{const a=state();a.events.push({event:'fault_confirmed',timestamp:'2026-10-28T02:01:00Z',trace_id:'new'});const f=createExecutionFollower();f.arm(a);expect(f.observe(a)).toBe('new');});
 it('projects real events without fabricating B experiences, model replies or success',()=>{const a=state();const run=liveRecoveryIncidents(a)[0];expect(run.status).toBe('failed');expect(run.experience_ids).toEqual([]);expect(run.model_calls).toEqual([]);expect(run.events[0].evidence).toContain('source=live_monitor_events');a.events=[a.events[0],{...a.events[0],event:'recovery_verified'}];expect(liveRecoveryIncidents(a)[0].status).not.toBe('recovered');});
 it('explains a later revocation separately from a successful approval',()=>{const a=state();expect(recoveryPolicyNotice(a)).toContain('Approval confirmed');a.mode='observe';a.events.push({event:'policy_disabled',timestamp:'2026-10-28T02:02:00Z',reason:'monitor_paused_or_target_changed'});expect(recoveryPolicyNotice(a)).toContain('approved target changed');});
 it('continues switching for the second and third recoveries under the same policy',()=>{const a=state(),f=createExecutionFollower();f.arm(a);for(const trace of ['one','two','three']){a.events.push({event:'fault_confirmed',timestamp:'2026-10-28T02:01:00Z',trace_id:trace});expect(f.observe(a)).toBe(trace);expect(f.observe(a)).toBeNull();}});
 it('opens an already running recovery on return to the workbench',()=>{const a=state();a.inflight=true;a.events.push({event:'fault_confirmed',timestamp:'2026-10-28T02:01:00Z',trace_id:'inflight'});expect(createExecutionFollower().observe(a)).toBe('inflight');});
});

describe('switch execution conversations independently of timeline selection',()=>{
 const run=(trace_id:string,second:number,status:'recovered'|'executing'='recovered')=>({trace_id,started_at:new Date(Date.UTC(2026,9,28,2,0,second)).toISOString(),status});
 it('catches an active newer session in the first snapshot',()=>{const f=createRunFollower();expect(f.observe([run('old',0),run('new',10,'executing')],'old')).toBe('new');});
 it('follows every new session, including one completed while the page was hidden',()=>{const f=createRunFollower();expect(f.observe([run('old',0)],'old')).toBeNull();expect(f.observe([run('old',0),run('second',10)],'old')).toBe('second');expect(f.observe([run('third',20,'executing'),run('second',10)],'second')).toBe('third');expect(f.observe([run('third',20)],'third')).toBeNull();});
 it('does not depend on a 90-second browser clock window',()=>{const f=createRunFollower();f.observe([run('old',0)],'old');expect(f.observe([run('old',0),run('new',10)],'old')).toBe('new');});
 it('ignores older imports and preserves a missing explicit trace on initial load',()=>{const f=createRunFollower();expect(f.observe([run('current',20,'executing')],'missing')).toBeNull();expect(f.observe([run('older',0),run('current',20)],'current')).toBeNull();});
 it('pauses only when automatic session switching is explicitly disabled',()=>{const f=createRunFollower();f.observe([run('old',0)],'old');expect(f.observe([run('old',0),run('new',10)],'old',false)).toBeNull();expect(f.observe([run('old',0),run('new',10),run('next',20)],'old',true)).toBe('next');});
});
