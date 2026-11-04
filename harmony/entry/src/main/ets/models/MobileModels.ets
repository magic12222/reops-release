import { IncidentRecord, WorkbenchEvent, ModelCall, Verification, ExperienceRecord } from './ApiModels';

// B 25944ba / shared/harmony-api.md; not a replacement shared contract.
export interface MobileContext {
  schema_version: string; source: string; generated_at: string; a_status: string; b_status: string;
}
export interface IncidentSummary {
  id: string; target_id: string; trace_id: string; title: string; status: string;
  started_at: string; updated_at: string; diagnosis_source: string; summary: string;
  severity: null; verification: Verification;
}
export interface IncidentPage extends MobileContext {
  items: IncidentSummary[]; total: number; limit: number; offset: number; has_more: boolean;
  since: string | null; until: string | null;
}
export interface FreshTarget {
  id: string; health: string; monitoring: string; observed_at: string | null;
  age_seconds: number | null; freshness: string;
}
export interface RelatedEvent extends WorkbenchEvent { incident_id: string; trace_id: string; }
export interface MobileOverview extends MobileContext {
  total: number; counts_by_status: Record<string, number>; since: string | null; until: string | null;
  statistics_scope: string; latest_incident_update_at: string | null; target_health: string;
  freshness_threshold_seconds: number; targets: FreshTarget[];
  recent_incidents: IncidentSummary[]; recent_events: RelatedEvent[];
}
export interface MobileDiagnosis {
  status: string; source: string; diagnosed_at: null; failure_reason: null;
  calls: ModelCall[]; evidence_events: WorkbenchEvent[];
}
export interface MobileRecovery {
  decision_events: WorkbenchEvent[]; safety_events: WorkbenchEvent[];
  authorization_events: WorkbenchEvent[]; execution_events: WorkbenchEvent[];
  verification_events: WorkbenchEvent[]; verification: Verification; outcome: string;
}
export interface RunLink {
  run_id: string; incident_id: string; trace_id: string; source: string; status: string; event_ids: string[];
}
export interface MobileDetail extends MobileContext {
  incident: IncidentRecord; severity: null; updated_at: string; diagnosis: MobileDiagnosis;
  knowledge: ExperienceRecord[]; recovery: MobileRecovery; run_link_status: string; runs: RunLink[]; gaps: string[];
}
