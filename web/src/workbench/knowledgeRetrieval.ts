import type {Incident,ModelCall} from './contract';
import {markRecoveryLookup,finishRecoveryLookup,recoveryNavigation,cancelRecoveryNavigation} from './recoveryNavigation';

export interface RetrievedExperience {experience_id:string;incident_id:string;trace_id:string;source_event_id:string;target_id:string;symptom:string;action:string;source_started_at?:string;root_cause?:string;matched_conditions?:string[];used_as:'model_context';execution_applied:false}
export interface KnowledgeRetrieval {status:'hit'|'miss'|'unavailable';duration_ms:number;started_at:string;completed_at:string;query:{target_id:string};matches:RetrievedExperience[]}
export function knowledgeRetrieval(call:ModelCall):KnowledgeRetrieval|null {
  try {
    const request=JSON.parse(call.request),value=request.knowledge_retrieval;
    return parseKnowledgeRetrieval(value,request.trace_id);
  } catch {return null;}
}
export function parseKnowledgeRetrieval(value:any,trace:string):KnowledgeRetrieval|null {
  try {
    if(value?.profile!=='dependency-knowledge-retrieval-v1'||!['hit','miss','unavailable'].includes(value.status)
      ||value.trace_id!==trace||!value.query||typeof value.query.target_id!=='string'
      ||!Number.isFinite(value.duration_ms)||value.duration_ms<0||!Array.isArray(value.matches)||value.matches.length>2
      ||!value.matches.every((m:RetrievedExperience)=>m&&['experience_id','incident_id','trace_id','source_event_id','target_id','symptom','action'].every(k=>typeof (m as unknown as Record<string,unknown>)[k]==='string')&&m.used_as==='model_context'&&m.execution_applied===false&&m.target_id===value.query.target_id))return null;
    return value;
  } catch {return null;}
}
export function retrievedReferences(incident:Incident) {
  return incident.model_calls.flatMap(call=>{
    const result=knowledgeRetrieval(call);
    return result?.status==='hit'&&result.query.target_id===incident.target_id?result.matches:[];
  });
}

const pendingLookups=new Set<string>();
export function beginExperienceLookup(trace:string) {
  pendingLookups.add(trace);
  markRecoveryLookup(trace);
  return '/knowledge-retrieval?source=real&trace='+encodeURIComponent(trace);
}
export function lookupCanContinue(trace:string){return pendingLookups.has(trace);}
export function completeExperienceLookup(trace:string){pendingLookups.delete(trace);finishRecoveryLookup(trace);}
export function abandonExperienceLookup(trace:string){
  pendingLookups.delete(trace);
  if(recoveryNavigation()?.trace===trace&&recoveryNavigation()?.phase==='lookup')cancelRecoveryNavigation();
}

export function retrievalFailure(status:number) {
  if(status===404)return {title:'Knowledge service needs an update',message:'The running configuration service does not expose this retrieval endpoint. Load the updated service, then retry.'};
  if(status===409)return {title:'Incident record is not available',message:'This exact incident could not be read by the knowledge service. Check record synchronization, then retry.'};
  if(status===408)return {title:'Knowledge request timed out',message:'The service did not respond in time. Retry when the connection is available.'};
  return {title:'Knowledge connection unavailable',message:'The retrieval response could not be read or validated. No experience match or Agent context is claimed.'};
}
