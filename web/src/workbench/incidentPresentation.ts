import type { Incident,WorkbenchEvent } from './contract';
import {recordedSpanSeconds} from './recordedSpan';
import { t } from '../i18n';
import {eventCode,eventPhase,evidenceFields,phaseNames,probeSummary} from '../pages/execution/presentation';

export function recoveryMethod(incident: Incident): string {
  if (incident.diagnosis_source === 'rule') return 'Rule-based recovery';
  if (incident.diagnosis_source === 'experience') return 'Experience-based recovery';
  if (incident.diagnosis_source === 'model') return incident.model_calls.length ? 'Model-based diagnosis' : 'Model diagnosis reported · no call record';
  return 'Diagnosis source unknown';
}

export function eventLabel(event:WorkbenchEvent) {
  const code=eventCode(event);
  const names:Record<string,string>={sql_probe:'SQL probe',sql_ready:'SQL ready',sql_wait_started:'Wait for SQL',business_check:'Business read',verification_started:'Start verification',recovery_verified:'Recovery verified',dependency_memory_saved:'Experience saved',experience_saved:'Experience saved'};
  if(code==='verification_passed')return t('Verify {0}', evidenceFields(event).find(f=>f.key==='check')?.value??'').trim();
  if(event.stage==='experience_update'&&event.status==='succeeded')return 'Experience saved';
  return code&&names[code]||phaseNames[eventPhase(event)]||event.stage;
}
export function eventFact(event:WorkbenchEvent) {
  const fields=evidenceFields(event);
  if(fields.some(f=>f.key==='query'))return probeSummary(event,'sql');
  if(fields.some(f=>f.key==='business_passed'))return probeSummary(event,'business');
  return event.title;
}

export function recordedSpan(incident: Incident): string | null {
  if (!['recovered', 'failed'].includes(incident.status)) return null;
  const seconds = recordedSpanSeconds(incident);
  return seconds === null ? null : t('{0}s recorded span', seconds.toFixed(1));
}

export function incidentHistory(incidents: Incident[], query: string, attention: boolean) {
  const term = query.trim().toLowerCase();
  return incidents.filter(item => (!attention || item.status !== 'recovered')
    && [item.title, item.id, item.trace_id, item.summary, item.status].join(' ').toLowerCase().includes(term))
    .sort((a, b) => (Date.parse(b.started_at) || 0) - (Date.parse(a.started_at) || 0));
}
