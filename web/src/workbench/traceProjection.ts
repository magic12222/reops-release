import type { Snapshot } from './contract';
import type { EventRecord, RunRecord } from '../types/dashboard';
import { toReadTrace } from '../data/adapter';

export function workbenchTrace(data: Snapshot, traceId: string) {
  const matches = data.incidents.filter(item => item.trace_id === traceId);
  if (data.source !== 'real' || matches.length !== 1) throw new Error('workbench_exact_trace_required');
  const incident = matches[0];
  const run: RunRecord = { id: incident.id, incident_id: incident.id, trace_id: incident.trace_id,
    case_id: null, fault_id: null, source: 'real', status: incident.status === 'waiting_human' ? 'waiting_authorization' : incident.status,
    started_at: incident.started_at, finished_at: null, model_calls: null, action_count: null, recovery_latency_ms: null,
    success: incident.status === 'recovered' ? true : incident.status === 'failed' ? false : null,
    metadata: { ingest_kind: 'workbench_snapshot_projection', c_database_imported: false,
      title: incident.title, target_id: incident.target_id, diagnosis_source: incident.diagnosis_source,
      recorded_model_calls: incident.model_calls.length, experience_ids: incident.experience_ids,
      verification: incident.verification, model_calls: incident.model_calls } };
  const statuses = { running: 'started', succeeded: 'success', failed: 'failed', skipped: 'skipped', waiting_human: 'waiting_human', unknown: null } as const;
  const events: EventRecord[] = incident.events.map(event => ({
    event_id: event.id, run_id: incident.id, incident_id: incident.id, trace_id: incident.trace_id,
    case_id: null, ordinal: event.sequence, parent_event_id: null, stage: event.stage, status: statuses[event.status],
    timestamp: event.timestamp, message: event.title, source: 'real', origin: 'workbench_projection', original_event_id: null,
    data: { summary: event.detail, evidence: event.evidence, original_workbench_event: event,
      source_field: 'Snapshot.incidents.events', parent_link: 'not_exposed_by_snapshot_0.1' },
  }));
  return { run, trace: toReadTrace(run, events) };
}
