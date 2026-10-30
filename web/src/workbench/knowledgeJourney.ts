import type { Incident, Snapshot } from './contract';
import { savedExperienceEvent } from './knowledgeAtlas';

export const knowledgeSpeeds = [1000, 2200, 3600] as const;
const speedKey = 'reops.knowledge-playback-speed';
export function readKnowledgeSpeed() {
  try { const value = Number(sessionStorage.getItem(speedKey)); return knowledgeSpeeds.some(speed => speed === value) ? value : 2200; }
  catch { return 2200; }
}
export function rememberKnowledgeSpeed(value: number) {
  if (!knowledgeSpeeds.some(speed => speed === value)) return;
  try { sessionStorage.setItem(speedKey, String(value)); } catch { /* Preference persistence is optional. */ }
}

export interface KnowledgeJourney { traceId: string; experienceId: string; eventId: string }
export function readyKnowledgeJourney(data: Snapshot | null, incident: Incident | undefined): KnowledgeJourney | null {
  if (!data || data.source !== 'real' || !incident || incident.status !== 'recovered' || incident.verification.status !== 'passed') return null;
  const experience = data.experiences.find(item => item.incident_id === incident.id && item.target_id === incident.target_id
    && incident.experience_ids.includes(item.id) && item.status === 'verified');
  const event = experience && savedExperienceEvent(data, experience);
  return experience && event ? { traceId: incident.trace_id, experienceId: experience.id, eventId: event.id } : null;
}

// Only recoveries actually followed in progress may trigger automatic navigation.
// Historical snapshots, page refresh and returning to a completed run stay readable.
export function createKnowledgeCompletionFollower() {
  const followed = new Set<string>();
  const shown = new Set<string>();
  return {
    observe(incident: Incident | undefined, enabled: boolean) {
      if (enabled && incident && ['observing', 'diagnosing', 'waiting_human', 'executing', 'verifying'].includes(incident.status)) followed.add(incident.trace_id);
    },
    eligible(journey: KnowledgeJourney | null) { return !!journey && followed.has(journey.traceId) && !shown.has(journey.traceId); },
    complete(journey: KnowledgeJourney) { shown.add(journey.traceId); },
  };
}

export function knowledgeConversationSettled(incident: Incident) {
  if (incident.model_calls.some(call => call.status === 'running')) return false;
  const live = incident.model_calls.filter(call => {
    try { return JSON.parse(call.request).analysis_mode === 'dependency-live-conversation-v1'; } catch { return false; }
  });
  if (!live.length) return true;
  if(['recovered','failed','unknown'].includes(incident.status)&&['failed','unknown'].includes(live.at(-1)!.status))return true;
  // Preserve the final real conversation before leaving Execution, including a
  // terminal failure/unknown result. Never invent a missing verification round.
  return live.some(call => {
    try { return JSON.parse(call.request).phase === 'verification' && call.status !== 'running'; } catch { return false; }
  });
}

// In-memory handoff: a reload clears the pending presentation and never replays
// writes or redirects. The original experience is already saved by the backend.
let pending: (KnowledgeJourney & { token: string }) | null = null;
export function beginKnowledgeJourney(journey: KnowledgeJourney) {
  pending = { ...journey, token: crypto.randomUUID() };
  return `/workbench?source=real&knowledge=record&trace=${encodeURIComponent(journey.traceId)}&integration=${pending.token}`;
}
export function takeKnowledgeJourney(data: Snapshot, token: string | null): KnowledgeJourney | null {
  if (!pending || !token || pending.token !== token) return null;
  const incident = data.incidents.find(item => item.trace_id === pending!.traceId);
  const ready = readyKnowledgeJourney(data, incident);
  if (!ready || ready.eventId !== pending.eventId || ready.experienceId !== pending.experienceId) return null;
  const result = pending; pending = null; return result;
}
