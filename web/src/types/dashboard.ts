import type { AgentStage } from './agent';

export type Provenance = 'real' | 'offline_fixture' | 'simulation';
export type RunStatus = 'unknown' | 'pending' | 'observing' | 'diagnosing' | 'waiting_authorization' | 'executing' | 'verifying' | 'recovered' | 'failed' | 'inconclusive';
export type ComponentStatus = 'healthy' | 'unhealthy' | 'unknown' | 'unavailable';

export interface RunRecord {
  id: string; incident_id: string; trace_id: string; case_id: string | null; fault_id: string | null;
  source: Provenance; status: RunStatus; started_at: string | null; finished_at: string | null;
  model_calls: number | null; action_count: number | null; recovery_latency_ms: number | null;
  success: boolean | null; metadata: Record<string, unknown>;
}

export interface EventRecord {
  event_id: string; run_id: string; incident_id: string; trace_id: string; case_id: string | null;
  ordinal: number; parent_event_id: string | null; stage: AgentStage;
  status: 'started' | 'success' | 'failed' | 'skipped' | 'waiting_human' | null;
  timestamp: string | null; message: string; source: Provenance;
  origin: 'trace_journal' | 'decision_trace' | 'experience_update' | 'workbench_projection';
  original_event_id: string | null; data: Record<string, unknown>;
}

export interface SystemStatus {
  status: 'healthy' | 'degraded' | 'unknown' | 'unavailable'; source: 'real';
  components: Record<'api' | 'postgres' | 'redis' | 'users' | 'control', ComponentStatus>;
}

export interface RunPage { items: RunRecord[]; total: number; limit: number; offset: number }
export interface EventPage { run_id: string; items: EventRecord[]; total: number }
