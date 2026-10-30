import type {Incident, ModelCall, WorkbenchEvent} from '../../workbench/contract';
import { t } from '../../i18n';
export {recordedSpanSeconds as recordedSpan} from '../../workbench/recordedSpan';

export const phaseNames: Record<string, string> = {
  observe: 'Observe', failure_detection: 'Detect', localization: 'Localize', root_cause_analysis: 'Analyze',
  recovery_decision: 'Plan', authorization: 'Authorization', safety: 'Safety Guard',
  recovery_execution: 'Execute', verification: 'Verify', experience_update: 'Learn',
};

// Evidence can contain repeated keys (notably source). Preserve every recorded value.
export function evidenceFields(event: WorkbenchEvent) {
  return event.evidence.flatMap(value => value.split(';').flatMap(part => {
    const index = part.indexOf('=');
    return index > 0 ? [{key: part.slice(0, index), value: part.slice(index + 1)}] : [];
  }));
}
export function eventCode(event: WorkbenchEvent) {
  return evidenceFields(event).find(field => field.key === 'event')?.value;
}
export function eventPhase(event: WorkbenchEvent) {
  const code = eventCode(event);
  if (code === 'dependency_action_reserved' || ['recovery_authorization_required', 'model_authorization_required', 'authorization_missing_expired_or_changed'].includes(event.title)) return 'authorization';
  if (code === 'dependency_safety_passed' || event.title === 'safety_and_target_policy_passed') return 'safety';
  return event.stage;
}
export function isWorking(incident: Incident) {
  return ['observing', 'diagnosing', 'executing', 'verifying'].includes(incident.status);
}
export function runOutcome(incident: Incident) {
  const verified = incident.status === 'recovered' && incident.verification.status === 'passed' && incident.verification.checks.length > 0;
  const label = verified ? 'Succeeded' : incident.status === 'recovered' ? 'Unconfirmed'
    : isWorking(incident) ? 'Running' : incident.status === 'waiting_human' ? 'Waiting for authorization'
    : incident.status === 'failed' ? 'Failed' : 'Unknown';
  return {label, tone: verified ? 'success' : incident.status === 'failed' ? 'failed' : isWorking(incident) ? 'running' : 'unknown',
    description: verified ? 'Recovery verified by the run’s recorded checks.'
      : incident.status === 'failed' ? 'Recovery did not complete successfully. Inspect the recorded failure and verification.'
      : isWorking(incident) ? 'Execution is in progress. Step completion does not confirm recovery.'
      : incident.status === 'waiting_human' ? 'Execution is waiting for the required authorization.'
      : 'The feed does not confirm a successful recovery.'};
}

export function verificationEvent(incident: Incident, check: string) {
  const observation = check.split(';').find(part => part.startsWith('observation_id='));
  const matches = incident.events.filter(event => event.stage === 'verification' && (
    event.evidence.includes(check) || (observation && evidenceFields(event).some(field => `${field.key}=${field.value}` === observation))));
  // A check may occur in multiple probe/verification records. Never pick an arbitrary match.
  return matches.length === 1 ? matches[0] : undefined;
}
export function linkedModelCalls(event: WorkbenchEvent, calls: ModelCall[]) {
  // Same run or nearest timestamp is insufficient to establish step-level causality.
  const ids = evidenceFields(event).filter(field => field.key === 'model_call_id').map(field => field.value);
  return calls.filter(call => ids.includes(call.id));
}
export function modelRelationship(incident: Incident) {
  const fixed=incident.events.some(event => event.evidence.includes('profile=dependency-audit-v1') || event.evidence.includes('source=live_monitor_events'));
  if(fixed)return incident.model_calls.length
    ? t('Fixed recovery policy · {0} model request {1}. Inspect replies and status; authorization and Safety Guard govern execution.', incident.model_calls.length, t(incident.model_calls.length===1?'record':'records'))
    : 'Fixed recovery policy · no model request is exposed for this run.';
  return incident.diagnosis_source === 'model'
    ? 'Diagnosis source: model. Actions still require the executor’s authorization and safety checks.'
    : t('Diagnosis source: {0}. Model records alone do not establish control over execution.', t(incident.diagnosis_source));
}

export function probeSummary(event: WorkbenchEvent, kind: 'sql' | 'business') {
  const fields = evidenceFields(event);
  const value = (key: string) => fields.find(field => field.key === key)?.value;
  const result = (raw?: string) => raw === 'True' || raw === 'true' ? t('Passed') : raw === 'False' || raw === 'false' ? t('Failed') : raw ?? t('Unknown');
  if (kind === 'sql') return [value('query'), result(value('passed'))].filter(Boolean).join(' · ');
  const passed = result(value('passed')), business = result(value('business_passed'));
  return [value('status_code') ? `HTTP ${value('status_code')}` : null,
    passed === business ? business : t('Business {0} · check {1}', business.toLowerCase(), passed.toLowerCase())].filter(Boolean).join(' · ');
}
