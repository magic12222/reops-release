import type { Experience, Incident, Snapshot } from './contract';
import {retrievedReferences} from './knowledgeRetrieval';
import { knowledgeGraph } from './knowledge';
import { translate } from '../i18n';
import type { KnowledgeGraph, KnowledgeNode, NodeKind } from './knowledge';

// Product knowledge, versioned separately from runtime incidents, metrics and audit.
export const knowledgeEdition = 'reops-starter-v1';
export const domains = [
  { id: 'dependency', label: 'Database & dependencies', match: /postgres|database|dependency|sql|数据库/i },
  { id: 'service', label: 'Services & containers', match: /service|container|api|服务|容器/i },
  { id: 'network', label: 'Network & connectivity', match: /network|connection|dns|timeout|网络|连接/i },
  { id: 'validation', label: 'Business verification', match: /business|verify|verification|业务|验证/i },
];
export const starterKnowledge = [
  { id: 'postgres-startup', topic: 'dependency', title: 'Recover after database readiness', symptom: 'Application cannot connect to its database', cause: 'Database exits before application initialization completes', action: 'Wait for SQL readiness, then start the application within its approved scope', verify: 'SQL read and business request both pass', conditions: 'Dependency identity matches; current Safety and Gate apply' },
  { id: 'postgres-readiness', topic: 'dependency', title: 'Container state and SQL readiness', symptom: 'Container is running while SQL remains unavailable', cause: 'Database startup or transaction recovery is still in progress', action: 'Wait for readiness within a bounded window', verify: 'Read the business object after the SQL probe passes', conditions: 'Bound the wait; escalate for inspection on timeout' },
  { id: 'service-stopped', topic: 'service', title: 'Start a stopped service', symptom: 'Service probe is unreachable', cause: 'The target service has stopped', action: 'Start the target using the allowlisted executor', verify: 'Consecutive fresh business checks', conditions: 'Bind the exact target, scope and action budget' },
  { id: 'restart-boundary', topic: 'service', title: 'Keep recovery scope minimal', symptom: 'A component failure affects business requests', cause: 'Evidence localizes the fault to the target component', action: 'Execute only the currently approved recovery action', verify: 'Verify target generation and business object identity', conditions: 'Block execution without approval or after identity changes' },
  { id: 'connection-refused', topic: 'network', title: 'Locate connection refusal', symptom: 'connection refused', cause: 'The target port is not accepting connections', action: 'Inspect dependency state and port ownership first', verify: 'Validate connectivity and business requests separately', conditions: 'A log fragment alone does not confirm the root cause' },
  { id: 'timeout-boundary', topic: 'network', title: 'Preserve unknown outcomes', symptom: 'Request timed out; execution outcome is unknown', cause: 'The transport did not confirm the final result', action: 'Keep the outcome unknown and inspect existing evidence', verify: 'Read fresh state and original audit records', conditions: 'Do not replay writes whose outcome is unknown' },
  { id: 'fresh-checks', topic: 'validation', title: 'Close the loop with fresh checks', symptom: 'Process is restored; business state still needs verification', cause: 'Infrastructure state does not establish business success', action: 'Perform two independent fresh business reads', verify: 'Both pass with the same business object identity', conditions: 'Retain the verification window and observation IDs' },
  { id: 'memory-reuse', topic: 'validation', title: 'Recheck conditions before reuse', symptom: 'A fault resembles a historical incident', cause: 'Similar symptoms can occur under different conditions', action: 'Recommend experience after matching scope and conditions', verify: 'Current Safety, Gate and business verification', conditions: 'Historical success does not authorize current execution' },
] as const;

export function savedExperienceEvent(data: Snapshot, experience: Experience) {
  return data.incidents.find(item => item.id === experience.incident_id && item.target_id === experience.target_id)
    ?.events.find(event => event.stage === 'experience_update' && event.status === 'succeeded');
}
export function savedExperiences(data: Snapshot) {
  return data.experiences.filter(item => savedExperienceEvent(data, item));
}
export function unlearnedExecutionRecords(data:Snapshot,query='',targetId='',status='all'){
  const linked=new Set(savedExperiences(data).map(item=>item.incident_id));
  return data.incidents.filter(item=>!linked.has(item.id)&&['recovered','failed','unknown'].includes(item.status)
    &&item.events.some(event=>['recovery_execution','verification'].includes(event.stage))
    &&(!targetId||item.target_id===targetId)&&(status==='all'||status==='failed'&&item.status==='failed')
    &&`${item.title} ${item.summary} ${item.id} ${item.trace_id}`.toLowerCase().includes(query.toLowerCase()));
}

export function incidentKnowledgeGraph(data: Snapshot, incident: Incident, expanded = false): KnowledgeGraph {
  const own = data.experiences.filter(item => item.incident_id === incident.id && item.target_id === incident.target_id);
  const nodes = new Map<string, KnowledgeNode>();
  const edges: KnowledgeGraph['edges'] = [];
  const root = `incident:${incident.id}`;
  let omitted = 0;
  nodes.set(root, { id: root, kind: 'incident', label: incident.title, value: incident.summary,
    record: incident.id, field: 'Incident.id + trace_id', incidentId: incident.id, column: 0, provenance: 'recorded' });
  own.forEach(experience => {
    const graph = knowledgeGraph(data, experience, expanded); omitted += graph.omitted;
    graph.nodes.filter(node => node.incidentId === incident.id).forEach(node => nodes.set(node.id, { ...node, provenance: 'recorded' }));
    edges.push(...graph.edges.filter(edge => nodes.has(edge.from) && nodes.has(edge.to)));
  });
  data.experiences.filter(item => item.target_id === incident.target_id && item.incident_id !== incident.id && (incident.experience_ids.includes(item.id)||retrievedReferences(incident).some(ref=>ref.experience_id===item.id&&ref.incident_id===item.incident_id&&data.incidents.some(origin=>origin.id===ref.incident_id&&origin.trace_id===ref.trace_id&&origin.events.some(event=>event.id===ref.source_event_id))))).forEach(experience => {
    const id = `experience:${experience.id}`;
    nodes.set(id, { id, kind: 'experience', label: experience.title, value: experience.status, record: experience.id,
      field: 'Incident.experience_ids', incidentId: experience.incident_id, column: 1, provenance: 'recorded' });
    edges.push({ from: id, to: root, label: incident.diagnosis_source === 'experience' ? 'reused by' : retrievedReferences(incident).some(ref=>ref.experience_id===experience.id)?'retrieved for analysis':'referenced by', field: 'Incident.experience_ids or ModelCall.request.knowledge_retrieval (exact source reference)' });
  });
  const eventKinds: Partial<Record<Incident['events'][number]['stage'], NodeKind>> = {
    observe: 'symptom', failure_detection: 'symptom', localization: 'event', root_cause_analysis: 'event',
    recovery_execution: 'action', verification: 'verification', experience_update: 'event',
  };
  const eligible = incident.events.filter(event => eventKinds[event.stage]);
  // Keep all stage categories in the compact view, rather than only the first events.
  const shown = expanded ? eligible.slice(0, 64) : [...new Map(eligible.map(event => [event.stage, event])).values()];
  omitted += eligible.length - shown.length;
  shown.forEach(event => {
    const id = `event:${incident.id}:${event.id}`;
    nodes.set(id, { id, kind: eventKinds[event.stage]!, label: event.title, value: `${event.status}\n${event.detail}\n${event.evidence.join('\n')}`,
      record: event.id, field: `Incident.events[id=${event.id}] · ${event.stage}`, eventId: event.id,
      incidentId: incident.id, column: event.stage === 'experience_update' ? 3 : 2, provenance: 'recorded' });
    if (!edges.some(edge => edge.from === root && edge.to === id)) edges.push({ from: root, to: id, label: event.stage, field: 'Incident.events' });
  });
  if (!own.length) {
    const id = `${root}:verification`;
    nodes.set(id, { id, kind: 'verification', label: `Business verification · ${incident.verification.status}`, value: incident.verification.checks.join('\n'),
      record: incident.id, field: 'Incident.verification', incidentId: incident.id, column: 2, provenance: 'recorded' });
    edges.push({ from: root, to: id, label: 'checked', field: 'Incident.verification' });
  }
  return { nodes: [...nodes.values()], edges: [...new Map(edges.map(edge => [`${edge.from}:${edge.to}`, edge])).values()], omitted };
}

export function globalKnowledgeGraph(data: Snapshot, experiences: Experience[], expanded = false, focusExperienceId?: string, query = '', executionRecords:Incident[]=[]): KnowledgeGraph {
  const nodes: KnowledgeNode[] = [{ id: 'library:reops', kind: 'library', label: 'ReOps experience network', value: knowledgeEdition,
    record: knowledgeEdition, field: 'Product knowledge edition', incidentId: '', column: 0, provenance: 'curated' }];
  const edges: KnowledgeGraph['edges'] = [];
  const link = (from: string, to: string, label: string, field: string) => edges.push({ from, to, label, field });
  domains.forEach(domain => {
    nodes.push({ id: `topic:${domain.id}`, kind: 'topic', label: domain.label, value: 'Knowledge topic; association does not establish identical causality or executed recovery',
      record: `${knowledgeEdition}/domains/${domain.id}`, field: 'Curated taxonomy', incidentId: '', column: 1, topic: domain.id, provenance: 'curated' });
    link('library:reops', `topic:${domain.id}`, 'knowledge domain', 'Curated taxonomy');
  });
  starterKnowledge.forEach(entry => {
    if (!Object.values(entry).flatMap(value => [value, translate(value, 'zh-CN'), translate(value, 'en')]).join(' ').toLowerCase().includes(query.toLowerCase())) return;
    const id = `starter:${entry.id}`;
    nodes.push({ id, kind: 'experience', label: entry.title,
      value: `Symptom: ${entry.symptom}\nCause conditions: ${entry.cause}\nSuggested action: ${entry.action}\nVerification: ${entry.verify}\nConditions: ${entry.conditions}`,
      record: `${knowledgeEdition}/${entry.id}`, field: 'Product starter knowledge', incidentId: '', column: 2, topic: entry.topic, provenance: 'curated' });
    link(`topic:${entry.topic}`, id, 'includes', 'StarterKnowledge.topic');
  });
  const principles = [
    { id: 'sql-ready', label: 'SQL readiness', kind: 'condition' as const, value: 'Verify dependent business reads after SELECT 1 succeeds', entries: ['postgres-startup', 'postgres-readiness'] },
    { id: 'scope-bound', label: 'Target & scope identity', kind: 'condition' as const, value: 'Check target identity, generation and current authorization before recovery', entries: ['service-stopped', 'restart-boundary', 'memory-reuse'] },
    { id: 'fresh-business', label: 'Fresh business checks', kind: 'verification' as const, value: 'Retain business reads separately from infrastructure probes', entries: ['postgres-startup', 'connection-refused', 'fresh-checks'] },
    { id: 'known-outcome', label: 'Traceable outcomes', kind: 'condition' as const, value: 'Do not replay writes with unknown outcomes; retain the original audit', entries: ['timeout-boundary', 'memory-reuse'] },
  ];
  principles.forEach(principle => {
    const entries = principle.entries.filter(entry => nodes.some(node => node.id === `starter:${entry}`));
    if (!entries.length) return;
    const id = `principle:${principle.id}`;
    nodes.push({ id, kind: principle.kind, label: principle.label, value: principle.value,
      record: `${knowledgeEdition}/${principle.id}`, field: 'StarterKnowledge.principles', incidentId: '', column: 2, provenance: 'curated' });
    entries.forEach(entry => link(`starter:${entry}`, id, 'requires', 'Curated knowledge prerequisite'));
  });
  let omitted = Math.max(0, experiences.length - 200);
  experiences.slice(0, 200).forEach(experience => {
    if (!savedExperienceEvent(data, experience)) return;
    const graph = knowledgeGraph(data, experience, expanded);
    let evidenceId: string | undefined;
    if (experience.id === focusExperienceId) {
      const origin = data.incidents.find(item => item.id === experience.incident_id)!;
      const evidence = origin.events.filter(event => ['localization', 'root_cause_analysis'].includes(event.stage));
      const event = evidence.at(-1);
      if (event) {
        evidenceId = `event:${origin.id}:${event.id}`;
        graph.nodes.push({ id: evidenceId, kind: 'event', label: event.title,
          value: `${event.status}\n${event.detail}\n${event.evidence.join('\n')}`, record: event.id,
          field: 'Incident.events · diagnosis evidence', eventId: event.id, incidentId: origin.id, column: 2 });
      }
    }
    const shown = graph.nodes.filter(node => experience.id !== focusExperienceId ? node.id === `experience:${experience.id}`
      : expanded || ['incident', 'experience', 'symptom', 'cause', 'action', 'verification'].includes(node.kind) || node.id === evidenceId);
    const ids = new Set(shown.map(node => node.id));
    const text = `${experience.symptom} ${experience.root_cause} ${experience.action}`;
    const topic = domains.find(domain => domain.match.test(text))?.id;
    shown.forEach(node => nodes.push({ ...node, provenance: 'recorded', topic }));
    if (experience.id === focusExperienceId) {
      const chain = shown.filter(node => node.incidentId === experience.incident_id).sort((a, b) => integrationRank(a) - integrationRank(b));
      chain.forEach((node, index) => {
        if (index) link(chain[index - 1].id, node.id, node.kind === 'experience' ? 'saved as' : 'evidence chain', 'Experience fields + origin Incident.events (presentation sequence)');
      });
    } else edges.push(...graph.edges.filter(edge => ids.has(edge.from) && ids.has(edge.to)));
    link('library:reops', `experience:${experience.id}`, 'saved experience', 'Experience.id + succeeded experience_update');
    if (topic) link(`experience:${experience.id}`, `topic:${topic}`, 'related topic', 'Curated taxonomy keyword rule v1: symptom/root_cause/action');
    omitted += graph.omitted + graph.nodes.length - shown.length;
  });
  const executions=[...executionRecords].sort((a,b)=>Date.parse(b.started_at)-Date.parse(a.started_at));
  omitted+=Math.max(0,executions.length-50);
  executions.slice(0,50).forEach(incident=>{
    const id=`incident:${incident.id}`;
    nodes.push({id,kind:'incident',label:incident.title,value:`${incident.status}\n${incident.summary}`,record:incident.id,
      field:'Snapshot.incidents.id + trace_id; execution evidence without a saved experience',incidentId:incident.id,column:0,provenance:'recorded'});
    link('library:reops',id,'execution record','Snapshot.incidents.id + trace_id');
  });
  return { nodes: [...new Map(nodes.map(node => [node.id, node])).values()],
    edges: [...new Map(edges.map(edge => [`${edge.from}:${edge.to}`, edge])).values()], omitted };
}

export const integrationStages = ['Locate incident origin', 'Reveal failure symptoms', 'Link diagnostic evidence', 'Connect recovery action', 'Attach business checks', 'Integrate into global knowledge'] as const;
export function integrationRank(node: KnowledgeNode) {
  return ({ incident: 0, symptom: 1, cause: 2, event: 2, action: 3, condition: 3, verification: 4, experience: 5, topic: 5, library: 5 })[node.kind];
}

// Positions depend on the complete graph, never the current animation frame.
export function atlasPositions(graph: KnowledgeGraph) {
  const positions = new Map<string, { x: number; y: number }>();
  positions.set('library:reops', { x: 560, y: 200 });
  ['sql-ready', 'scope-bound', 'fresh-business', 'known-outcome'].forEach((id, index) => positions.set(`principle:${id}`, { x: 560, y: [60, 130, 270, 340][index] }));
  const centers = [{ x: 200, y: 110 }, { x: 920, y: 110 }, { x: 200, y: 310 }, { x: 920, y: 310 }];
  domains.forEach((domain, index) => {
    const center = centers[index]; positions.set(`topic:${domain.id}`, center);
    graph.nodes.filter(node => node.provenance === 'curated' && node.kind === 'experience' && node.topic === domain.id)
      .forEach((node, row) => positions.set(node.id, { x: center.x, y: center.y + (row === 0 ? -65 : 65) }));
  });
  const recorded = graph.nodes.filter(node => node.provenance === 'recorded');
  const origins = [...new Set(recorded.map(node => node.incidentId))];
  const focus = origins.find(origin => recorded.filter(node => node.incidentId === origin).length > 1);
  const group = recorded.filter(node => node.incidentId === focus).sort((a, b) => integrationRank(a) - integrationRank(b));
  group.forEach((node, row) => positions.set(node.id, { x: 120 + (row % 5) * 220, y: 480 + Math.floor(row / 5) * 84 }));
  const offset = group.length ? 480 + Math.ceil(group.length / 5) * 84 + 24 : 480;
  recorded.filter(node => node.incidentId !== focus).forEach((node, row) => positions.set(node.id, { x: 120 + (row % 5) * 220, y: offset + Math.floor(row / 5) * 84 }));
  return { positions, height: Math.max(660, ...[...positions.values()].map(p => p.y + 64)) };
}
