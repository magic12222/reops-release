import {useEffect,useRef,useState} from 'react';
import {useRoute} from '../navigation/router';
import {readWorkbench} from './contract';
import {createVikunjaClient} from './vikunjaClient';
import {liveRecoveryIncidents} from './liveRecovery';
import {beginRecoveryAnalysis,cancelRecoveryNavigation,recoveryNavigation,smoothRecoveryNavigate} from './recoveryNavigation';
import {DependencyDiagnosisControl} from './DependencyDiagnosisControl';
import {abandonExperienceLookup} from './knowledgeRetrieval';
import type {Incident} from './contract';

export function LiveAnalysisCoordinator(){
  const route=useRoute();
  const [analysis,setAnalysis]=useState<Incident[]>([]);
  const liveAdmitted=useRef(new Set<string>());
  const seen=useRef(new Set<string>());
  const initialized=useRef({saved:false,live:false});
  const sources=useRef<{records:Incident[];automatic:boolean}>({records:[],automatic:false});
  const client=useRef(createVikunjaClient()).current;
  useEffect(()=>{
    if(!['workbench','execution','knowledge-retrieval'].includes(route.page)||new URLSearchParams(route.href.split('?')[1]??'').get('source')==='offline_fixture')return;
    const abort=new AbortController();let savedBusy=false,liveBusy=false;
    const activeRun=(run:Incident)=>['observing','diagnosing','executing','verifying'].includes(run.status);
    const observe=(runs:Incident[],source:'saved'|'live')=>{
      const ordered=[...runs].sort((a,b)=>Date.parse(a.started_at)-Date.parse(b.started_at));
      for(const run of ordered){
        const fresh=!seen.current.has(run.trace_id);seen.current.add(run.trace_id);
        if(fresh&&initialized.current[source]&&window.location.pathname==='/workbench'){const href=beginRecoveryAnalysis(run.trace_id);if(href)void smoothRecoveryNavigate(()=>href,()=>recoveryNavigation()?.trace===run.trace_id);}
      }
      // An empty successful snapshot is a valid baseline; unavailable reads are not.
      initialized.current[source]=true;
    };
    const syncAnalysis=()=>{
      // Start only the existing approved live analysis, independently of navigation.
      if(sources.current.automatic)sources.current.records.filter(activeRun).forEach(run=>liveAdmitted.current.add(run.trace_id));
      setAnalysis(sources.current.automatic?sources.current.records.filter(run=>liveAdmitted.current.has(run.trace_id)&&activeRun(run)):[]);
    };
    const savedRead=async()=>{
      if(savedBusy||document.hidden)return;savedBusy=true;
      try{const snapshot=await readWorkbench(abort.signal);if(!abort.signal.aborted){sources.current.records=snapshot.incidents;observe(snapshot.incidents,'saved');syncAnalysis();}}
      catch{/* Pages expose their own unavailable state. */}finally{savedBusy=false;}
    };
    const liveRead=async()=>{
      if(liveBusy||document.hidden)return;liveBusy=true;
      try{const value=await client.status(abort.signal);if(!abort.signal.aborted){sources.current.automatic=value.automation.mode==='automatic';observe(liveRecoveryIncidents(value.automation),'live');syncAnalysis();}}
      catch{/* Slow monitor status must not block saved records. */}finally{liveBusy=false;}
    };
    const read=()=>{void savedRead();void liveRead();};read();const timer=setInterval(read,1500);
    return()=>{abort.abort();clearInterval(timer);};
  },[route.page,route.href.includes('offline_fixture'),client]);
  useEffect(()=>{
    const flow=recoveryNavigation();if(!flow||flow.phase==='execution')return;
    const url=new URL(window.location.href);
    const expected=flow.phase==='analysis'?'/execution':'/knowledge-retrieval';
    if(url.pathname!==expected||url.searchParams.get('trace')!==flow.trace){abandonExperienceLookup(flow.trace);cancelRecoveryNavigation();}
  },[route.href]);
  const workers=<div hidden aria-hidden="true">{(!route.href.includes('offline_fixture')?analysis:[]).map(incident=><DependencyDiagnosisControl key={incident.id} incident={incident} active={true} onChanged={()=>{}}/>)}</div>;
  return workers;
}
