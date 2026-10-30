import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {describe,it,expect} from 'vitest';
import {fixtureSnapshot} from './contract';
import {knowledgeAnimation} from './knowledgeAnimation';
import {knowledgeUpdateSnapshot} from './knowledgeUpdate';
import type {KnowledgeRetrieval} from './knowledgeRetrieval';
import {globalKnowledgeGraph,unlearnedExecutionRecords} from './knowledgeAtlas';

function records(){
  const data=fixtureSnapshot(),origin=data.incidents[0],experience=data.experiences.find(e=>e.incident_id===origin.id)!;
  const current={...structuredClone(origin),id:'new-incident',trace_id:'new-trace',experience_ids:[],model_calls:[]};
  data.incidents.push(current);
  const retrieval:KnowledgeRetrieval={status:'hit',duration_ms:1,started_at:origin.started_at,completed_at:origin.started_at,query:{target_id:current.target_id},matches:[{experience_id:experience.id,incident_id:origin.id,trace_id:origin.trace_id,source_event_id:origin.events[0].id,target_id:origin.target_id,symptom:experience.symptom,action:experience.action,matched_conditions:['same_target'],used_as:'model_context',execution_applied:false}]};
  return {data,origin,current,experience,retrieval};
}
describe('graph animation uses actual evidence paths',()=>{
  it('starts at the current incident, traces an exact recorded match, then inspects the original source',()=>{
    const {data,current,experience,retrieval}=records();const before=JSON.stringify(data);
    const {graph,frames}=knowledgeAnimation(data,current,'lookup',retrieval);
    expect(frames[0].ids).toEqual([`incident:${current.id}`]);
    const matchFrame=frames.findIndex(f=>f.title==='Follow the match into its source experience');
    const evidenceFrame=frames.findIndex(f=>f.title==='Inspect the source diagnosis and conditions');
    expect(matchFrame).toBeGreaterThan(0);expect(evidenceFrame).toBeGreaterThan(matchFrame);
    expect(frames.at(-1)?.ids).toEqual([`experience:${experience.id}`]);
    expect(graph.edges.some(e=>e.from===`experience:${experience.id}`&&e.to===`incident:${current.id}`&&e.label==='retrieved for analysis')).toBe(true);
    expect(graph.nodes.some(n=>n.id.startsWith('lookup:'))).toBe(false);
    expect(graph.nodes.some(n=>n.incidentId===current.id&&n.kind==='action')).toBe(false);
    expect(JSON.stringify(data)).toBe(before);
  });
  it.each(['source','target','trace','miss','unavailable'])('never substitutes a fabricated source for %s',failure=>{
    const {data,current,retrieval}=records();
    if(failure==='source')retrieval.matches[0].source_event_id='missing';
    if(failure==='trace')retrieval.matches[0].trace_id='other-trace';
    if(failure==='target')retrieval.matches[0].target_id=current.target_id='other-target';
    if(failure==='miss'||failure==='unavailable'){retrieval.status=failure;retrieval.matches=[];}
    const plan=knowledgeAnimation(data,current,'lookup',retrieval);
    expect(plan.frames.some(f=>f.title==='Follow the match into its source experience')).toBe(false);
    expect(plan.graph.edges.some(e=>e.to===`incident:${current.id}`&&e.label==='retrieved for analysis')).toBe(false);
  });
  it('keeps failed execution and its save receipt separate from verified learning',()=>{
    const {data,current}=records();current.status='failed';current.verification.status='failed';
    current.events.push({...current.events[0],id:'save-failure-record',stage:'experience_update',status:'succeeded'});
    const snapshot=knowledgeUpdateSnapshot(data,current);const plan=knowledgeAnimation(snapshot,current,'update');
    expect(plan.graph.nodes.some(n=>n.record==='save-failure-record')).toBe(true);
    expect(plan.frames.at(-1)?.title).toContain('no new experience');
    expect(plan.graph.edges.some(e=>e.from==='library:reops'&&e.to===`incident:${current.id}`)).toBe(true);
    expect(plan.graph.nodes.some(n=>n.kind==='experience'&&n.incidentId===current.id)).toBe(false);
  });
  it.each(['lookup','update'] as const)('retains every original node value and edge in the %s camera itinerary',mode=>{
    const {data,current,retrieval}=records();
    const original=globalKnowledgeGraph(data,data.experiences.filter(e=>e.incident_id!==current.id),false,undefined,'',unlearnedExecutionRecords(data).filter(i=>i.id!==current.id));
    const {graph,frames}=knowledgeAnimation(data,current,mode,retrieval);
    for(const node of original.nodes)expect(graph.nodes.find(n=>n.id===node.id)).toEqual(node);
    for(const edge of original.edges)expect(graph.edges).toContainEqual(edge);
    expect(new Set(graph.nodes.map(n=>n.id)).size).toBe(graph.nodes.length);
    for(const frame of frames)for(const id of frame.ids)expect(graph.nodes.some(n=>n.id===id)).toBe(true);
  });
});
