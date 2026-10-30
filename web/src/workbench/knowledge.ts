import type { Experience, Incident, Snapshot } from './contract';
import {retrievedReferences} from './knowledgeRetrieval';

export type NodeKind = 'incident' | 'experience' | 'symptom' | 'cause' | 'action' | 'condition' | 'verification' | 'event' | 'library' | 'topic';
export interface KnowledgeNode {
  id: string; kind: NodeKind; label: string; value: string; record: string; field: string;
  incidentId: string; eventId?: string; column: number;
  provenance?: 'curated' | 'recorded'; topic?: string;
}
export interface KnowledgeEdge { from: string; to: string; label: string; field: string }
export interface KnowledgeGraph { nodes: KnowledgeNode[]; edges: KnowledgeEdge[]; omitted: number }
export const kindLabels: Record<NodeKind, string> = {
  incident: 'Incident', experience: 'Experience', symptom: 'Symptom', cause: 'Root cause', action: 'Recovery action',
  condition: 'Condition', verification: 'Verification', event: 'Source event',
  library: 'Knowledge library', topic: 'Knowledge domain',
};

// Field projections, never entity extraction from prose. Equal text does not merge facts.
export function knowledgeGraph(data: Snapshot, experience: Experience, expanded = false): KnowledgeGraph {
  const origin = data.incidents.find(item => item.id === experience.incident_id && item.target_id === experience.target_id);
  if (!origin) return { nodes: [], edges: [], omitted: 0 };
  const nodes: KnowledgeNode[] = [];
  const edges: KnowledgeEdge[] = [];
  const memory = `experience:${experience.id}`;
  const add = (node: KnowledgeNode, from?: string, label?: string) => {
    nodes.push(node);
    if (from) edges.push({ from, to: node.id, label: label!, field: node.field });
  };
  add({ id: `incident:${origin.id}`, kind: 'incident', label: origin.title, value: origin.summary, record: origin.id,
    field: 'Experience.incident_id', incidentId: origin.id, column: 0 });
  add({ id: memory, kind: 'experience', label: experience.title, value: experience.status, record: experience.id,
    field: 'Experience.incident_id', incidentId: origin.id, column: 1 }, `incident:${origin.id}`, 'produced');
  for (const [key, kind] of [['symptom', 'symptom'], ['root_cause', 'cause'], ['action', 'action']] as const) {
    if (!experience[key].trim()) continue;
    add({ id: `${memory}:${key}`, kind, label: experience[key], value: experience[key], record: experience.id,
      field: `Experience.${key}`, incidentId: origin.id, column: 2 }, memory, 'records');
  }
  const indexed = experience.conditions.map((value, index) => ({value,index}));
  const technical = /^(scope|conditions|target|source_event|memory_event|report_sha256|source|original_b_agent_closed_loop)=/;
  const ordered = [...indexed.filter(item => !technical.test(item.value)), ...indexed.filter(item => technical.test(item.value))];
  const conditions = ordered.slice(0, expanded ? 24 : 2);
  conditions.forEach(({value, index}) => add({ id: `${memory}:condition:${index}`, kind: 'condition', label: value,
    value, record: experience.id, field: `Experience.conditions[${index}]`, incidentId: origin.id, column: 2 }, memory, 'requires'));
  add({ id: `${memory}:verification`, kind: 'verification', label: `Business verification · ${origin.verification.status}`,
    value: origin.verification.checks.join('\n') || 'No check details recorded', record: origin.id,
    field: 'Incident.verification', incidentId: origin.id, column: 2 }, memory, 'origin checked');
  // Only exact source_event references present in the origin's event list qualify.
  const eventIds = new Set(experience.conditions.filter(value => value.startsWith('source_event=')).map(value => value.slice(13)));
  const sourceEvents = origin.events.filter(event => eventIds.has(event.id));
  const events = sourceEvents.slice(0, expanded ? 16 : 4);
  events.forEach(event => add({ id: `event:${origin.id}:${event.id}`, kind: 'event', label: event.title, value: event.detail,
    record: event.id, field: 'Experience.conditions[source_event] → Incident.events.id', incidentId: origin.id,
    eventId: event.id, column: 0 }, `incident:${origin.id}`, 'source event'));
  const references = data.incidents.filter(item => item.target_id === experience.target_id && item.id !== origin.id && (item.experience_ids.includes(experience.id)||retrievedReferences(item).some(ref=>ref.experience_id===experience.id&&ref.incident_id===origin.id&&ref.trace_id===origin.trace_id&&origin.events.some(event=>event.id===ref.source_event_id))));
  const shown = references.slice(0, expanded ? 40 : 6);
  shown.forEach(item => add({ id: `incident:${item.id}`, kind: 'incident', label: item.title,
    value: `${item.diagnosis_source === 'experience' ? 'Experience diagnosis' : 'Recorded reference'}\n${item.summary}`,
    record: item.id, field: 'Incident.experience_ids + diagnosis_source', incidentId: item.id, column: 3 }, memory,
    item.diagnosis_source === 'experience' ? 'reused by' : retrievedReferences(item).some(ref=>ref.experience_id===experience.id)?'retrieved for analysis':'referenced by'));
  return { nodes, edges, omitted: experience.conditions.length - conditions.length + references.length - shown.length + sourceEvents.length - events.length };
}

export function reusedBy(data: Snapshot, experience: Experience): Incident[] {
  return data.incidents.filter(item => item.target_id === experience.target_id && item.id !== experience.incident_id
    && item.diagnosis_source === 'experience' && item.experience_ids.includes(experience.id));
}

export function knowledgeLibraryGraph(data: Snapshot, experiences: Experience[], expanded = false): KnowledgeGraph {
  const nodes = new Map<string, KnowledgeNode>();
  const edges = new Map<string, KnowledgeEdge>();
  let omitted = 0;
  for (const experience of experiences.slice(0, 200)) {
    const graph = knowledgeGraph(data, experience, expanded);
    const visible = graph.nodes.filter(node => expanded || ['incident','experience','action','verification'].includes(node.kind));
    const ids = new Set(visible.map(node => node.id));
    visible.forEach(node => nodes.set(node.id, node));
    graph.edges.filter(edge => ids.has(edge.from) && ids.has(edge.to)).forEach(edge => edges.set(`${edge.from}:${edge.to}`, edge));
    omitted += graph.omitted + graph.nodes.length - visible.length;
  }
  omitted += Math.max(0, experiences.length - 200);
  return {nodes:[...nodes.values()],edges:[...edges.values()],omitted};
}

export function neighborhood(graph: KnowledgeGraph, id: string, depth: number): Set<string> {
  const result = new Set([id]);
  let frontier = new Set([id]);
  for (let step = 0; step < depth; step++) {
    const next = new Set<string>();
    for (const edge of graph.edges) {
      if (frontier.has(edge.from) && !result.has(edge.to)) next.add(edge.to);
      if (frontier.has(edge.to) && !result.has(edge.from)) next.add(edge.from);
    }
    next.forEach(value => result.add(value)); frontier = next;
  }
  return result;
}

// Undirected navigation along recorded edges; the UI retains the original arrows.
export function evidencePath(graph: KnowledgeGraph, start: string, end: string): string[] {
  const parents = new Map<string, string | null>([[start, null]]);
  const queue = [start];
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index];
    if (id === end) {
      const path = [id]; let previous = parents.get(id);
      while (previous) { path.unshift(previous); previous = parents.get(previous); }
      return path;
    }
    for (const edge of graph.edges) {
      const next = edge.from === id ? edge.to : edge.to === id ? edge.from : null;
      if (next && !parents.has(next)) { parents.set(next, id); queue.push(next); }
    }
  }
  return [];
}
