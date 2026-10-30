import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { fixtureSnapshot } from './contract';
import { evidencePath, knowledgeGraph, knowledgeLibraryGraph, neighborhood, reusedBy } from './knowledge';
import { incidentFlow } from './IncidentFlow';
import { KnowledgeExplorer } from './KnowledgeExplorer';
import { globalKnowledgeGraph, incidentKnowledgeGraph, integrationRank, savedExperiences, starterKnowledge } from './knowledgeAtlas';

describe('field-backed recovery knowledge', () => {
  it('opts Workbench into refined geometry without changing other explorer consumers',()=>{
    const data=fixtureSnapshot();const props={data,targetId:data.targets[0].id,incidentId:data.incidents[0].id,onIncident:()=>{},onEvent:()=>{}};
    const workbench=renderToStaticMarkup(<KnowledgeExplorer {...props} workbench/>);
    const other=renderToStaticMarkup(<KnowledgeExplorer {...props}/>);
    expect(workbench).toContain('kg-workbench');expect(workbench).toContain('View options');
    expect(workbench).toMatch(/disabled=""[^>]*aria-pressed="false"[^>]*title="Show the recorded path/);
    expect(other).not.toContain('kg-workbench');expect(other).not.toContain('View options');
  });
  it('keeps an unestablished root cause and complete source audit in the Workbench inspector',()=>{
    const data=fixtureSnapshot();data.experiences[0].root_cause='Root cause not established by this audit';
    const html=renderToStaticMarkup(<KnowledgeExplorer workbench data={data} targetId={data.targets[0].id} incidentId={data.incidents[0].id} onIncident={()=>{}} onEvent={()=>{}}/>);
    expect(html).toContain('Root cause not established by this audit');
    expect(html).toContain('Original source text');expect(html).toContain('Complete experience');
  });
  it('keeps complete source values and relationships inside closed disclosures', () => {
    const data=fixtureSnapshot();
    data.experiences[0].action='Long actual action '.repeat(50)+'retain-the-tail';
    data.experiences[0].conditions.push('passed=false;check=0');
    const before=JSON.stringify(data);
    const html=renderToStaticMarkup(<KnowledgeExplorer data={data} targetId={data.targets[0].id} incidentId={data.incidents[0].id} onIncident={()=>{}} onEvent={()=>{}}/>);
    expect(html).toContain('Recorded verification');
    expect(html).toContain('More relationships');
    expect(html).toContain('retain-the-tail');
    expect(html).toContain('passed=false;check=0');
    expect(html).toMatch(/<details class="kg-complete-record"><summary>Conditions &amp; complete record/);
    expect(JSON.stringify(data)).toBe(before);
  });
  it('combines the whole library by record IDs without inferring shared causes',()=>{
    const data=fixtureSnapshot();
    data.experiences.push({...data.experiences[0],id:'separate-experience',incident_id:data.incidents[1].id,status:'unverified'});
    const graph=knowledgeLibraryGraph(data,data.experiences,true);
    expect(graph.nodes.filter(node=>node.kind==='experience')).toHaveLength(data.experiences.length);
    expect(new Set(graph.nodes.map(node=>node.id)).size).toBe(graph.nodes.length);
    expect(graph.edges.some(edge=>edge.from==='experience:separate-experience'&&edge.to===`experience:${data.experiences[0].id}`)).toBe(false);
    const empty=knowledgeLibraryGraph(data,[]);expect(empty.nodes).toHaveLength(0);
  });
  it('uses real field references for every edge and never invents a source event', () => {
    const data = fixtureSnapshot();
    const graph = knowledgeGraph(data, data.experiences[0]);
    const ids = new Set(graph.nodes.map(node => node.id));
    expect(ids.size).toBe(graph.nodes.length);
    expect(graph.edges.every(edge => ids.has(edge.from) && ids.has(edge.to) && edge.field.length > 0)).toBe(true);
    expect(graph.nodes.some(node => node.kind === 'event')).toBe(false);
    expect(graph.edges.filter(edge => edge.label === 'reused by')).toHaveLength(1);
    data.incidents[1].diagnosis_source = 'rule';
    expect(reusedBy(data, data.experiences[0])).toHaveLength(0);
    expect(knowledgeGraph(data, data.experiences[0]).edges.some(edge => edge.label === 'referenced by')).toBe(true);
  });
  it('accepts only exact source events within the origin incident', () => {
    const data = fixtureSnapshot();
    data.experiences[0].conditions.push(`source_event=${data.incidents[0].events[0].id}`, `source_event=${data.incidents[1].events[0].id}`, 'source_event=missing');
    const graph = knowledgeGraph(data, data.experiences[0]);
    expect(graph.nodes.filter(node => node.kind === 'event').map(node => node.record)).toEqual([data.incidents[0].events[0].id]);
    const source = graph.nodes.find(node => node.kind === 'event')!;
    const cause = graph.nodes.find(node => node.kind === 'cause')!;
    expect(evidencePath(graph, source.id, cause.id)).toHaveLength(4);
    expect(neighborhood(graph, cause.id, 1).size).toBe(2);
    expect(evidencePath(graph, source.id, 'unrecorded')).toEqual([]);
  });
  it('bounds expansion with a thousand related incidents and conditions', () => {
    const data = fixtureSnapshot(); const memory = data.experiences[0];
    memory.conditions = Array.from({ length: 1000 }, (_, index) => `condition=${index}`);
    data.incidents = [data.incidents[0], ...Array.from({ length: 1000 }, (_, index) => ({ ...data.incidents[1], id: `large-${index}`, trace_id: `trace-${index}` }))];
    const start = performance.now();
    const graph = knowledgeGraph(data, memory, true);
    expect(graph.nodes.length).toBeLessThanOrEqual(70);
    expect(graph.omitted).toBe(1936);
    expect(graph.edges.filter(edge => edge.label === 'reused by')).toHaveLength(40);
    expect(performance.now() - start).toBeLessThan(250);
  });
  it('keeps missing B runtime data empty while independently showing the product starter library', () => {
    const data = fixtureSnapshot(); data.source = 'real'; data.b_status = 'not_connected'; data.experiences = []; data.incidents = [];
    const html = renderToStaticMarkup(<KnowledgeExplorer data={data} targetId={data.targets[0].id} incidentId={null} onIncident={() => {}} onEvent={() => {}} />);
    expect(html).toContain('ReOps starter library');
    expect(html).not.toContain('SAMPLE GRAPH');
    expect(html).not.toContain('View source incident');
    expect(data.experiences).toEqual([]);
    expect(globalKnowledgeGraph(data, []).nodes.filter(node => node.provenance === 'recorded')).toEqual([]);
  });
});

describe('incident and global knowledge integration', () => {
  it('keeps stable curated IDs and provenance without creating runtime or success records', () => {
    const data = fixtureSnapshot(); const before = JSON.stringify(data);
    const graph = globalKnowledgeGraph(data, data.experiences);
    expect(graph.nodes.filter(node => node.id.startsWith('starter:'))).toHaveLength(starterKnowledge.length);
    expect(graph.nodes.filter(node => node.provenance === 'curated').every(node => !node.incidentId && node.record.startsWith('reops-starter-v1'))).toBe(true);
    expect(JSON.stringify(data)).toBe(before);
    expect(globalKnowledgeGraph(data, data.experiences)).toEqual(graph);
  });
  it('only integrates experiences after a succeeded save event and preserves failures', () => {
    const data = fixtureSnapshot(); const experience = data.experiences[0];
    const origin = data.incidents.find(item => item.id === experience.incident_id)!;
    origin.events = origin.events.filter(item => item.stage !== 'experience_update');
    expect(savedExperiences(data).some(item => item.id === experience.id)).toBe(false);
    expect(globalKnowledgeGraph(data, [experience]).nodes.some(node => node.record === experience.id)).toBe(false);
    const event = { ...origin.events[0], id: 'save-1', stage: 'experience_update' as const, status: 'running' as const };
    origin.events.push(event);
    expect(savedExperiences(data).some(item => item.id === experience.id)).toBe(false);
    origin.events[origin.events.length - 1].status = 'succeeded'; experience.status = 'failed';
    const graph = globalKnowledgeGraph(data, [experience, experience], false, experience.id);
    expect(graph.nodes.filter(node => node.id === `experience:${experience.id}`)).toHaveLength(1);
    expect(graph.nodes.find(node => node.record === experience.id)?.value).toBe('failed');
    expect(new Set(graph.edges.map(edge => `${edge.from}:${edge.to}`)).size).toBe(graph.edges.length);
  });
  it('builds a graph for an unsaved incident using actual trace events and pending verification', () => {
    const data = fixtureSnapshot(); const incident = data.incidents[0]; data.experiences = [];
    incident.verification.status = 'pending';
    const graph = incidentKnowledgeGraph(data, incident);
    expect(graph.nodes.some(node => node.kind === 'experience')).toBe(false);
    expect(graph.nodes.find(node => node.kind === 'verification' && node.field === 'Incident.verification')?.label).toContain('pending');
    expect(graph.nodes.every(node => node.incidentId === incident.id)).toBe(true);
    expect(graph.nodes.filter(node => node.eventId).every(node => incident.events.some(event => event.id === node.eventId))).toBe(true);
  });
  it('reveals evidence and relationships in order, linking the saved experience at the last step', () => {
    const data = fixtureSnapshot(); const experience = data.experiences[0]; const origin = data.incidents[0];
    origin.events.push({ ...origin.events[0], id: 'save', stage: 'experience_update', status: 'succeeded' });
    const graph = globalKnowledgeGraph(data, [experience], false, experience.id);
    const own = graph.nodes.filter(node => node.incidentId === origin.id);
    const counts = Array.from({length:6}, (_, step) => own.filter(node => integrationRank(node) <= step).length);
    expect(counts[0]).toBe(1); expect(counts[1]).toBeGreaterThan(counts[0]); expect(counts[5]).toBeGreaterThan(counts[4]);
    expect(graph.edges.some(edge => edge.from === `experience:${experience.id}` && edge.to.startsWith('topic:'))).toBe(true);
    for (let step = 0; step < 6; step++) {
      const ids = new Set(graph.nodes.filter(node => !node.incidentId || integrationRank(node) <= step).map(node => node.id));
      const visible = graph.edges.filter(edge => ids.has(edge.from) && ids.has(edge.to));
      if (step < 5) expect(visible.some(edge => edge.from === `experience:${experience.id}`)).toBe(false);
    }
  });
  it('searches starter knowledge and keeps every graph endpoint valid', () => {
    const data = fixtureSnapshot(); const graph = globalKnowledgeGraph(data, [], false, undefined, 'SQL');
    expect(graph.nodes.filter(node => node.id.startsWith('starter:')).length).toBeGreaterThan(0);
    expect(graph.nodes.filter(node => node.id.startsWith('starter:')).length).toBeLessThan(starterKnowledge.length);
    const ids = new Set(graph.nodes.map(node => node.id));
    expect(graph.edges.every(edge => ids.has(edge.from) && ids.has(edge.to))).toBe(true);
  });
});

describe('incident evidence coverage', () => {
  it('does not infer Safety or a consumed grant from successful recovery', () => {
    const data = fixtureSnapshot();
    const flow = incidentFlow(data, data.targets[0], data.incidents[0]);
    expect(flow).toHaveLength(11);
    expect(flow.find(step => step.id === 'safety')?.state).toBe('unknown');
    expect(flow.find(step => step.id === 'authorize')?.state).toBe('unknown');
    expect(flow.find(step => step.id === 'monitor')?.fact).toContain('not linked to this incident');
  });
  it('distinguishes default-disabled waiting from explicit A consumption', () => {
    const data = fixtureSnapshot(); const incident = data.incidents[0];
    incident.events.push({ ...incident.events[0], id: 'safety', title: 'safety_and_target_policy_passed', stage: 'recovery_decision', status: 'succeeded' },
      { ...incident.events[0], id: 'disabled', title: 'recovery_disabled_by_default', stage: 'recovery_decision', status: 'waiting_human' });
    expect(incidentFlow(data, data.targets[0], incident).find(step => step.id === 'authorize')?.state).toBe('waiting_human');
    incident.events.push({ ...incident.events[0], id: 'consumed', title: 'a_original_result_and_consumption_retained', stage: 'recovery_execution', status: 'succeeded', evidence: ['authorization_consumed_by_a=true'] });
    const flow = incidentFlow(data, data.targets[0], incident);
    expect(flow.find(step => step.id === 'authorize')?.events[0].id).toBe('consumed');
    expect(flow.find(step => step.id === 'safety')?.state).toBe('succeeded');
  });
});
