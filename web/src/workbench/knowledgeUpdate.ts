import type {Incident,Snapshot} from './contract';
import type {KnowledgeGraph} from './knowledge';
import {globalKnowledgeGraph,incidentKnowledgeGraph,savedExperienceEvent,unlearnedExecutionRecords} from './knowledgeAtlas';

export function confirmedNewExperiences(data:Snapshot,incident:Incident){
  return data.experiences.filter(experience=>incident.status==='recovered'&&incident.verification.status==='passed'
    &&experience.incident_id===incident.id&&experience.target_id===incident.target_id
    &&incident.experience_ids.includes(experience.id)&&experience.status==='verified'&&savedExperienceEvent(data,experience));
}
export function knowledgeUpdateSnapshot(data:Snapshot,incident:Incident,baseline=data):Snapshot{
  const confirmed=confirmedNewExperiences(data,incident);
  return {...data,incidents:[...baseline.incidents.filter(item=>item.id!==incident.id),incident],
    experiences:[...baseline.experiences.filter(item=>item.incident_id!==incident.id),...confirmed]};
}
export function knowledgeUpdateGraph(data:Snapshot,incident:Incident,experiences:Snapshot['experiences'],expanded=false,query='',executionRecords=unlearnedExecutionRecords(data,query)):KnowledgeGraph{
  const previous=globalKnowledgeGraph(data,experiences.filter(item=>item.incident_id!==incident.id),expanded,undefined,query,executionRecords.filter(item=>item.id!==incident.id));
  const execution=incidentKnowledgeGraph(data,incident,expanded);
  const nodes=[...new Map([...previous.nodes,...execution.nodes].map(node=>[node.id,node])).values()];
  const ids=new Set(nodes.map(node=>node.id));
  const edges=[...previous.edges,...execution.edges,{from:'library:reops',to:`incident:${incident.id}`,label:'execution record',field:'Snapshot.incidents.id + trace_id; separate from saved Experience'}];
  return {nodes,edges:[...new Map(edges.filter(edge=>ids.has(edge.from)&&ids.has(edge.to)).map(edge=>[`${edge.from}:${edge.to}`,edge])).values()],omitted:previous.omitted+execution.omitted};
}
