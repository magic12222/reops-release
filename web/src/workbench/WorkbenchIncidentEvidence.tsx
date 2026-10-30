import { t, useLocale, getLocale } from '../i18n';
import { ArrowLeft, ArrowRight, ShieldCheck } from 'lucide-react';
import type { Incident, WorkbenchEvent } from './contract';
import { evidenceFields } from '../pages/execution/presentation';
import { eventLabel, recoveryMethod } from './incidentPresentation';

const statuses: Record<string, string> = { succeeded: 'Completed', failed: 'Failed', running: 'Running', skipped: 'Skipped', waiting_human: 'Awaiting approval', unknown: 'Unknown' };
const eventTime = (value: string) => Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString(getLocale(), { timeZone:'Asia/Shanghai', hour12:false }) + ' CST' : 'Time not recorded';

export function IncidentOverview({ incident }: { incident: Incident }) {
  useLocale();
  return <section className="wb-incident-overview" aria-label={t("Incident recovery overview")}>
    <div className="wb-overview-verification"><ShieldCheck size={17}/><div><h3>{t("Recorded business verification")}</h3><strong className={`wb-state ${incident.verification.status}`}>{t(incident.verification.status)}</strong><span>{incident.verification.checks.length}{t(" recorded checks")}</span></div></div>
    <details className="wb-check-details"><summary>{t("Verification checks")}</summary>{incident.verification.checks.length ? <ul>{incident.verification.checks.map((check, index) => <li key={index}>{check}</li>)}</ul> : <p>{t("No check details recorded.")}</p>}</details>
    <details className="wb-incident-provenance"><summary>{t("Incident summary & provenance")}</summary><p>{incident.summary}</p><dl><dt>{t("Recovery / diagnosis")}</dt><dd>{t(recoveryMethod(incident))}</dd><dt>{t("Model call records")}</dt><dd>{t(incident.model_calls.length || 'None recorded · total usage unknown')}</dd><dt>{t("Incident")}</dt><dd>{incident.id}</dd><dt>{t("Trace")}</dt><dd>{incident.trace_id}</dd></dl></details>
  </section>;
}

export function RecordedEventBrowser({ incident, event, open, onOpen, onEvent }: {
  incident: Incident; event?: WorkbenchEvent; open: boolean; onOpen: (open: boolean) => void; onEvent: (id: string) => void;
}) {
  useLocale();
  const position = event ? incident.events.indexOf(event) : -1;
  const fields = event ? evidenceFields(event).filter(field => /^(step|reason|query|passed|business_passed|status_code|check|execution_status)$/.test(field.key))
    .sort((a,b) => Number(b.key==='reason')-Number(a.key==='reason')).slice(0, 3) : [];
  return <details className="wb-recorded-events" open={open} onToggle={e=>onOpen(e.currentTarget.open)}>
    <summary>{t("Recorded events ")}<span>{incident.events.length}{t(" events · browse evidence")}</span></summary>
    {event ? <div className="wb-recorded-event-content">
      <div className="wb-recorded-event-navigation"><label>{t("Event")}<select aria-label={t("Selected recorded event")} value={event.id} onChange={e=>onEvent(e.target.value)}>{incident.events.map((item,index)=><option key={item.id} value={item.id}>{String(index+1).padStart(2,'0')} · {item.title===eventLabel(item) ? item.title : t("{0} · {1}", t(eventLabel(item)), item.title)}</option>)}</select></label><div><button aria-label={t("Previous recorded event")} disabled={position<=0} onClick={()=>onEvent(incident.events[position-1].id)}><ArrowLeft size={14}/></button><button aria-label={t("Next recorded event")} disabled={position>=incident.events.length-1} onClick={()=>onEvent(incident.events[position+1].id)}><ArrowRight size={14}/></button></div></div>
      <p className="wb-recorded-event-meta"><span className={`wb-state ${event.status}`}>{t(statuses[event.status])}</span><time dateTime={event.timestamp}>{t(eventTime(event.timestamp))}</time></p>
      {!!fields.length && <dl className="wb-key-evidence">{fields.map((field,index)=><div key={index}><dt>{t(field.key.replaceAll('_',' '))}</dt><dd>{field.value}</dd></div>)}</dl>}
      <details className="wb-full-event"><summary>{t("Full event evidence · ")}{event.evidence.length}{t(" fields")}</summary><p>{event.detail}</p><code>{event.id}</code><ul>{event.evidence.map((item,index)=><li key={index}>{item}</li>)}</ul><pre>{JSON.stringify(event,null,2)}</pre></details>
    </div> : <p className="wb-content-empty">{t("No event evidence.")}</p>}
  </details>;
}
