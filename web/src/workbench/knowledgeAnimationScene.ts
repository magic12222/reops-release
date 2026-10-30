import type {KnowledgeAnimation} from './knowledgeAnimation';
import type {KnowledgeGraph} from './knowledge';

// Presentation-only filter: the complete original graph stays in the plan.
// During playback keep the current branch; restore all history in the last frame.
export function knowledgeAnimationScene(plan:KnowledgeAnimation,incidentId:string,step:number,selected?:string,showAll=false):KnowledgeGraph {
  if(showAll||step>=plan.frames.length-1)return plan.graph;
  const revealed=new Set(plan.frames.slice(0,step+1).flatMap(frame=>frame.ids));
  const focus=plan.graph.nodes.find(node=>node.id===(selected??plan.frames[step]?.ids[0]));
  const activeOrigin=focus?.incidentId||incidentId;
  const nodes=plan.graph.nodes.filter(node=>{
    if(!node.incidentId||node.provenance==='curated')return true;
    if(node.id===selected||node.id===`incident:${incidentId}`)return true;
    if(node.incidentId===incidentId)return revealed.has(node.id);
    return node.incidentId===activeOrigin&&(node.kind==='experience'||node.kind==='incident'||revealed.has(node.id));
  });
  const ids=new Set(nodes.map(node=>node.id));
  return {nodes,edges:plan.graph.edges.filter(edge=>ids.has(edge.from)&&ids.has(edge.to)),omitted:plan.graph.omitted};
}

export const graphAnimationRates=[2,4,8] as const;
const preference='reops.knowledge-journey-rate';
export function readGraphAnimationRate(){
  try{const value=Number(sessionStorage.getItem(preference));return graphAnimationRates.some(rate=>rate===value)?value:4;}
  catch{return 4;}
}
export function rememberGraphAnimationRate(value:number){
  if(!graphAnimationRates.some(rate=>rate===value))return;
  try{sessionStorage.setItem(preference,String(value));}catch{/* Optional display preference. */}
}
