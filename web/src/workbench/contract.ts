import schema from '../../../workbench/snapshot.schema.json';
import example from '../../../workbench/example.snapshot.json';

type Health = 'healthy' | 'unhealthy' | 'unknown';
export interface Target {
  id: string; name: string; runtime: 'process' | 'docker' | 'windows_service'; health: Health;
  monitoring: 'watching' | 'paused' | 'not_connected'; observed_at: string | null;
  components: { id: string; name: string; health: Health }[]; allowed_actions: string[];
}
export interface WorkbenchEvent {
  id: string; sequence: number; timestamp: string;
  stage: 'observe' | 'failure_detection' | 'localization' | 'root_cause_analysis' | 'recovery_decision' | 'recovery_execution' | 'verification' | 'experience_update';
  status: 'running' | 'succeeded' | 'failed' | 'skipped' | 'waiting_human' | 'unknown';
  title: string; detail: string; evidence: string[];
}
export interface ModelCall {
  id: string; model: string; status: 'running' | 'succeeded' | 'failed' | 'unknown';
  request: string; response: string | null; duration_ms: number | null;
  input_tokens: number | null; output_tokens: number | null; redacted: true;
}
export interface Incident {
  id: string; target_id: string; trace_id: string; title: string; started_at: string;
  status: 'observing' | 'diagnosing' | 'waiting_human' | 'executing' | 'verifying' | 'recovered' | 'failed' | 'unknown';
  diagnosis_source: 'model' | 'experience' | 'rule' | 'unknown'; summary: string;
  events: WorkbenchEvent[]; model_calls: ModelCall[]; experience_ids: string[];
  verification: { status: 'passed' | 'failed' | 'pending' | 'unknown'; checks: string[] };
}
export interface Experience {
  id: string; target_id: string; incident_id: string; title: string; symptom: string;
  root_cause: string; action: string; conditions: string[]; status: 'verified' | 'failed' | 'retired' | 'unverified';
}
export interface Snapshot {
  schema_version: '0.1'; source: 'real' | 'offline_fixture'; generated_at: string;
  a_status: 'not_connected' | 'ready'; b_status: 'not_connected' | 'ready';
  targets: Target[]; incidents: Incident[]; experiences: Experience[];
}

type Rule = { $ref?: string; anyOf?: Rule[]; const?: unknown; enum?: unknown[]; type?: string;
  properties?: Record<string, Rule>; required?: string[]; additionalProperties?: boolean;
  items?: Rule; minLength?: number; minimum?: number };
const definitions = schema.$defs as Record<string, Rule>;
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);

// Validate the generated Python JSON Schema at the browser boundary as well.
function valid(value: unknown, rule: Rule): boolean {
  if (rule.$ref) return valid(value, definitions[rule.$ref.split('/').at(-1)!]);
  if (rule.anyOf) return rule.anyOf.some(item => valid(value, item));
  if ('const' in rule && value !== rule.const) return false;
  if (rule.enum && !rule.enum.includes(value)) return false;
  if (rule.type === 'null') return value === null;
  if (rule.type === 'string') return typeof value === 'string' && value.length >= (rule.minLength ?? 0);
  if (rule.type === 'boolean') return typeof value === 'boolean';
  if (rule.type === 'integer' || rule.type === 'number') return typeof value === 'number' && Number.isFinite(value)
    && (rule.type !== 'integer' || Number.isInteger(value)) && value >= (rule.minimum ?? -Infinity);
  if (rule.type === 'array') return Array.isArray(value) && value.every(item => valid(item, rule.items!));
  if (rule.type === 'object') return object(value) && (rule.required ?? []).every(key => key in value)
    && Object.entries(value).every(([key, item]) => rule.properties?.[key] ? valid(item, rule.properties[key]) : rule.additionalProperties !== false);
  return true;
}
const unique = (items: { id: string }[]) => new Set(items.map(item => item.id)).size === items.length;

export function parseSnapshot(value: unknown, source: Snapshot['source']): Snapshot {
  if (!valid(value, schema as Rule)) throw new Error('workbench_invalid_snapshot');
  const data = value as Snapshot;
  const targets = new Set(data.targets.map(item => item.id));
  const experiences = new Map(data.experiences.map(item => [item.id, item]));
  const incidents = new Map(data.incidents.map(item => [item.id, item]));
  if (data.source !== source || !unique(data.targets) || !unique(data.incidents) || !unique(data.experiences)
    || (data.a_status === 'not_connected' && data.targets.length > 0)
    || (data.b_status === 'not_connected' && (data.incidents.length > 0 || data.experiences.length > 0))
    || data.incidents.some(item => !targets.has(item.target_id) || !unique(item.events) || !unique(item.model_calls)
      || item.events.some((event, index) => event.sequence !== index)
      || item.experience_ids.some(id => !experiences.has(id) || experiences.get(id)?.target_id !== item.target_id)
      || (item.diagnosis_source === 'experience' && item.experience_ids.length === 0)
      || (item.status === 'recovered' && item.verification.status !== 'passed'))
    || data.experiences.some(item => !targets.has(item.target_id) || !incidents.has(item.incident_id)
      || incidents.get(item.incident_id)?.target_id !== item.target_id
      || (item.status === 'verified' && incidents.get(item.incident_id)?.verification.status !== 'passed'))) {
    throw new Error('workbench_correlation_mismatch');
  }
  return data;
}

export function fixtureSnapshot(): Snapshot {
  return parseSnapshot(structuredClone(example), 'offline_fixture');
}

export async function readWorkbench(signal?: AbortSignal, fetcher = fetch): Promise<Snapshot> {
  const response = await fetcher('/api/v1/workbench/snapshot', {
    method: 'GET', cache: 'no-store', credentials: 'omit', redirect: 'error', signal,
  });
  if (!response.ok) throw new Error('workbench_unavailable');
  return parseSnapshot(await response.json(), 'real');
}
