import {
  JsonObject, SystemStatus, RunRecord, RunPage, EventRecord, EventPage, ComponentRecord,
  TargetRecord, WorkbenchEvent, ModelCall, Verification, IncidentRecord, ExperienceRecord, WorkbenchSnapshot
} from '../models/ApiModels';
import { ApiError } from './ApiError';
import { MobileContext, IncidentSummary, IncidentPage, MobileOverview, FreshTarget, RelatedEvent,
  MobileDiagnosis, MobileRecovery, MobileDetail, RunLink } from '../models/MobileModels';

function check(valid: boolean): void { if (!valid) throw new ApiError('contract'); }
function object(value: Object | null): JsonObject {
  check(value !== null && typeof value === 'object' && !Array.isArray(value));
  return value as JsonObject;
}
function text(value: Object | null): string { check(typeof value === 'string'); return value as string; }
function id(value: Object | null): string { const result = text(value); check(result.length > 0); return result; }
function member(value: Object | null, options: string[]): string {
  const result = text(value); check(options.includes(result)); return result;
}
function count(value: Object | null): number {
  check(typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value) && (value as number) >= 0);
  return value as number;
}
function nullableText(value: Object | null): string | null { return value === null ? null : text(value); }
function nullableCount(value: Object | null): number | null { return value === null ? null : count(value); }
function array(value: Object | null): Object[] { check(Array.isArray(value)); return value as Object[]; }
function texts(value: Object | null): string[] { return array(value).map((item: Object) => text(item)); }
function parse(raw: string): JsonObject {
  let parsed: Object | null = null;
  try { parsed = JSON.parse(raw) as Object | null; } catch { throw new ApiError('json'); }
  return object(parsed);
}
function unique(ids: string[]): void { check(new Set(ids).size === ids.length); }
const HEALTH: string[] = ['healthy', 'unhealthy', 'unknown'];
const STAGES: string[] = ['observe', 'failure_detection', 'localization', 'root_cause_analysis',
  'recovery_decision', 'recovery_execution', 'verification', 'experience_update'];
const RUN_STATUS: string[] = ['unknown', 'pending', 'observing', 'diagnosing', 'waiting_authorization',
  'executing', 'verifying', 'recovered', 'failed', 'inconclusive'];

export function decodeSystem(raw: string, source: string = 'real'): SystemStatus {
  const o = parse(raw);
  const c = object(o['components']);
  const components: Record<string, string> = {};
  ['api', 'postgres', 'redis', 'users', 'control'].forEach((key: string) => {
    components[key] = member(c[key], [...HEALTH, 'unavailable']);
  });
  return { status: member(o['status'], ['healthy', 'degraded', 'unknown', 'unavailable']),
    source: member(o['source'], [source]), components: components };
}
function run(value: Object, source: string = 'real'): RunRecord {
  const o = object(value);
  const latency = o['recovery_latency_ms'];
  check(latency === null || (typeof latency === 'number' && Number.isFinite(latency) && (latency as number) >= 0));
  check(o['success'] === null || typeof o['success'] === 'boolean');
  return { id: id(o['id']), incident_id: id(o['incident_id']), trace_id: id(o['trace_id']),
    source: member(o['source'], [source]), status: member(o['status'], RUN_STATUS),
    case_id: nullableText(o['case_id']), fault_id: nullableText(o['fault_id']),
    started_at: nullableText(o['started_at']), finished_at: nullableText(o['finished_at']),
    model_calls: nullableCount(o['model_calls']), action_count: nullableCount(o['action_count']),
    recovery_latency_ms: latency as number | null, success: o['success'] as boolean | null,
    metadata: object(o['metadata']) };
}
export function decodeRun(raw: string, expectedId: string, source: string = 'real'): RunRecord {
  const result = run(parse(raw), source); check(result.id === expectedId); return result;
}
export function decodeRuns(raw: string, source: string = 'real'): RunPage {
  const o = parse(raw);
  const result: RunPage = { items: array(o['items']).map((item: Object) => run(item, source)),
    total: count(o['total']), limit: count(o['limit']), offset: count(o['offset']) };
  unique(result.items.map((item: RunRecord) => item.id));
  check(result.limit > 0 && result.items.length <= result.limit && (result.items.length === 0 || result.total >= result.offset + result.items.length));
  return result;
}
function event(value: Object, expected: RunRecord): EventRecord {
  const o = object(value);
  const result: EventRecord = {
    event_id: id(o['event_id']), run_id: id(o['run_id']), incident_id: id(o['incident_id']), trace_id: id(o['trace_id']),
    source: member(o['source'], [expected.source]), ordinal: count(o['ordinal']), stage: member(o['stage'], STAGES),
    status: o['status'] === null ? null : member(o['status'], ['started', 'success', 'failed', 'skipped', 'waiting_human']),
    timestamp: nullableText(o['timestamp']), case_id: nullableText(o['case_id']),
    parent_event_id: nullableText(o['parent_event_id']), original_event_id: nullableText(o['original_event_id']),
    origin: member(o['origin'], ['trace_journal', 'decision_trace', 'experience_update', 'workbench_projection']),
    message: text(o['message']), data: object(o['data']) };
  check(result.run_id === expected.id && result.incident_id === expected.incident_id && result.trace_id === expected.trace_id);
  return result;
}
export function decodeEvents(raw: string, expected: RunRecord): EventPage {
  const o = parse(raw);
  const result: EventPage = { run_id: id(o['run_id']), total: count(o['total']),
    items: array(o['items']).map((item: Object) => event(item, expected)) };
  check(result.run_id === expected.id && result.total === result.items.length);
  unique(result.items.map((item: EventRecord) => item.event_id));
  return result;
}
function component(value: Object): ComponentRecord {
  const o = object(value); return { id: id(o['id']), name: id(o['name']), health: member(o['health'], HEALTH) };
}
function target(value: Object): TargetRecord {
  const o = object(value);
  return { id: id(o['id']), name: id(o['name']), runtime: member(o['runtime'], ['process', 'docker', 'windows_service']),
    health: member(o['health'], HEALTH), monitoring: member(o['monitoring'], ['watching', 'paused', 'not_connected']),
    observed_at: nullableText(o['observed_at']), components: array(o['components']).map((item: Object) => component(item)),
    allowed_actions: texts(o['allowed_actions']) };
}
function workbenchEvent(value: Object): WorkbenchEvent {
  const o = object(value);
  return { id: id(o['id']), sequence: count(o['sequence']), timestamp: text(o['timestamp']), stage: member(o['stage'], STAGES),
    status: member(o['status'], ['running', 'succeeded', 'failed', 'skipped', 'waiting_human', 'unknown']),
    title: text(o['title']), detail: text(o['detail']), evidence: texts(o['evidence']) };
}
function modelCall(value: Object): ModelCall {
  const o = object(value); check(o['redacted'] === true);
  return { id: id(o['id']), model: text(o['model']), status: member(o['status'], ['running', 'succeeded', 'failed', 'unknown']),
    request: text(o['request']), response: nullableText(o['response']), duration_ms: nullableCount(o['duration_ms']),
    input_tokens: nullableCount(o['input_tokens']), output_tokens: nullableCount(o['output_tokens']), redacted: true };
}
function verification(value: Object | null): Verification {
  const o = object(value); return { status: member(o['status'], ['passed', 'failed', 'pending', 'unknown']), checks: texts(o['checks']) };
}
function incident(value: Object): IncidentRecord {
  const o = object(value);
  return { id: id(o['id']), target_id: text(o['target_id']), trace_id: id(o['trace_id']), title: text(o['title']),
    started_at: text(o['started_at']), status: member(o['status'], ['observing', 'diagnosing', 'waiting_human',
      'executing', 'verifying', 'recovered', 'failed', 'unknown']),
    diagnosis_source: member(o['diagnosis_source'], ['model', 'experience', 'rule', 'unknown']), summary: text(o['summary']),
    events: array(o['events']).map((item: Object) => workbenchEvent(item)),
    model_calls: array(o['model_calls']).map((item: Object) => modelCall(item)),
    experience_ids: texts(o['experience_ids']), verification: verification(o['verification']) };
}
function experience(value: Object): ExperienceRecord {
  const o = object(value);
  return { id: id(o['id']), target_id: text(o['target_id']), incident_id: text(o['incident_id']), title: text(o['title']),
    symptom: text(o['symptom']), root_cause: text(o['root_cause']), action: text(o['action']), conditions: texts(o['conditions']),
    status: member(o['status'], ['verified', 'failed', 'retired', 'unverified']) };
}
export function decodeSnapshot(raw: string, source: string = 'real'): WorkbenchSnapshot {
  const o = parse(raw);
  const s: WorkbenchSnapshot = { schema_version: member(o['schema_version'], ['0.1']), source: member(o['source'], [source]),
    generated_at: text(o['generated_at']), a_status: member(o['a_status'], ['ready', 'not_connected']),
    b_status: member(o['b_status'], ['ready', 'not_connected']),
    targets: array(o['targets']).map((item: Object) => target(item)),
    incidents: array(o['incidents']).map((item: Object) => incident(item)),
    experiences: array(o['experiences']).map((item: Object) => experience(item)) };
  unique(s.targets.map((item: TargetRecord) => item.id));
  unique(s.incidents.map((item: IncidentRecord) => item.id));
  unique(s.incidents.map((item: IncidentRecord) => item.trace_id));
  unique(s.experiences.map((item: ExperienceRecord) => item.id));
  check(s.a_status !== 'not_connected' || s.targets.length === 0);
  check(s.b_status !== 'not_connected' || (s.incidents.length === 0 && s.experiences.length === 0));
  s.incidents.forEach((item: IncidentRecord) => {
    check(s.targets.some((t: TargetRecord) => t.id === item.target_id));
    check(item.status !== 'recovered' || item.verification.status === 'passed');
    unique(item.events.map((e: WorkbenchEvent) => e.id));
    unique(item.model_calls.map((m: ModelCall) => m.id));
    item.events.forEach((e: WorkbenchEvent, index: number) => check(e.sequence === index));
    check(item.diagnosis_source !== 'experience' || item.experience_ids.length > 0);
    item.experience_ids.forEach((eid: string) => check(s.experiences.some((e: ExperienceRecord) => e.id === eid && e.target_id === item.target_id)));
  });
  s.experiences.forEach((e: ExperienceRecord) => {
    check(s.targets.some((t: TargetRecord) => t.id === e.target_id));
    check(s.incidents.some((i: IncidentRecord) => i.id === e.incident_id && i.target_id === e.target_id
      && (e.status !== 'verified' || i.verification.status === 'passed')));
  });
  return s;
}

const INCIDENT_STATES: string[] = ['observing', 'diagnosing', 'waiting_human', 'executing', 'verifying', 'recovered', 'failed', 'unknown'];
function dateText(value: Object | null): string {
  const result = text(value);
  check(/(Z|[+-]\d{2}:\d{2})$/.test(result) && Number.isFinite(Date.parse(result)));
  return result;
}
function nullableDate(value: Object | null): string | null { return value === null ? null : dateText(value); }
function context(o: JsonObject, source: string): MobileContext {
  return { schema_version: member(o['schema_version'], ['mobile-v1']), source: member(o['source'], [source]),
    generated_at: dateText(o['generated_at']), a_status: member(o['a_status'], ['ready', 'not_connected']),
    b_status: member(o['b_status'], ['ready']) };
}
function summary(value: Object): IncidentSummary {
  const o = object(value); check(o['severity'] === null);
  const result: IncidentSummary = { id: id(o['id']), target_id: text(o['target_id']), trace_id: id(o['trace_id']),
    title: text(o['title']), status: member(o['status'], INCIDENT_STATES), started_at: dateText(o['started_at']),
    updated_at: dateText(o['updated_at']), diagnosis_source: member(o['diagnosis_source'], ['model', 'experience', 'rule', 'unknown']),
    summary: text(o['summary']), severity: null, verification: verification(o['verification']) };
  check(result.status !== 'recovered' || result.verification.status === 'passed');
  return result;
}
export function decodeMobilePage(raw: string, offset: number, limit: number, source: string = 'real'): IncidentPage {
  const o = parse(raw); const c = context(o, source);
  const items = array(o['items']).map((v: Object) => summary(v));
  const total = count(o['total']);
  check(count(o['offset']) === offset && count(o['limit']) === limit && items.length <= limit);
  check(typeof o['has_more'] === 'boolean' && o['has_more'] === (offset + limit < total));
  check(items.length === Math.min(limit, Math.max(0, total - offset)));
  unique(items.map((v: IncidentSummary) => v.id));
  unique(items.map((v: IncidentSummary) => v.trace_id));
  return { schema_version: c.schema_version, source: c.source, generated_at: c.generated_at, a_status: c.a_status, b_status: c.b_status,
    items: items, total: total, limit: limit, offset: offset, has_more: o['has_more'] as boolean,
    since: nullableDate(o['since']), until: nullableDate(o['until']) };
}
function freshTarget(value: Object, threshold: number): FreshTarget {
  const o = object(value); const age = o['age_seconds'];
  check(age === null || (typeof age === 'number' && Number.isFinite(age)));
  const result: FreshTarget = { id: id(o['id']), health: member(o['health'], HEALTH),
    monitoring: member(o['monitoring'], ['watching', 'paused', 'not_connected']),
    observed_at: nullableDate(o['observed_at']), age_seconds: age as number | null,
    freshness: member(o['freshness'], ['fresh', 'stale', 'unavailable']) };
  if (result.freshness === 'fresh') check(result.monitoring === 'watching' && age !== null && (age as number) >= 0 && (age as number) <= threshold && result.observed_at !== null);
  else check(result.health === 'unknown');
  return result;
}
function relatedEvent(value: Object): RelatedEvent {
  const o = object(value); const e = workbenchEvent(value); dateText(e.timestamp);
  return { id: e.id, sequence: e.sequence, timestamp: e.timestamp, stage: e.stage, status: e.status,
    title: e.title, detail: e.detail, evidence: e.evidence, incident_id: id(o['incident_id']), trace_id: id(o['trace_id']) };
}
export function decodeMobileOverview(raw: string, source: string = 'real'): MobileOverview {
  const o = parse(raw); const c = context(o, source); const total = count(o['total']);
  const counts: Record<string, number> = {}; const values = object(o['counts_by_status']);
  let sum: number = 0;
  INCIDENT_STATES.forEach((key: string) => { counts[key] = count(values[key]); sum += counts[key]; });
  check(sum === total);
  const threshold = count(o['freshness_threshold_seconds']); check(threshold === 60);
  const targets = array(o['targets']).map((v: Object) => freshTarget(v, threshold));
  check(c.a_status !== 'not_connected' || targets.length === 0);
  const health = member(o['target_health'], HEALTH);
  const expected = targets.some((t: FreshTarget) => t.health === 'unhealthy') ? 'unhealthy' :
    targets.length > 0 && targets.every((t: FreshTarget) => t.health === 'healthy') ? 'healthy' : 'unknown';
  check(health === expected);
  const recent = array(o['recent_incidents']).map((v: Object) => summary(v));
  const events = array(o['recent_events']).map((v: Object) => relatedEvent(v));
  unique(targets.map((v: FreshTarget) => v.id)); unique(recent.map((v: IncidentSummary) => v.id));
  check(recent.length <= 5 && recent.length <= total && events.length <= 10);
  events.forEach((e: RelatedEvent) => {
    const known = recent.find((i: IncidentSummary) => i.id === e.incident_id);
    if (known) check(known.trace_id === e.trace_id);
  });
  return { schema_version: c.schema_version, source: c.source, generated_at: c.generated_at, a_status: c.a_status, b_status: c.b_status,
    total: total, counts_by_status: counts, since: nullableDate(o['since']), until: nullableDate(o['until']),
    statistics_scope: member(o['statistics_scope'], ['persisted_workbench_incidents_started_at']),
    latest_incident_update_at: nullableDate(o['latest_incident_update_at']), target_health: health,
    freshness_threshold_seconds: threshold, targets: targets, recent_incidents: recent, recent_events: events };
}
function eventSubset(value: Object | null, i: IncidentRecord): WorkbenchEvent[] {
  const events = array(value).map((v: Object) => workbenchEvent(v));
  unique(events.map((e: WorkbenchEvent) => e.id));
  events.forEach((e: WorkbenchEvent) => check(i.events.some((original: WorkbenchEvent) => JSON.stringify(original) === JSON.stringify(e))));
  return events;
}
export function decodeMobileDetail(raw: string, expectedId: string, expectedTrace: string, source: string = 'real'): MobileDetail {
  const o = parse(raw); const c = context(o, source); const i = incident(object(o['incident']));
  check(i.id === expectedId && i.trace_id === expectedTrace && o['severity'] === null);
  dateText(i.started_at);
  unique(i.events.map((e: WorkbenchEvent) => e.id)); unique(i.model_calls.map((m: ModelCall) => m.id));
  i.events.forEach((e: WorkbenchEvent, index: number) => { check(e.sequence === index); dateText(e.timestamp); });
  check(i.status !== 'recovered' || i.verification.status === 'passed');
  const d = object(o['diagnosis']); check(d['diagnosed_at'] === null && d['failure_reason'] === null);
  const diagnosis: MobileDiagnosis = { status: member(d['status'], ['not_started', 'running', 'succeeded', 'failed', 'unavailable']),
    source: text(d['source']), diagnosed_at: null, failure_reason: null,
    calls: array(d['calls']).map((v: Object) => modelCall(v)), evidence_events: eventSubset(d['evidence_events'], i) };
  check(diagnosis.source === i.diagnosis_source && JSON.stringify(diagnosis.calls) === JSON.stringify(i.model_calls));
  check(diagnosis.evidence_events.every((e: WorkbenchEvent) => ['localization', 'root_cause_analysis'].includes(e.stage)));
  const last = diagnosis.calls.length > 0 ? diagnosis.calls[diagnosis.calls.length - 1] : null;
  const expectedStatus = last ? last.status === 'running' || last.status === 'failed' ? last.status :
    last.status === 'succeeded' && (last.response ?? '').trim().length > 0 ? 'succeeded' : 'unavailable' : 'not_started';
  check(diagnosis.status === expectedStatus);
  const knowledge = array(o['knowledge']).map((v: Object) => experience(v));
  unique(knowledge.map((e: ExperienceRecord) => e.id)); unique(i.experience_ids);
  check(knowledge.length === i.experience_ids.length && (i.diagnosis_source !== 'experience' || knowledge.length > 0));
  knowledge.forEach((e: ExperienceRecord) => check(i.experience_ids.includes(e.id) && e.target_id === i.target_id));
  const r = object(o['recovery']);
  const recovery: MobileRecovery = { decision_events: eventSubset(r['decision_events'], i), safety_events: eventSubset(r['safety_events'], i),
    authorization_events: eventSubset(r['authorization_events'], i), execution_events: eventSubset(r['execution_events'], i),
    verification_events: eventSubset(r['verification_events'], i), verification: verification(r['verification']),
    outcome: member(r['outcome'], ['verified', 'failed', 'pending', 'unknown']) };
  check(JSON.stringify(recovery.verification) === JSON.stringify(i.verification));
  check(recovery.decision_events.every((e: WorkbenchEvent) => e.stage === 'recovery_decision'));
  check(recovery.execution_events.every((e: WorkbenchEvent) => e.stage === 'recovery_execution'));
  check(recovery.verification_events.every((e: WorkbenchEvent) => e.stage === 'verification'));
  const outcome = i.status === 'recovered' && i.verification.status === 'passed' ? 'verified' :
    i.verification.status === 'failed' ? 'failed' : i.verification.status === 'pending' ? 'pending' : 'unknown';
  check(recovery.outcome === outcome);
  const links = array(o['runs']).map((value: Object): RunLink => {
    const run = object(value);
    const ids = texts(run['event_ids']); unique(ids);
    check(id(run['incident_id']) === i.id && id(run['trace_id']) === i.trace_id && text(run['source']) === c.source);
    return { run_id: id(run['run_id']), incident_id: i.id, trace_id: i.trace_id, source: c.source, status: text(run['status']), event_ids: ids };
  });
  unique(links.map((run: RunLink) => run.run_id));
  const linkStatus = member(o['run_link_status'], ['matched', 'not_imported', 'unavailable']);
  check((linkStatus === 'matched') === (links.length > 0));
  return { schema_version: c.schema_version, source: c.source, generated_at: c.generated_at, a_status: c.a_status, b_status: c.b_status,
    incident: i, severity: null, updated_at: dateText(o['updated_at']), diagnosis: diagnosis, knowledge: knowledge,
    recovery: recovery, run_link_status: linkStatus, runs: links, gaps: texts(o['gaps']) };
}
