import { t, useLocale } from '../i18n';
import {useEffect,useRef,useState} from 'react';
import type {Incident} from './contract';

export const conversationProfile='dependency-conversation-v2';
export const liveConversationProfile='dependency-live-conversation-v1';
export function hasLiveConversation(incident:Incident) {
  return incident.model_calls.some(call=>{try{return JSON.parse(call.request).analysis_mode===liveConversationProfile;}catch{return false;}});
}
export function hasAutomaticConversation(incident:Incident) {
  if(hasLiveConversation(incident))return true;
  const latest=incident.model_calls.filter(call=>{try{return JSON.parse(call.request).analysis_mode===conversationProfile;}catch{return false;}}).at(-1);
  return !!latest&&latest.status!=='failed';
}
export function needsLiveAnalysis(incident:Incident) {
  return ['observing','diagnosing','executing','verifying'].includes(incident.status)
    &&incident.target_id==='reops-vikunja-demo'&&incident.events.length>0
    &&incident.events.every(event=>event.evidence.includes('profile=dependency-audit-v1'))
    &&!hasAutomaticConversation(incident);
}
const prefix='/api/v1/researchloop/control';
export function DependencyDiagnosisControl({incident,active,onChanged}:{incident:Incident;active:boolean;onChanged:()=>void}) {
  useLocale();
  const eligible=needsLiveAnalysis(incident);
  const recorded=hasAutomaticConversation(incident);
  const attempted=useRef('');
  const changed=useRef(onChanged);changed.current=onChanged;
  const [message,setMessage]=useState('');
  const [connection,setConnection]=useState<{loaded:boolean|null;verified:boolean|null}>({loaded:null,verified:null});
  useEffect(()=>{
    if(!active||!eligible||recorded)return;
    const abort=new AbortController();let busy=false;
    async function inspect(){
      if(busy||document.hidden)return;busy=true;
      try {
        const [api,cap]=await Promise.all([
          fetch(prefix+'/status',{credentials:'same-origin',cache:'no-store',redirect:'error',signal:abort.signal}),
          fetch(prefix+'/dependency-diagnosis/status',{credentials:'same-origin',cache:'no-store',redirect:'error',signal:abort.signal})]);
        const status=api.ok?await api.json():null;
        const capability=cap.ok?await cap.json():null;
        const verified=status?.model?.verified===true;
        const loaded=capability?.automatic_conversation===true&&capability?.live_conversation===true;
        if(abort.signal.aborted)return;
        setConnection({loaded,verified});
        const binding=incident.id+':live:'+status?.model?.id+':'+status?.model?.revision;
        if(!verified||!loaded||attempted.current===binding||typeof status?.csrf!=='string')return;
        attempted.current=binding;
        setMessage('Reading recorded evidence. Model analysis will appear here…');
        const response=await fetch(prefix+'/dependency-diagnosis/live',{method:'POST',
          credentials:'same-origin',cache:'no-store',redirect:'error',mode:'same-origin',signal:abort.signal,
          headers:{'Content-Type':'application/json','X-ReOps-UI-Token':status.csrf},
          body:JSON.stringify({incident_id:incident.id})});
        if(!response.ok)throw new Error();
        const result=await response.json();
        if(!abort.signal.aborted){setMessage(result.existing?'A model request is already recorded for this incident.':'Analysis started. Incoming replies appear progressively.');changed.current();}
      } catch {
        if(!abort.signal.aborted)setMessage('Model analysis is unavailable. Check the API connection. Refreshing does not repeat a submitted request.');
      } finally {busy=false;}
    }
    void inspect();const timer=window.setInterval(()=>void inspect(),1500);
    document.addEventListener('visibilitychange',inspect);
    return()=>{abort.abort();window.clearInterval(timer);document.removeEventListener('visibilitychange',inspect);};
  },[active,eligible,recorded,incident.id]);
  if(!eligible||recorded)return null;
  return <section className="wb-diagnosis-control execution-auto-analysis" aria-label={t("Automatic model analysis")}>
    <strong>{t("Model analysis")}</strong>
    {connection.loaded===false?<p>{t("Load the updated model analysis service.")}</p>
      :connection.verified===false?<p>{t("Connect and verify an API to enable analysis. ")}<a href="/api">{t("Open API settings →")}</a></p>
      :<p role="status">{t(message||'Connecting to model analysis…')}</p>}
    <small>{t("Analysis follows recovery independently, using new execution and verification evidence.")}</small>
  </section>;
}
