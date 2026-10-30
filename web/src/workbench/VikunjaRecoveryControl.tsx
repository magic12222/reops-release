import { t, useLocale, getLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import { createVikunjaClient } from './vikunjaClient';
import type { VikunjaState } from './vikunjaClient';
import {createExecutionFollower,recoveryPolicyNotice} from './liveRecovery';
import {beginRecoveryAnalysis,recoveryNavigation,smoothRecoveryNavigate} from './recoveryNavigation';
import { RecoveryProgress } from './RecoveryProgress';

const labels: Record<string,string> = {observe:'Monitor only',watching:'Automatic recovery enabled',recovering:'Recovering and verifying',
  attention:'Recovery needs attention',expired:'Automatic recovery expired',budget_exhausted:'Recovery budget reached'};
const events: Record<string,string> = {policy_approved:'Automatic recovery enabled',policy_disabled:'Automatic recovery disabled',
  policy_expired:'Automatic recovery expired',policy_budget_exhausted:'Recovery budget reached',action_reserved:'Starting database recovery',
  recovery_verified:'Business recovered; both checks passed',recovery_requires_attention:'Recovery needs attention; check the event record',
  sql_wait_started:'Waiting for database SQL',sql_ready:'SQL ready',application_exit_confirmed:'Dependent application exit confirmed',
  application_started:'Application started',application_start_skipped:'Application kept running',dependency_action_reserved:'Fixed dependency action authorized',
  dependency_action_failed:'Dependency action failed or uncertain; no retry'};

export function VikunjaRecoveryControl({active,businessWatching=false,applicationStopped=false,databaseStopped=false,singleApproval=false,compact=false}: {active: boolean; businessWatching?:boolean; applicationStopped?:boolean; databaseStopped?:boolean;singleApproval?:boolean;compact?:boolean}) {
  useLocale();
  const client = useRef(createVikunjaClient()).current;
  const follower = useRef(createExecutionFollower()).current;
  const [state,setState] = useState<VikunjaState | null>(null);
  const [pending,setPending] = useState(false);
  const [error,setError] = useState('');
  const [approvalOpen,setApprovalOpen] = useState(false);
  const alive = useRef(false);
  const mutation = useRef(false);
  const version = useRef(0);
  const approveButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {alive.current=true;return () => {alive.current=false;};},[]);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController(); let reading = false;
    async function read() {
      if (reading || mutation.current || document.hidden) return;
      const requestVersion = version.current;
      reading = true;
      try {const next=await client.status(abort.signal);if (!abort.signal.aborted && requestVersion===version.current) {setState(next);setError(current=>current.startsWith('Recovery service is unavailable.')?'':current);const trace=follower.observe(next.automation);if(trace&&window.location.pathname==='/workbench'){const href=beginRecoveryAnalysis(trace);if(href)void smoothRecoveryNavigate(()=>href,()=>recoveryNavigation()?.trace===trace);}}}
      catch {if (!abort.signal.aborted && requestVersion===version.current) {setState(null);setError('Recovery service is unavailable. Status will refresh automatically.');}}
      finally {reading=false;}
    }
    void read();const timer=window.setInterval(() => void read(),2000);
    document.addEventListener('visibilitychange', read);
    return () => {abort.abort();window.clearInterval(timer);document.removeEventListener('visibilitychange', read);};
  },[active,client]);
  useEffect(() => {if (active && state?.demo?.pending) approveButton.current?.focus();},[active,state?.demo?.pending?.id]);
  async function act(operation: () => Promise<VikunjaState>,follow=false) {
    if(!active || mutation.current)return;
    mutation.current=true;version.current++;
    setPending(true);setError('');
    try {const next=await operation();if (alive.current) {setState(next);setApprovalOpen(false);if(follow&&next.automation.mode==='automatic'){follower.arm(next.automation);const trace=follower.observe(next.automation);if(trace&&window.location.pathname==='/workbench'){const href=beginRecoveryAnalysis(trace);if(href)void smoothRecoveryNavigate(()=>href,()=>recoveryNavigation()?.trace===trace);}}}}
    catch (e) {if (alive.current) setError(e instanceof Error ? e.message : 'The operation did not complete. Refresh and try again.');}
    finally {mutation.current=false;if (alive.current) setPending(false);}
  }
  const a=state?.automation;const d=state?.demo;
  const dependency=a?.plan_id==='vikunja_dependency_v1';
  const blocker=businessWatching&&applicationStopped&&dependency&&!databaseStopped&&!a?.inflight
    ?'The application is stopped while the database is running. This plan requires a confirmed database outage and dependent exit; check the recorded recovery outcome.'
    :businessWatching&&applicationStopped&&!dependency
    ? databaseStopped?'The application and database are both stopped. The application may exit after losing its database. This recovery plan supports the database only; restarting the application is not included.'
      :'The application is stopped. Database-only recovery cannot restore this application.'
    :null;
  const recentEvents=a?.events.slice(Math.max(0,a.events.map(item=>item.event).lastIndexOf('fault_confirmed')))??[];
  const progressNeedsAttention=recentEvents.some(item=>['dependency_action_failed','recovery_requires_attention'].includes(item.event));
  const disabled=!active || pending || !state?.available;
  const seconds = Math.max(0, Math.floor(a?.remaining_seconds ?? 0));
  const remaining = seconds >= 3600 ? `${Math.floor(seconds/3600)}h ${Math.floor(seconds%3600/60)}m` : seconds >= 60 ? `${Math.floor(seconds/60)}m ${seconds%60}s` : `${seconds}s`;
  if(singleApproval)return <section className="wb-recovery-controls" aria-label={t("Automatic handling progress")} aria-busy={pending}>
    {!compact&&<div className="wb-recovery-heading"><strong>{t("Automatic recovery authorization")}</strong><span className={`wb-authorization-state ${a?.mode==='automatic'?'authorized':''}`} role="status">{!a ? error ? t('Status unavailable') : t('Loading authorization…') : a.mode==='automatic' ? t('Authorized') : t('Not authorized')}</span></div>}
    {!compact&&a?.mode==='automatic'&&<div className="wb-recovery-toolbar"><span>{t(a.remaining_actions)}{t(" recoveries left · ")}{t(remaining)}{t(" remaining")}</span></div>}
    {error&&<p role="alert">{t(error)}</p>}{a&&(compact&&!a.inflight&&['observe','watching'].includes(a.state)&&!blocker&&!progressNeedsAttention&&a.events.length>0?<details className="wb-latest-recovery"><summary>{t("Latest recovery · recorded evidence")}</summary><RecoveryProgress automation={a} blockedReason={blocker}/></details>:<RecoveryProgress automation={a} blockedReason={blocker}/>)}</section>;
  return <section className="wb-recovery-controls" aria-label={t("Continuous monitoring and automatic recovery")} aria-busy={pending}>
    <div className="wb-recovery-heading"><strong>{t("Automatic recovery authorization")}</strong><span className={`wb-authorization-state ${a?.mode==='automatic'?'authorized':''}`} role="status">{!a ? error ? t('Status unavailable') : t('Loading authorization…') : a.mode==='automatic' ? t('Authorized') : t('Not authorized')}</span></div>
    <div className="wb-recovery-toolbar"><span>{dependency ? t('Database + conditional app start') : t('Database-only recovery')}</span>{a?.mode==='automatic'&&<><span>{t(a.remaining_actions)}{t(" recoveries left · ")}{t(remaining)}{t(" remaining")}</span><button disabled={disabled} onClick={()=>void act(()=>client.disable())}>{t("Turn off automatic recovery")}</button></>}{a&&a.mode!=='automatic'&&<button disabled={disabled||!!state?.demo_busy} aria-expanded={approvalOpen} aria-controls="recovery-approval-details" onClick={()=>setApprovalOpen(value=>!value)}>{t("Enable automatic recovery")}</button>}</div>
    {a && <div className="wb-policy-limits"><span>{t(a.policy.duration_hours)}{t("h approval · max ")}{t(a.policy.max_actions)}{t(" incidents")}</span><span>{t(a.policy.cooldown_seconds)}{t("s cooldown · one attempt / incident")}</span><span>{t("No model calls · no fault injection")}</span></div>}
    {a && !['observe','watching'].includes(a.state) && <p role="status">{t(labels[a.state] ?? a.state)}</p>}
    {a?.mode!=='automatic'&&a&&recoveryPolicyNotice(a)&&<p role="status">{t(recoveryPolicyNotice(a))}</p>}
    {error&&<p role="alert">{t(error)}</p>}
    <details id="recovery-approval-details" className="wb-approval-details" open={approvalOpen} onToggle={event=>setApprovalOpen(event.currentTarget.open)}><summary>{t("Recovery strategy & approval details ")}{a?.mode!=='automatic' ? t('· enable recovery') : ''}</summary>
    <p>{t("Monitoring continues while the service is running, even after you close this page. Only approved recovery actions run automatically.")}</p>
    {a?.dependency_plan&&a.mode!=='automatic'&&<div className="wb-recovery-policy"><div><strong>{t("Dependency recovery · database and application")}</strong><p>{t("Approve this new plan: start this database once, wait up to 45 seconds for SQL, then start this same application once only if Docker confirms it exited after the database stopped, without an application stop or kill. A running application is never restarted. Finish with two fresh business and SQL checks within 45 seconds.")}</p><p>{t("8 hours · up to 3 incidents · 60 seconds apart · one attempt per incident · no model calls or fault injection. Existing database-only approvals do not cover this plan.")}</p></div><button disabled={disabled||!!state?.demo_busy||!businessWatching||!a.dependency_offer_id} onClick={()=>void act(()=>client.enableDependency(a.dependency_offer_id!),true)}>{t("Approve dependency recovery")}</button></div>}
    {a?.mode!=='automatic'&&<details className="wb-legacy-policy"><summary>{t("Alternative · database-only recovery")}</summary><div className="wb-recovery-policy"><div><strong>{t("Database-only recovery")}</strong><p>{t("This click allows ReOps to start only this Vikunja demo database, then verify business health automatically. It does not stop the database. No further approval is needed during that recovery.")}</p><p>{t("Valid for 8 hours, up to 3 recoveries, at least 60 seconds apart. One attempt per incident; failures need your attention. Uses fixed rules with no model calls.")}</p></div><button disabled={disabled||!!state?.demo_busy||!businessWatching||!a?.offer_id} onClick={()=>void act(()=>client.enable(a!.offer_id!),true)}>{t("Enable database-only recovery")}</button></div></details>}
    {a?.mode==='automatic' && <p>{t("You can turn approval off at any time; a submitted action will finish verification. New recoveries open their matching Execution record automatically.")}</p>}
    {!businessWatching&&<p role="status">{t("Start business monitoring first, then wait for a healthy business check before enabling automatic recovery.")}</p>}
    {a?.mode==='automatic'&&!blocker&&<p className="wb-external-fault" role="status"><strong>{t("3 · Ready for your external fault")}</strong>{t(" Open Docker Desktop → reops-vikunja-demo → stop only postgres. Leave ReOps running. ")}{dependency ? t('If the app exits after losing its database, this plan can start it after SQL is ready.') : t('Keep the app running; this plan only starts the database.')}{t(" Return here to watch recovery and verification automatically.")}</p>}
    </details>
    {a&&<RecoveryProgress automation={a} blockedReason={blocker}/>}
    <details className="wb-advanced-demo"><summary>{t("Advanced · let ReOps inject a fault instead")}</summary><div className="wb-recovery-demo"><div><strong>{t("Fault demonstration")}</strong><p>{t("This is a separate workflow. Approve one run covering the database stop, recovery and read/write checks. Turn off automatic recovery before starting a demonstration.")}</p></div>
      <button disabled={disabled || !!state?.demo_busy || a?.mode==='automatic'} onClick={() => void act(() => client.demo())}>{t("Prepare a demonstration")}</button></div>
    </details>
    {state?.demo_busy && !d?.pending && <p role="status">{t("Preparing or running this demonstration. The service will complete the approved steps without further prompts.")}</p>}
    {d?.pending && <div className="wb-recovery-consent" role="region" aria-label={t("Approve this fault demonstration")}>
      <strong>{t("Confirm this demonstration")}</strong><p>{t("Stop the Vikunja demo database once, start it once, and verify the original task, a new task write and two fresh reads. Allow one additional start of this same database if cleanup is needed. The app stays running. No model calls.")}</p>
      <div><button ref={approveButton} disabled={disabled || Date.now()>=d.pending.expires_at*1000} onClick={() => void act(() => client.approve(d.id,d.pending!.id))}>{t("Approve and run once")}</button>
        <button disabled={disabled} onClick={() => void act(() => client.cancel(d.id))}>{t("Cancel")}</button></div></div>}
    {d?.state==='finished' && d.result && <p role="status">{d.result.passed ? t('Demonstration passed. Real business checks completed.') : t('Demonstration did not pass. Review the evidence and final health.')}</p>}
    {d?.state==='finished' && d.result?.b_agent_closed_loop === true && <p role="status">{t("B diagnosis: ")}{t(d.result.diagnosis_source ?? 'unknown')}{t(" · Experience ")}{d.result.memory_written === true ? t('saved') : t('not confirmed')}{t(". Open the matching incident to inspect provenance.")}</p>}
    {a && a.events.length>0 && <details><summary>{t("Recent recovery activity")}</summary><ol>{a.events.slice(-6).reverse().map((e,i) => <li key={`${e.timestamp}-${i}`}><time dateTime={e.timestamp}>{t(new Date(e.timestamp).toLocaleString(getLocale(),{timeZone:'Asia/Shanghai',hour12:false}))}{t(" CST")}</time> {t(events[e.event] ?? e.event)}</li>)}</ol></details>}
  </section>;
}
