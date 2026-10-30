import type {Incident,Snapshot} from './contract';
import type {KnowledgeGraph,KnowledgeNode} from './knowledge';
import {knowledgeGraph} from './knowledge';
import {globalKnowledgeGraph,incidentKnowledgeGraph,unlearnedExecutionRecords} from './knowledgeAtlas';
import type {KnowledgeRetrieval} from './knowledgeRetrieval';
import {confirmedNewExperiences,knowledgeUpdateGraph} from './knowledgeUpdate';

export type KnowledgeFrame={title:string;ids:string[]};
export type KnowledgeAnimation={graph:KnowledgeGraph;frames:KnowledgeFrame[];existingIds:string[];networkStep:number};

// Camera itinerary over the existing field projection; no second knowledge model.
export function knowledgeAnimation(data:Snapshot,incident:Incident,mode:'lookup'|'update',retrieval?:KnowledgeRetrieval|null):KnowledgeAnimation {
  const root=`incident:${incident.id}`;
  const original=globalKnowledgeGraph(data,data.experiences.filter(e=>e.incident_id!==incident.id),false,undefined,'',unlearnedExecutionRecords(data).filter(i=>i.id!==incident.id));
  let graph=mode==='update'?knowledgeUpdateGraph(data,incident,data.experiences):original;
  const frames:KnowledgeFrame[]=[{title:mode==='lookup'?'Start from the current fault':'Add this execution to the existing graph',ids:[root]}];
  const merge=(extra:KnowledgeGraph)=>{
    // Existing node values, identifiers, source fields and edges take precedence.
    graph={nodes:[...new Map([...extra.nodes,...graph.nodes].map(n=>[n.id,n])).values()],edges:[...new Map([...extra.edges,...graph.edges].map(e=>[`${e.from}:${e.to}`,e])).values()],omitted:graph.omitted+extra.omitted};
  };
  const add=(title:string,nodes:KnowledgeNode[])=>nodes.forEach(n=>frames.push({title,ids:[n.id]}));
  let networkStep=0;
  if(mode==='lookup'){
    const stages=['observe','failure_detection','localization','root_cause_analysis'];
    const evidence=incidentKnowledgeGraph(data,{...incident,experience_ids:[],events:incident.events.filter(e=>stages.includes(e.stage))});
    evidence.nodes=evidence.nodes.filter(n=>n.id===root||n.eventId&&incident.events.some(e=>e.id===n.eventId&&stages.includes(e.stage)));
    const ids=new Set(evidence.nodes.map(n=>n.id));evidence.edges=evidence.edges.filter(e=>ids.has(e.from)&&ids.has(e.to));
    merge(evidence);add('Expand the recorded fault evidence',evidence.nodes.filter(n=>n.id!==root));
    networkStep=frames.length;
    for(const match of retrieval?.status==='hit'&&retrieval.query.target_id===incident.target_id?retrieval.matches:[]){
      const source=data.incidents.find(i=>i.id===match.incident_id&&i.trace_id===match.trace_id&&i.target_id===incident.target_id&&i.events.some(e=>e.id===match.source_event_id));
      const experience=data.experiences.find(e=>e.id===match.experience_id&&e.incident_id===source?.id&&e.target_id===incident.target_id&&match.target_id===incident.target_id);
      if(!source||!experience)continue;
      const history=knowledgeGraph(data,experience,false);
      merge({...history,nodes:history.nodes.map(n=>({...n,provenance:'recorded' as const}))});
      const sourceGraph=incidentKnowledgeGraph(data,source,true);
      const sourceEvent=sourceGraph.nodes.find(n=>n.eventId===match.source_event_id);
      if(sourceEvent)merge({nodes:[sourceEvent],edges:sourceGraph.edges.filter(e=>e.to===sourceEvent.id),omitted:0});
      const memory=`experience:${experience.id}`;
      if(!graph.edges.some(e=>e.from===memory&&e.to===root))graph.edges.push({from:memory,to:root,label:'retrieved for analysis',field:'KnowledgeRetrieval.matches (exact experience/incident/trace/source_event/target)'});
      frames.push({title:'Follow the match into its source experience',ids:[memory]});
      add('Inspect the source diagnosis and conditions',history.nodes.filter(n=>['symptom','cause','action'].includes(n.kind)));
      // Read the compact applicability projection; all remaining conditions stay
      // in this same graph and its source inspector, rather than 24 slow stops.
      const compact=knowledgeGraph(data,experience,false);
      add('Inspect the source applicability conditions',compact.nodes.filter(n=>n.kind==='condition'));
      add('Check the original source and its verification',[...history.nodes.filter(n=>n.kind==='verification'),...(sourceEvent?[sourceEvent]:[])]);
      frames.push({title:'Located the matched experience in the original network',ids:[memory]});
    }
    if(!frames.some(f=>f.title==='Follow the match into its source experience'))frames.push({title:retrieval?.status==='miss'?'No matching experience recorded':retrieval?.status==='hit'?'Matched source is absent from this snapshot':'Knowledge source unavailable',ids:[root]});
  }else{
    const own=graph.nodes.filter(n=>n.incidentId===incident.id&&n.id!==root&&n.kind!=='experience');
    for(const [title,kinds] of [['Attach fault and analysis evidence',['symptom','cause','event']],['Link the recorded recovery actions',['action','condition']],['Attach the actual verification result',['verification']]] as [string,string[]][])add(title,own.filter(n=>kinds.includes(n.kind)));
    add('Connect experience referenced by this execution',graph.edges.filter(e=>e.to===root&&e.from.startsWith('experience:')).map(e=>graph.nodes.find(n=>n.id===e.from)!).filter(Boolean));
    add('Save the verified new experience',graph.nodes.filter(n=>confirmedNewExperiences(data,incident).some(e=>n.id===`experience:${e.id}`)));
    frames.push({title:confirmedNewExperiences(data,incident).length?'Execution and verified experience joined the original network':'Execution joined the original network · no new experience',ids:[root]});
  }
  const ids=new Set(graph.nodes.map(n=>n.id));graph.edges=graph.edges.filter(e=>ids.has(e.from)&&ids.has(e.to));
  return {graph,frames,existingIds:original.nodes.map(n=>n.id),networkStep};
}
