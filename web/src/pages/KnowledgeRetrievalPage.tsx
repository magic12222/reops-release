import { t, useLocale, getLocale } from '../i18n';
import {useEffect,useState} from 'react';
import {ArrowLeft,ArrowUpRight,Network,RefreshCw} from 'lucide-react';
import {useRoute,navigate} from '../navigation/router';
import {readWorkbench,fixtureSnapshot} from '../workbench/contract';
import {lookupCanContinue} from '../workbench/knowledgeRetrieval';
import {useRecoveryNavigation} from '../workbench/recoveryNavigation';
import type {Incident,Snapshot} from '../workbench/contract';
import {KnowledgeRetrievalHandoff} from '../workbench/KnowledgeRetrievalHandoff';
import {KnowledgeExplorer} from '../workbench/KnowledgeExplorer';
import './KnowledgeRetrievalPage.css';
import {KnowledgeUpdate} from '../workbench/KnowledgeUpdateView';
import {createVikunjaClient} from '../workbench/vikunjaClient';
import {liveRecoveryIncidents} from '../workbench/liveRecovery';
import {KnowledgeJourneyStage} from '../workbench/KnowledgeJourneyStage';
import type {KnowledgeRetrieval} from '../workbench/knowledgeRetrieval';

export function KnowledgeRetrievalPage({active=true}:{active?:boolean}) {
  useLocale();
  const route=useRoute();
  const trace=new URLSearchParams(route.href.split('?')[1]??'').get('trace');
  const updating=new URLSearchParams(route.href.split('?')[1]??'').get('view')==='update';
  const sample=new URLSearchParams(route.href.split('?')[1]??'').get('source')==='offline_fixture';
  useRecoveryNavigation();
  const lookup=!!trace&&lookupCanContinue(trace)&&!updating;
  const library=!updating&&!lookup;
  const [data,setData]=useState<Snapshot|null>(null);
  const [loadedHref,setLoadedHref]=useState('');
  const [live,setLive]=useState<Incident[]>([]);
  const [error,setError]=useState(false);
  const [revision,setRevision]=useState(0);
  const [focus,setFocus]=useState<string>();
  const [lookupStage,setLookupStage]=useState(0);
  const [graphReady,setGraphReady]=useState(false);
  const [retrieval,setRetrieval]=useState<KnowledgeRetrieval|null>(null);
  useEffect(()=>{
    if(!active)return;
    if(sample){setData(fixtureSnapshot());setLoadedHref(route.href);setError(false);setLive([]);return;}
    const abort=new AbortController();let busy=false;
    const read=async()=>{
      if(busy||document.hidden)return;busy=true;
      try{const next=await readWorkbench(abort.signal);if(!abort.signal.aborted){setData(next);setLoadedHref(route.href);setError(false);}}
      catch{if(!abort.signal.aborted){setData(null);setError(true);}}
      finally{busy=false;}
    };
    let liveBusy=false;const client=createVikunjaClient();
    const readLive=async()=>{if(liveBusy||document.hidden)return;liveBusy=true;try{const value=await client.status(abort.signal);if(!abort.signal.aborted)setLive(liveRecoveryIncidents(value.automation));}catch{/* Saved snapshot remains independent. */}finally{liveBusy=false;}};
    void read();void readLive();const timer=window.setInterval(()=>{void read();void readLive();},2000);
    return()=>{abort.abort();window.clearInterval(timer);};
  },[active,revision,sample,route.href]);
  useEffect(()=>{setFocus(undefined);setLookupStage(0);setGraphReady(false);setRetrieval(null);},[trace]);
  const incident=data?.incidents.find(item=>item.trace_id===trace)??live.find(item=>item.trace_id===trace&&data?.targets.some(t=>t.id===item.target_id));
  const origin=focus?data?.experiences.find(item=>item.id===focus&&item.target_id===incident?.target_id):undefined;
  return <section className="knowledge-retrieval-page shell" aria-label={t("Knowledge retrieval workspace")}>
    <header className="retrieval-page-heading"><div><a href="/workbench"><ArrowLeft size={13}/>{t("Operations workbench")}</a><h1>{updating ? t('Knowledge update') : library ? t('Knowledge') : t('Experience retrieval')}</h1><p>{updating ? t('Keep the execution. Add new experience only when it is recorded.') : library ? t('Explore the knowledge graph. Select a node to inspect its source.') : t('Follow the lookup, inspect matching evidence, and return to your Agent.')}</p></div>{!library&&<a href="/knowledge-retrieval?source=real"><Network size={15}/>{t("Global knowledge")}<ArrowUpRight size={13}/></a>}</header>
    {!library&&<div className="retrieval-page-toolbar"><label>{t("Recovery run ")}<select aria-label={t("Knowledge retrieval run")} value={trace??''} onChange={event=>navigate('/knowledge-retrieval?source=real&trace='+encodeURIComponent(event.target.value)+(updating?'&view=update':''))}><option value="">{t("Choose an incident")}</option>{trace&&!incident&&<option value={trace}>{t("Requested trace not found")}</option>}{data?.incidents.map(item=><option key={item.id} value={item.trace_id}>{item.title} · {t(new Date(item.started_at).toLocaleTimeString(getLocale(),{timeZone:'Asia/Shanghai',hour12:false}))}</option>)}</select></label><span>{t(incident?.status??'Awaiting selection')}</span><button aria-label={t("Refresh retrieval workspace")} onClick={()=>setRevision(v=>v+1)}><RefreshCw size={14}/></button>{incident&&<a href={`/execution?source=real&trace=${encodeURIComponent(incident.trace_id)}`}>{t("Agent execution")}<ArrowUpRight size={13}/></a>}</div>}
    {error?<div className="retrieval-page-empty" role="alert"><Network size={26}/><h2>{t("Incident feed unavailable")}</h2><p>{t("The current incident could not be read. Historical or sample data has not been substituted.")}</p><button onClick={()=>setRevision(v=>v+1)}>{t("Retry connection")}</button></div>:(!data||loadedHref!==route.href)?<div className="retrieval-page-empty" role="status">{t("Reading incident feed…")}</div>:library?<section className="knowledge-library" aria-label={t("Knowledge library")}><KnowledgeExplorer key={`library:${sample}`} data={data} targetId="" incidentId={null} initiallyUnselected autoIntegrate={false} active={active}
      onIncident={id=>{const origin=data.incidents.find(item=>item.id===id);if(origin)navigate('/execution?source='+data.source+'&trace='+encodeURIComponent(origin.trace_id));}}
      onEvent={(id,event)=>{const origin=data.incidents.find(item=>item.id===id);if(origin)navigate('/agent?source='+data.source+'&feed=workbench&trace='+encodeURIComponent(origin.trace_id)+'&event='+encodeURIComponent(event));}}/></section>:!incident?<div className="retrieval-page-empty"><Network size={26}/><h2>{trace ? t('No exact matching incident') : t('Choose a recovery to inspect')}</h2><p>{trace ? t('The requested trace is not available in this feed. Another recovery has not been selected in its place.') : t('New faults open this page automatically. You can also inspect a recorded recovery.')}</p></div>:<>
      {updating?<KnowledgeUpdate data={data} incident={incident} active={active}/>:<>
      <KnowledgeRetrievalHandoff key={incident.id} incident={incident} active={active} onRetrieved={setFocus} onStage={setLookupStage} onResult={setRetrieval} graphReady={graphReady}/>
      {lookup&&retrieval&&<KnowledgeJourneyStage key={`lookup:${incident.id}`} data={data} incident={incident} mode="lookup" retrieval={retrieval} active={active} onComplete={()=>setGraphReady(true)}/>}
      {!lookup&&<section className="retrieval-source-graph"><header><div><Network size={17}/><h2>{origin ? t('Matched experience & source evidence') : t('Knowledge & source evidence')}</h2></div><p>{focus&&!origin ? t('The referenced source is not present in this snapshot. No replacement source is selected.') : t('Inspect the exact history and its recorded verification.')}</p></header><KnowledgeExplorer autoIntegrate={false} initialScope="all" initiallyUnselected={!origin||lookupStage<2} key={incident.id} data={data} targetId={incident.target_id} incidentId={incident.id} active={active} retrievalExperienceId={origin?.id} onIncident={id=>{const item=data.incidents.find(x=>x.id===id);if(item)navigate('/workbench?source=real&trace='+encodeURIComponent(item.trace_id));}} onEvent={(id,event)=>{const item=data.incidents.find(x=>x.id===id);if(item)navigate('/agent?source=real&feed=workbench&trace='+encodeURIComponent(item.trace_id)+'&event='+encodeURIComponent(event));}}/></section>}
      </>}
    </>}
  </section>;
}
