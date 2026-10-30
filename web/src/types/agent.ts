import type { SystemPhase } from './system';

// Mirrors shared/agent_event.schema.json 1.0. View-only metadata belongs in TraceStep.
export type AgentStage = 'observe' | 'failure_detection' | 'localization' | 'root_cause_analysis' | 'recovery_decision' | 'recovery_execution' | 'verification' | 'experience_update';
export interface AgentEvent {
  schema_version: '1.0'; event_id: string; incident_id: string; trace_id: string;
  timestamp: string; stage: AgentStage; status: 'started' | 'success' | 'failed' | 'skipped' | 'waiting_human';
  message: string; data: Record<string, unknown>; parent_event_id?: string | null;
  component?: string | null; step?: string | null; confidence?: number | null;
  observation_id?: string | null; diagnosis_id?: string | null; action_id?: string | null; result_id?: string | null;
}
export interface TraceStep {
  event: AgentEvent; at: number; phase: SystemPhase; title: string; subtitle: string;
  input: string; reason: string; tool: string; result: string;
}
export interface RecoverySnapshot {
  mode: 'simulation' | 'live'; elapsed: number; index: number; phase: SystemPhase; complete: boolean;
  incidentId: string; traceId: string;
}
export interface RecoverySource {
  mode: 'simulation' | 'live';
  subscribe: (onSnapshot: (snapshot: RecoverySnapshot) => void, onError: (error: Error) => void) => () => void;
}
