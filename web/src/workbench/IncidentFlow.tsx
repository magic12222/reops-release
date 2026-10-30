import { t, useLocale } from '../i18n';
import type { Incident, Snapshot, Target, WorkbenchEvent } from './contract';
import './IncidentFlow.css';

export interface FlowStep { id: string; title: string; fact: string; events: WorkbenchEvent[]; state: string }
export function incidentFlow(data: Snapshot, target: Target, incident?: Incident): FlowStep[] {
  const events = incident?.events ?? [];
  const at = (...stages: WorkbenchEvent['stage'][]) => events.filter(event => stages.includes(event.stage));
  const codes = (...names: string[]) => events.filter(event => names.includes(event.title));
  const step = (id: string, title: string, items: WorkbenchEvent[], fact?: string): FlowStep => ({ id, title, events: items,
    state: items.at(-1)?.status ?? 'unknown', fact: fact ?? (items.length ? items.at(-1)!.title : t('No linked evidence')) });
  const saved = data.experiences.filter(item => item.incident_id === incident?.id);
  const reused = data.experiences.filter(item => item.incident_id !== incident?.id && incident?.diagnosis_source === 'experience' && incident.experience_ids.includes(item.id));
  const fresh = events.filter(event=>(event.title==='fresh_business_check'||event.evidence.includes('event=verification_passed'))&&event.status==='succeeded');
  // A code and its evidence must explicitly assert consumption. Stage order is not authorization proof.
  const grants = events.filter(event => (event.title === 'a_original_result_and_consumption_retained'||event.evidence.includes('event=dependency_action_reserved'))
    && event.evidence.includes('authorization_consumed_by_a=true'));
  return [
    { id: 'monitor', title: 'Continuous monitoring', state: target.monitoring === 'watching' ? 'running' : 'unknown', events: [],
      fact: t('{0} · current target sample; not linked to this incident', t(target.monitoring)) },
    step('detect', 'Anomaly detected', at('failure_detection')),
    step('observe', 'Observation & evidence', at('observe', 'localization')),
    step('diagnose', 'Diagnosis', at('root_cause_analysis'), t('Source: {0} · {1} model records', t(incident?.diagnosis_source ?? 'unknown'), incident?.model_calls.length ?? 0)),
    step('plan', 'Recovery plan', at('recovery_decision')),
    step('safety', 'Safety assessment', events.filter(event=>event.title==='safety_and_target_policy_passed'||event.evidence.includes('event=dependency_safety_passed'))),
    step('authorize', 'Authorization', grants.length ? grants : codes('recovery_authorization_required', 'recovery_disabled_by_default', 'authorization_missing_expired_or_changed'),
      grants.length ? t('A recorded authorization consumption') : t('No consumed grant exposed; see recorded wait state')),
    step('execute', 'Restricted execution', at('recovery_execution')),
    step('verify', 'Business verification', at('verification'), t('{0} · {1} successful fresh-check events; inspect IDs and times', t(incident?.verification.status ?? 'unknown'), fresh.length)),
    step('save', 'Experience saved', at('experience_update'), saved.length ? t('{0} experience records from this incident', saved.length) : t('No experience record saved for this incident')),
    { id: 'reuse', title: 'Later reuse', events: [], state: reused.length ? 'succeeded' : 'unknown',
      fact: reused.length ? t('This incident used {0} earlier experience record(s)', reused.length) : saved.length
        ? t('{0} later incidents with explicit experience diagnosis', data.incidents.filter(item => item.id !== incident?.id && item.diagnosis_source === 'experience' && item.experience_ids.some(id => saved.some(exp => exp.id === id))).length) : t('No linked reuse evidence') },
  ];
}

export function IncidentFlow({ data, target, incident, onEvent, onKnowledge }: {
  data: Snapshot; target: Target; incident?: Incident; onEvent: (id: string) => void; onKnowledge: () => void;
}) {
  useLocale();
  const steps = incidentFlow(data, target, incident);
  return <section className="incident-flow" aria-label={t("End-to-end incident evidence")}>
    <header><div><h3>{t("Evidence chain")}</h3><p>{incident ? t('One incident. Every recorded handoff.') : t('Monitoring is connected. Incident evidence has not arrived.')}</p></div><span>{data.source === 'real' ? t('LOCAL RECORDS') : t('SAMPLE RECORDS')}</span></header>
    {incident && <p className="flow-identity"><span>{t("Incident ")}<code>{incident.id}</code></span><span>{t("Trace ")}<code>{incident.trace_id}</code></span></p>}
    <div className="flow-steps">{steps.map((step, index) => <details key={step.id} className={`flow-step ${step.state}`}><summary><span className="flow-index">{String(index + 1).padStart(2, '0')}</span><strong>{t(step.title)}</strong><span className="flow-state">{step.state === 'unknown' ? t('Evidence gap') : t(step.state.replaceAll('_', ' '))}</span></summary><p>{step.fact}</p>{step.id === 'monitor' && <p>{t("Observed at ")}{t(target.observed_at ?? 'unknown')}{t(". Current health: ")}{t(target.health)}{t(". This sample does not prove historical health.")}</p>}
      {step.events.map(event => <button key={event.id} onClick={() => onEvent(event.id)}><span>{event.title}</span><code>{event.id}</code><time>{t(event.timestamp)}</time></button>)}
      {['save', 'reuse'].includes(step.id) && <button onClick={onKnowledge}>{t("Explore knowledge & provenance →")}</button>}
      {step.id === 'verify' && <ul>{incident?.verification.checks.map((check, index) => <li key={index}>{check}</li>)}</ul>}
    </details>)}</div>
    <p className="flow-note">{t("Missing evidence stays unknown. An executed command, a healthy target, and verified recovery are separate facts.")}</p>
  </section>;
}
