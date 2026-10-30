import {useSyncExternalStore} from 'react';
import {navigate} from '../navigation/router';
import type {Incident,ModelCall,Snapshot} from './contract';

type Position={window:number;timeline:number;dialogue:number};
type RecoveryNavigation={trace:string;phase:'analysis'|'lookup'|'execution'|'update';position?:Position};
let current:RecoveryNavigation|null=null;
const baselines=new Map<string,Snapshot>();
export function captureRecoveryBaseline(trace:string,data:Snapshot){
  if(current?.trace!==trace||baselines.has(trace))return;
  baselines.set(trace,data);if(baselines.size>8)baselines.delete(baselines.keys().next().value!);
}
export const recoveryBaseline=(trace:string)=>baselines.get(trace);
const listeners=new Set<()=>void>();
const emit=()=>listeners.forEach(listener=>listener());
export const recoveryNavigation=()=>current;
export function useRecoveryNavigation(){return useSyncExternalStore(listener=>{listeners.add(listener);return()=>{listeners.delete(listener);};},recoveryNavigation,()=>null);}
export function beginRecoveryAnalysis(trace:string){
  if(current&&current.trace!==trace&&!['execution','update'].includes(current.phase))return null;
  if(current?.trace===trace)return null;
  current={trace,phase:'analysis'};emit();
  return `/execution?source=real&trace=${encodeURIComponent(trace)}`;
}
export function markRecoveryLookup(trace:string,position?:Position){
  if(current?.trace===trace){current={...current,phase:'lookup',position:position??current.position};emit();}
}
export function finishRecoveryLookup(trace:string){
  if(current?.trace===trace&&current.phase==='lookup'){current={...current,phase:'execution'};emit();}
}
export function beginRecoveryKnowledgeUpdate(trace:string){
  if(current?.trace===trace&&current.phase==='execution'){current={...current,phase:'update'};emit();}
  return `/knowledge-retrieval?source=real&trace=${encodeURIComponent(trace)}&view=update`;
}
export function cancelRecoveryNavigation(){current=null;emit();}
export function initialAnalysisCall(incident:Incident):ModelCall|undefined{
  return incident.model_calls.find(call=>{
    try{const request=JSON.parse(call.request);return request.phase==='diagnosis'||(!request.phase&&(!request.round||request.round===1));}
    catch{return false;}
  });
}

let navigating=false;
// Animate only navigation. No calls, actions or evidence are delayed or replayed.
export async function smoothRecoveryNavigate(href:()=>string,allowed:()=>boolean=()=>true){
  if(navigating||!allowed())return;
  navigating=true;const from=window.location.href;
  const page=document.querySelector<HTMLElement>('[data-page]:not([hidden])');
  let animation:Animation|undefined;
  try{
    if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches&&page?.animate){
      animation=page.animate([{opacity:1,transform:'translateY(0)'},{opacity:0,transform:'translateY(-4px)'}],{duration:140,easing:'ease-out',fill:'forwards'});
      await animation.finished.catch(()=>{});
    }
    if(allowed()&&window.location.href===from)navigate(href());
  }finally{animation?.cancel();navigating=false;}
}
