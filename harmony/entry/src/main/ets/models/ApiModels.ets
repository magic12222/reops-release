// Read models mirror existing Python/JSON contracts; not a new shared/ contract.
export type JsonObject = Record<string, Object | null>;
export type LoadState = 'unconfigured' | 'idle' | 'loading' | 'ready' | 'empty' | 'error';
export interface SystemStatus {
  status: string;
  source: string;
  components: Record<string, string>;
}
export interface RunRecord {
  id: string; incident_id: string; trace_id: string; source: string; status: string;
  case_id: string | null; fault_id: string | null; started_at: string | null; finished_at: string | null;
  model_calls: number | null; action_count: number | null; recovery_latency_ms: number | null;
  success: boolean | null; metadata: JsonObject;
}
export interface RunPage { items: RunRecord[]; total: number; limit: number; offset: number; }
export interface EventRecord {
  event_id: string; run_id: string; incident_id: string; trace_id: string; source: string;
  ordinal: number; stage: string; status: string | null; timestamp: string | null;
  case_id: string | null; parent_event_id: string | null; original_event_id: string | null;
  origin: string; message: string; data: JsonObject;
}
export interface EventPage { run_id: string; items: EventRecord[]; total: number; }
export interface RunLookup { run: RunRecord | null; message: string; }
export interface ComponentRecord { id: string; name: string; health: string; }
export interface TargetRecord {
  id: string; name: string; runtime: string; health: string; monitoring: string;
  observed_at: string | null; components: ComponentRecord[]; allowed_actions: string[];
}
export interface WorkbenchEvent {
  id: string; sequence: number; timestamp: string; stage: string; status: string;
  title: string; detail: string; evidence: string[];
}
export interface ModelCall {
  id: string; model: string; status: string; request: string; response: string | null;
  duration_ms: number | null; input_tokens: number | null; output_tokens: number | null; redacted: boolean;
}
export interface Verification { status: string; checks: string[]; }
export interface IncidentRecord {
  id: string; target_id: string; trace_id: string; title: string; started_at: string;
  status: string; diagnosis_source: string; summary: string; events: WorkbenchEvent[];
  model_calls: ModelCall[]; experience_ids: string[]; verification: Verification;
}
export interface ExperienceRecord {
  id: string; target_id: string; incident_id: string; title: string; symptom: string;
  root_cause: string; action: string; conditions: string[]; status: string;
}
export interface WorkbenchSnapshot {
  schema_version: string; source: string; generated_at: string; a_status: string; b_status: string;
  targets: TargetRecord[]; incidents: IncidentRecord[]; experiences: ExperienceRecord[];
}

// Embedded shared 1.0 payloads remain raw EventRecord.data until their presence
// and schema are checked. These types do not imply standalone HTTP endpoints.
export interface SharedDiagnosis {
  schema_version: string; diagnosis_id: string; incident_id: string; trace_id: string;
  observation_id: string; timestamp: string; case_id?: string | null;
  failure_detected: boolean; failed_component: string | null; failed_step: string | null;
  failure_type: string | null; root_cause: string | null; evidence: string[]; confidence: number;
}
export interface SharedVerification {
  status: string; checked_at: string | null; health_check_passed: boolean | null;
  fault_cleared: boolean | null; business_request_passed: boolean | null; evidence: string[];
}
export interface SharedRecoveryResult {
  schema_version: string; result_id: string; incident_id: string; trace_id: string;
  action_id: string; timestamp: string; case_id?: string | null;
  execution_status: string; exit_code: number | null; stdout: string | null; stderr: string | null;
  duration_ms: number; post_observation_id: string | null; verification: SharedVerification;
}
