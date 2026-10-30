import { t, useLocale, getLocale } from '../../i18n';
import {CheckCircle2, Circle, ShieldCheck, KeyRound, FileText} from 'lucide-react';
import type {Incident, WorkbenchEvent} from '../../workbench/contract';
import {evidenceFields, eventCode, eventPhase, linkedModelCalls, phaseNames, probeSummary, recordedSpan, runOutcome, verificationEvent} from './presentation';

export function RunOutcome({incident, onSelect}: {incident: Incident; onSelect: (event: WorkbenchEvent) => void}) {
  useLocale();
  const outcome = runOutcome(incident);
  const span = recordedSpan(incident);
  const checks = incident.verification.checks;
  const sql = incident.events.filter(event => event.stage === 'verification' && evidenceFields(event).some(field => field.key === 'query')).at(-1);
  const business = incident.events.filter(event => event.stage === 'verification' && evidenceFields(event).some(field => field.key === 'business_passed')).at(-1);
  return <section className="execution-outcome" data-tone={outcome.tone} aria-label={t("Run outcome")}>
    <div className="execution-outcome-main"><div><span className="execution-status">{outcome.tone === 'success' ? <CheckCircle2 size={16}/> : <Circle size={14}/>} {t(outcome.label)}</span><span className="execution-run-stage">{t(incident.status)}</span></div><p>{t(outcome.description)}</p></div>
    <dl className="execution-outcome-facts"><div><dt>{t("Verification")}</dt><dd>{t(incident.verification.status)}</dd></div><div><dt>{t("Recorded span")}</dt><dd title={t("From run start to the latest execution evidence; excludes experience persistence. Total run duration is not provided.")}>{span === null ? t('Unavailable') : t("{0}s", span.toFixed(1))}</dd></div></dl>
    {(sql || business) && <div className="execution-probe-results">{sql && <button onClick={() => onSelect(sql)}>{t("Last SQL probe · ")}{t(probeSummary(sql, 'sql'))} →</button>}{business && <button onClick={() => onSelect(business)}>{t("Last business check · ")}{t(probeSummary(business, 'business'))} →</button>}</div>}
    <details className="execution-result-checks"><summary>{t("Verification evidence · ")}{checks.length}{t(" recorded ")}{checks.length === 1 ? t('check') : t('checks')}</summary>
      {checks.length ? <ul>{checks.map((check, index) => {const event = verificationEvent(incident, check); return <li key={index}><span>{check}</span>{event && <button onClick={() => onSelect(event)}>{t("Inspect event →")}</button>}</li>;})}</ul> : <p>{t("No check records are exposed for this run.")}</p>}
      {incident.events.some(event => event.stage === 'verification') && <div className="execution-result-links">{incident.events.filter(event => event.stage === 'verification').slice(-3).map(event => <button key={event.id} onClick={() => onSelect(event)}>{event.title} →</button>)}</div>}
    </details>
  </section>;
}

const labels: Record<string, string> = {step: 'Action target', action_id: 'Action ID', observation_id: 'Observation', check: 'Check', reason: 'Reason',
  method: 'Method', endpoint: 'Endpoint', status_code: 'HTTP status', query: 'SQL query', passed: 'Check passed', business_passed: 'Business passed',
  authorization_consumed_by_a: 'Authorization consumed by A', timeout_seconds: 'Timeout (s)', execution_status: 'Execution status', business: 'Business'};

export function EventEvidence({event, incident}: {event: WorkbenchEvent; incident: Incident}) {
  useLocale();
  const phase = eventPhase(event);
  const fields = evidenceFields(event);
  const keyFields = [...new Map(fields.filter(field => labels[field.key]).map(field => [JSON.stringify(field), field])).values()];
  const sources = [...new Set(fields.filter(field => field.key === 'source' && !['dependency_audit_projection', 'live_monitor_events'].includes(field.value)).map(field => field.value))];
  const detail = event.detail.trim();
  const boilerplate = (event.evidence.includes('profile=dependency-audit-v1') && detail === 'Recorded automatic dependency recovery event. Original audit remains unchanged.')
    || (event.evidence.includes('source=live_monitor_events') && detail === 'Actual monitoring event. B persistence and model messages are separate sources.');
  const showDetail = detail && detail !== event.title.trim() && !boilerplate;
  const unstructured = [...new Set(event.evidence.filter(value => !value.includes('=') && value.trim() !== event.title.trim() && !(showDetail && value.trim() === detail)))];
  const linked = linkedModelCalls(event, incident.model_calls);
  const code = eventCode(event);
  return <section className="execution-selected-evidence" aria-label={t("Selected event evidence")} data-event-id={event.id}>
    <div className="execution-evidence-heading"><span>{phase === 'authorization' ? <KeyRound size={14}/> : phase === 'safety' ? <ShieldCheck size={14}/> : <FileText size={14}/>} {t(phaseNames[phase] ?? phase)}</span><span className="execution-step-status" data-status={event.status}>{t(event.status.replaceAll('_', ' '))}</span></div>
    <h3>{event.title}</h3><time dateTime={event.timestamp}>{t(new Date(event.timestamp).toLocaleString(getLocale(), {timeZone: 'Asia/Shanghai', hour12: false}))}{t(" CST")}</time>
    {phase === 'authorization' && code === 'dependency_action_reserved' && <p className="execution-control-note">{t("A single action authorization was consumed. Safety checks and execution are separate records.")}</p>}
    {phase === 'safety' && <p className="execution-control-note">{t("This records the safety decision for this step. It does not confirm command completion or business recovery.")}</p>}
    {showDetail && <p>{event.detail}</p>}
    {keyFields.length > 0 && <dl className="execution-evidence-fields">{keyFields.map((field, index) => <div key={index}><dt>{t(labels[field.key])}</dt><dd>{field.value}</dd></div>)}</dl>}
    {sources.length > 0 && <p className="execution-check-basis">{t("Recorded basis: ")}{sources.join(' · ')}</p>}
    {unstructured.length > 0 && <ul className="execution-evidence-text">{unstructured.map((value, index) => <li key={index}>{value}</li>)}</ul>}
    {!keyFields.length && !unstructured.length && !sources.length && <p>{t("No structured step evidence is exposed. Inspect the original record below.")}</p>}
    <details><summary>{t("Original event & provenance")}</summary><pre>{JSON.stringify(event, null, 2)}</pre></details>
    {!!incident.model_calls.length && <p className="execution-association" title={linked.length ? t(undefined) : t('No explicit model call reference for this event.')}>{linked.length ? t("Model call: {0}", linked.map(call => call.id).join(', ')) : t('Model records are linked to this run only.')}</p>}
  </section>;
}
