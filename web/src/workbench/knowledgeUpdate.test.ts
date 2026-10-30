import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {describe,expect,it} from 'vitest';
import {fixtureSnapshot} from './contract';
import {confirmedNewExperiences,knowledgeUpdateGraph,knowledgeUpdateSnapshot} from './knowledgeUpdate';
import {globalKnowledgeGraph} from './knowledgeAtlas';

describe('execution evidence and optional experience in the existing graph',()=>{
  function records(){
    const data=fixtureSnapshot();const incident=data.incidents.find(item=>item.status==='recovered')!;
    const experience=data.experiences.find(item=>item.incident_id===incident.id)!;
    incident.experience_ids=[experience.id];experience.status='verified';incident.verification.status='passed';
    incident.events.push({...incident.events[0],id:'actual-save',stage:'experience_update',status:'succeeded',title:'Actual experience saved'});
    return {data,incident,experience};
  }
  it('retains the original graph and adds execution nodes when no new experience exists',()=>{
    const {data,incident,experience}=records();const current={...incident,id:'new-run',trace_id:'new-trace',experience_ids:[]};
    data.incidents.push({...incident,id:'previous-unlearned-run',trace_id:'previous-unlearned-trace',experience_ids:[]});
    const snapshot=knowledgeUpdateSnapshot(data,current,data);const graph=knowledgeUpdateGraph(snapshot,current,snapshot.experiences);
    expect(graph.nodes.some(node=>node.id===`experience:${experience.id}`)).toBe(true);
    expect(graph.nodes.some(node=>node.id===`incident:${current.id}`)).toBe(true);
    expect(graph.nodes.some(node=>node.id==='incident:previous-unlearned-run')).toBe(true);
    expect(graph.nodes.filter(node=>node.kind==='experience'&&node.incidentId===current.id)).toHaveLength(0);
    expect(graph.edges.some(edge=>edge.from==='library:reops'&&edge.to===`incident:${current.id}`&&edge.label==='execution record')).toBe(true);
  });
  it('adds an experience only with matching verified recovery and succeeded save evidence',()=>{
    const {data,incident,experience}=records();expect(confirmedNewExperiences(data,incident)).toEqual([experience]);
    const snapshot=knowledgeUpdateSnapshot(data,incident);const graph=knowledgeUpdateGraph(snapshot,incident,snapshot.experiences);
    expect(graph.nodes.some(node=>node.id===`experience:${experience.id}`)).toBe(true);
    const ids=new Set(graph.nodes.map(node=>node.id));expect(graph.edges.every(edge=>ids.has(edge.from)&&ids.has(edge.to))).toBe(true);
  });
  it.each(['failed','unverified','retired'] as const)('does not turn a %s record into a new learned experience',status=>{
    const {data,incident,experience}=records();experience.status=status;
    expect(confirmedNewExperiences(data,incident)).toEqual([]);
    expect(knowledgeUpdateSnapshot(data,incident).experiences.some(item=>item.id===experience.id)).toBe(false);
  });
  it('keeps execution and failed-save evidence without a successful experience node',()=>{
    const {data,incident,experience}=records();incident.events=incident.events.filter(event=>event.stage!=='experience_update');
    incident.events.push({...incident.events[0],id:'failed-save',stage:'experience_update',status:'failed'});
    expect(confirmedNewExperiences(data,incident)).toEqual([]);
    const snapshot=knowledgeUpdateSnapshot(data,incident);const graph=knowledgeUpdateGraph(snapshot,incident,snapshot.experiences);
    expect(graph.nodes.some(node=>node.record==='failed-save')).toBe(true);expect(graph.nodes.some(node=>node.id===`experience:${experience.id}`)).toBe(false);
  });
  it('rejects mismatched targets, failed verification and a missing incident experience link',()=>{
    for(const change of ['target','verification','link']){
      const {data,incident,experience}=records();if(change==='target')experience.target_id='another-target';else if(change==='verification')incident.verification.status='failed';else incident.experience_ids=[];
      expect(confirmedNewExperiences(data,incident)).toEqual([]);
    }
  });
  it('keeps an execution without experience in the normal global library, with a bounded record window',()=>{
    const {data,incident}=records();const runs=Array.from({length:60},(_,index)=>({...incident,id:`execution-${index}`,trace_id:`trace-${index}`,experience_ids:[]}));
    const graph=globalKnowledgeGraph(data,[],false,undefined,'',runs);
    expect(graph.nodes.filter(node=>node.kind==='incident')).toHaveLength(50);
    expect(graph.omitted).toBeGreaterThanOrEqual(10);
    expect(graph.nodes.filter(node=>node.kind==='experience'&&node.provenance==='recorded')).toHaveLength(0);
    const ids=new Set(graph.nodes.map(node=>node.id));expect(graph.edges.every(edge=>ids.has(edge.from)&&ids.has(edge.to))).toBe(true);
  });
});
