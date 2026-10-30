import { t, useLocale, getLocale } from '../i18n';
import {Activity,ArrowUpRight,CheckCircle2,Clock3} from 'lucide-react';
import type {VikunjaState} from './vikunjaClient';

const phases:Record<string,string>={fault_confirmed:'Fault confirmed',dependency_observed:'Observing target',recovery_started:'Preparing recovery',dependency_action_reserved:'Authorizing action',action_reserved:'Authorizing action',dependency_safety_passed:'Checking safety',database_started:'Executing recovery',sql_wait_started:'Waiting for readiness',sql_probe:'Checking readiness',sql_ready:'Dependency ready',application_exit_confirmed:'Confirming dependency impact',application_started:'Application started',application_start_skipped:'Application available',verification_started:'Verifying business',business_check:'Verifying business',verification_passed:'Verifying business',recovery_verified:'Verified',dependency_action_failed:'Needs attention',recovery_requires_attention:'Needs attention'};
export function RecoveryProgress({automation,blockedReason=null}:{automation:VikunjaState['automation'];blockedReason?:string|null}) {
  useLocale();
  const start=automation.events.map(item=>item.event).lastIndexOf('fault_confirmed');
  const origin=start>=0?automation.events[start]:undefined;
  const run=origin?automation.events.slice(start).filter(item=>phases[item.event]&&(!origin.trace_id||item.trace_id===origin.trace_id)):[];
  const failed=run.some(item=>['dependency_action_failed','recovery_requires_attention'].includes(item.event));
  const verified=!failed&&run.some(item=>item.event==='recovery_verified');
  const running=automation.inflight&&!failed&&!verified&&run.length>0;
  const last=run.at(-1);
  const duration=origin&&last&&run.length>1?(Date.parse(last.timestamp)-Date.parse(origin.timestamp))/1000:null;
  const time=last&&!Number.isNaN(Date.parse(last.timestamp))?new Date(last.timestamp).toLocaleString(getLocale(),{timeZone:'Asia/Shanghai',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):null;
  const status=failed?'Needs attention':verified?'Verified':running?phases[last!.event]:'Awaiting update';
  return <section className="wb-recovery-summary" aria-label={t("Recovery summary")} aria-live="polite" data-running={running}>
    <div className="wb-recovery-summary-main">{running?<Activity size={17}/>:verified?<CheckCircle2 size={17}/>:<Clock3 size={17}/>}
      <div><strong>{running ? t('Recovery in progress') : run.length ? t('Latest recovery · recorded result') : t('Recovery overview')}</strong><p>{run.length?<><span className={failed?'wb-summary-failed':undefined}>{t(status)}</span>{time&&<><span aria-hidden="true"> · </span><time dateTime={last!.timestamp}>{t(time)}{t(" CST")}</time></>}{duration!==null&&Number.isFinite(duration)&&duration>=0&&<span> · {duration.toFixed(1)}{t("s recorded span")}</span>}</>:automation.mode==='automatic'?t('Ready to recover when an incident is confirmed.'):t('No recovery recorded in this service session.')}</p></div>
    </div>
    {origin?.trace_id&&<a href={`/execution?source=real&trace=${encodeURIComponent(origin.trace_id)}`}>{running ? t('Track execution') : t('View execution')}<ArrowUpRight size={13}/></a>}
    {run.length>0&&!origin?.trace_id&&<p className="wb-summary-note">{t("Execution link unavailable: no trace ID was recorded.")}</p>}
    {blockedReason&&<p className="wb-summary-alert" role="alert">{t("Recovery blocked: ")}{t(blockedReason)}</p>}
    {failed&&<p className="wb-summary-alert" role="alert">{run.find(item=>item.event==='recovery_requires_attention')?.reason??t('Recovery failed or uncertain. Review the execution record.')}</p>}
  </section>;
}
