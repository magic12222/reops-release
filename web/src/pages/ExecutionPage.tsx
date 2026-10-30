import { t, useLocale, getLocale } from '../i18n';
import {useEffect,useLayoutEffect,useState,useRef} from 'react';
import {Activity,ArrowLeft,ArrowUpRight,ChevronDown,MessagesSquare,RefreshCw,Workflow} from 'lucide-react';
import {createVikunjaClient} from '../workbench/vikunjaClient';
import {liveRecoveryIncidents} from '../workbench/liveRecovery';
import type {Incident} from '../workbench/contract';
import {readWorkbench,fixtureSnapshot} from '../workbench/contract';
import type {Snapshot,WorkbenchEvent} from '../workbench/contract';
import {ExecutionTimeline} from '../workbench/ExecutionTimeline';
import {RunOutcome,EventEvidence} from './execution/ExecutionEvidence';
import {ExecutionRefreshStatus,ExecutionPhaseNavigation} from './execution/ExecutionControls';
import {isWorking,modelRelationship,recordedSpan} from './execution/presentation';
import {ModelConversation,conversationMessages,visibleConversationCalls} from '../workbench/ModelConversation';
import {useRoute} from '../navigation/router';
import './ExecutionPage.css';
import {useRecoveryNavigation,recoveryNavigation,initialAnalysisCall,markRecoveryLookup,cancelRecoveryNavigation,smoothRecoveryNavigate,captureRecoveryBaseline,beginRecoveryKnowledgeUpdate} from '../workbench/recoveryNavigation';
import {beginExperienceLookup} from '../workbench/knowledgeRetrieval';
import {useVisibleReading} from '../workbench/useVisibleReading';
import {knowledgeConversationSettled} from '../workbench/knowledgeJourney';
import {confirmedNewExperiences} from '../workbench/knowledgeUpdate';

export function ExecutionPage({active=true}:{active?:boolean}) {
  useLocale();
  const route=useRoute();
  const params=new URLSearchParams(typeof window==='undefined'?'':window.location.search);
  const sample=params.get('source')==='offline_fixture';
  const requested=params.get('trace');
  const liveClient=useRef(createVikunjaClient()).current;
  const [live,setLive]=useState<Incident[]>([]);
  const [data,setData]=useState<Snapshot|null>(sample?fixtureSnapshot():null);
  const [trace,setTrace]=useState<string|null>(requested);
  const [selectedId,setSelectedId]=useState<string>();
  const [error,setError]=useState(false);
  const [monitorError,setMonitorError]=useState(false);
  const [updatedAt,setUpdatedAt]=useState<string>();
  const [revision,setRevision]=useState(0);
  const [follow,setFollow]=useState(true);
  const [conversationFollow,setConversationFollow]=useState(true);
  const [replyReady,setReplyReady]=useState<string>();
  const flow=useRecoveryNavigation();
  const [shownReplies,setShownReplies]=useState<Record<string,number>>({});
  const learningNode=useRef<HTMLDivElement>(null);
  const restored=useRef<string|undefined>(undefined);
  const executionNode=useRef<HTMLElement>(null);
  useEffect(()=>{if(!active)return;const next=new URLSearchParams(window.location.search).get('trace');if(next!==trace){setTrace(next);setSelectedId(undefined);setReplyReady(undefined);setShownReplies({});setFollow(true);setConversationFollow(true);}},[active,route.href]);
  useEffect(()=>{
    if(!active&&!(flow?.trace===trace&&flow.phase==='lookup'))return;
    if(sample){setData(fixtureSnapshot());setLive([]);setError(false);setMonitorError(false);return;}
    const abort=new AbortController();let snapshotBusy=false,liveBusy=false;
    function refresh(){
      if(document.hidden)return;
      // A slow target/status request must not hold back saved timeline or model chunks.
      if(!snapshotBusy){snapshotBusy=true;void readWorkbench(abort.signal).then(value=>{if(!abort.signal.aborted){setData(value);setError(false);setUpdatedAt(new Date().toISOString());}}).catch(()=>{if(!abort.signal.aborted)setError(true);}).finally(()=>{snapshotBusy=false;});}
      if(!liveBusy){liveBusy=true;void liveClient.status(abort.signal).then(value=>{if(!abort.signal.aborted){setLive(liveRecoveryIncidents(value.automation));setMonitorError(false);}}).catch(()=>{if(!abort.signal.aborted)setMonitorError(true);}).finally(()=>{liveBusy=false;});}
    }
    refresh();const timer=window.setInterval(refresh,750);document.addEventListener('visibilitychange',refresh);
    return()=>{abort.abort();window.clearInterval(timer);document.removeEventListener('visibilitychange',refresh);};
  },[active,sample,revision,flow?.phase,flow?.trace,trace]);
  const visibleData=data?.source===(sample?'offline_fixture':'real')?data:null;
  const runs=[...(visibleData?.incidents??[]),...(!sample?live:[]).filter(item=>!visibleData?.incidents.some(record=>record.trace_id===item.trace_id))];
  const incident=trace?runs.find(item=>item.trace_id===trace):[...runs].sort((a,b)=>Date.parse(b.started_at)-Date.parse(a.started_at))[0];
  useEffect(()=>{if(active&&incident&&!trace)setTrace(incident.trace_id);},[active,incident?.trace_id,trace]);
  const target=visibleData?.targets.find(item=>item.id===incident?.target_id);
  const working=!!incident&&isWorking(incident);
  const latest=incident?.events.filter(event=>event.stage!=='experience_update').at(-1);
  const running=!error&&working;
  const current=running?latest:undefined;
  const selected=incident?.events.find(event=>event.id===selectedId)??(follow?incident?.events.at(-1):undefined)??incident?.events.at(-1);
  const pauseBrowsing=()=>{setSelectedId(selected?.id);setFollow(false);};
  const choose=(event:WorkbenchEvent)=>{
    setSelectedId(event.id);setFollow(false);
    executionNode.current?.querySelector('.execution-context')?.scrollTo({top:0,behavior:'instant'});
  };
  const choosePhase=(event:WorkbenchEvent)=>{
    choose(event);
    window.requestAnimationFrame(()=>{
      const pane=executionNode.current?.querySelector('.execution-timeline-pane');
      const row=pane?.querySelector('[data-selected=true]');
      if(!pane||!row)return;
      const bounds=pane.getBoundingClientRect(),item=row.getBoundingClientRect();
      if(item.top<bounds.top+80||item.bottom>bounds.bottom)pane.scrollTo({top:pane.scrollTop+item.top-bounds.top-90,behavior:'instant'});
    });
  };
  const span=incident?recordedSpan(incident):null;
  const firstAnalysis=incident?initialAnalysisCall(incident):undefined;
  const autoAnalysis=flow?.trace===incident?.trace_id&&flow?.phase==='analysis';
  const analysisKey=firstAnalysis?`${firstAnalysis.id}:${firstAnalysis.response?.length??0}`:'';
  const hasAnalysisReply=!!firstAnalysis&&conversationMessages(firstAnalysis).some(message=>message.role==='assistant');
  const recordedAnalysis=firstAnalysis?firstAnalysis.status!=='running'&&(!hasAnalysisReply||replyReady===analysisKey)
    :!!incident&&['rule','experience'].includes(incident.diagnosis_source)&&incident.events.some(event=>['failure_detection','localization','root_cause_analysis'].includes(event.stage));
  useVisibleReading(executionNode,`analysis:${incident?.trace_id}:${analysisKey}`,active&&!error&&autoAnalysis&&recordedAnalysis,2200,()=>{
    if(!incident)return;
    const trace=incident.trace_id;
    const position={window:window.scrollY,timeline:executionNode.current?.querySelector('.execution-timeline-pane')?.scrollTop??0,dialogue:executionNode.current?.querySelector('.execution-dialogue-scroll')?.scrollTop??0};
    void smoothRecoveryNavigate(()=>{markRecoveryLookup(trace,position);setFollow(false);return beginExperienceLookup(trace);},()=>recoveryNavigation()?.trace===trace&&recoveryNavigation()?.phase==='analysis');
  });
  useEffect(()=>{if(visibleData&&incident&&active)captureRecoveryBaseline(incident.trace_id,visibleData);},[active,visibleData,incident?.trace_id]);
  const persisted=visibleData?.incidents.find(item=>item.trace_id===incident?.trace_id);
  const terminal=!!incident&&['recovered','failed','unknown'].includes(incident.status);
  const newExperiences=persisted&&visibleData?confirmedNewExperiences(visibleData,persisted):[];
  const repliesShown=!!incident&&visibleConversationCalls(incident.model_calls).every(call=>!conversationMessages(call).some(message=>message.role==='assistant')||shownReplies[call.id]===(call.response?.length??0));
  const updateReady=!!persisted&&terminal&&!!incident&&knowledgeConversationSettled(incident)&&repliesShown;
  const updateKey=incident?`${incident.trace_id}:${incident.model_calls.map(call=>`${call.id}:${call.status}:${call.response?.length??0}`).join('|')}:${newExperiences.map(item=>item.id).join('|')}`:'';
  useVisibleReading(learningNode,`knowledge-update:${updateKey}`,active&&!error&&flow?.trace===incident?.trace_id&&flow?.phase==='execution'&&updateReady,5000,()=>{
    const trace=incident!.trace_id;
    void smoothRecoveryNavigate(()=>beginRecoveryKnowledgeUpdate(trace),()=>recoveryNavigation()?.trace===trace&&recoveryNavigation()?.phase==='execution');
  });
  useLayoutEffect(()=>{
    if(!active||flow?.phase!=='execution'||flow.trace!==incident?.trace_id||!flow.position||restored.current===flow.trace)return;
    const position=flow.position;restored.current=flow.trace;
    const frame=requestAnimationFrame(()=>{
      window.scrollTo({top:position.window,behavior:'instant'});
      setSelectedId(undefined);setFollow(true);setConversationFollow(true);
    });return()=>cancelAnimationFrame(frame);
  },[active,flow,incident?.trace_id]);

  return <section ref={executionNode} className="execution-page shell" aria-label={t("Live execution workspace")} data-active={active} onClickCapture={event=>{if((event.target as HTMLElement).closest('a,button,select,summary')&&!(event.target as HTMLElement).closest('[data-follow-control]'))cancelRecoveryNavigation();}}>
    <header className="execution-page-heading"><div><a href="/workbench"><ArrowLeft size={13}/>{t("Operations workbench")}</a><h1>{t("Execution ")}<span>{t("records")}</span></h1><p>{t("Follow the recovery. Read the conversation.")}</p></div><div><ExecutionRefreshStatus sample={sample} active={active} error={error} loaded={!!visibleData} monitorError={monitorError} updatedAt={updatedAt}/><button aria-label={t("Refresh execution")} onClick={()=>setRevision(v=>v+1)}><RefreshCw size={14}/></button></div></header>
    <div className="execution-runbar"><label><Workflow size={15}/><span>{t("Recovery run")}</span><select aria-label={t("Execution run")} value={incident?.trace_id??trace??''} onChange={e=>{cancelRecoveryNavigation();setTrace(e.target.value);setSelectedId(undefined);setFollow(false);const url=new URL(window.location.href);url.searchParams.set('trace',e.target.value);window.history.replaceState(window.history.state,'',url);}}>{!incident&&<option value={trace??''}>{trace ? t('Requested trace not found') : t('Choose a recorded recovery')}</option>}{[...runs].sort((a,b)=>Date.parse(b.started_at)-Date.parse(a.started_at)).map(item=><option key={item.id} value={item.trace_id}>{item.title} · {t(new Date(item.started_at).toLocaleTimeString(getLocale(),{timeZone:'Asia/Shanghai',hour12:false}))}</option>)}</select><ChevronDown size={12}/></label><span>{target?.name ?? t('No target selected')}</span><span>{t(incident?.status??'Awaiting evidence')}</span><span>{span===null ? t('Duration unknown') : t("{0}s recorded span", Math.max(0,span).toFixed(1))}</span>{incident&&<a href={`/workbench?source=${sample?'offline_fixture':'real'}&trace=${encodeURIComponent(incident.trace_id)}`}>{t("Knowledge & evidence")}<ArrowUpRight size={12}/></a>}</div>
    {incident?.events.some(event=>event.evidence.includes('source=live_monitor_events'))&&<p className="execution-pane-caption">{t("Live monitoring events · B experience persistence is not connected for this run. Model messages are not reconstructed.")}</p>}
    {error&&incident&&<p className="execution-feed-warning" role="alert">{t("Saved feed unavailable. Showing the last snapshot")}{updatedAt ? t(" from {0} CST", t(new Date(updatedAt).toLocaleString(getLocale(),{timeZone:'Asia/Shanghai',hour12:false}))) : ''}{t("; reconnect before treating it as current.")}</p>}
    {monitorError&&<p className="execution-feed-warning" role="status">{t("Live monitoring is unavailable. Saved records remain available.")}</p>}
    {error&&!incident?<div className="execution-empty" role="alert"><Activity size={25}/><h2>{t("Connection unavailable")}</h2><p>{t("The execution feed could not be read. Refresh to reconnect.")}</p></div>:!incident?<div className="execution-empty"><Workflow size={26}/><h2>{trace ? t('No exact matching trace') : t('Waiting for a recovery run')}</h2><p>{trace ? t('Another run has not been selected in its place.') : t('Recorded events appear when the recovery read model is connected. Existing recovery approvals remain separate.')}</p><a href="/workbench">{t("Open the workbench →")}</a></div>:<>
      <RunOutcome incident={incident} onSelect={choose}/>
      <ExecutionPhaseNavigation events={incident.events} selected={selected} onSelect={choosePhase}/>
      <div className="execution-split"><section className="execution-timeline-pane"><header><div><Workflow size={16}/><h2>{t("Recovery timeline")}</h2><span>{incident.events.length}{t(" events")}</span></div><button data-follow-control aria-pressed={follow} onClick={()=>{if(follow)pauseBrowsing();else{setFollow(true);setSelectedId(undefined);}}}>{t("Follow live ")}{follow ? t('on') : t('off')}</button></header><p className="execution-pane-caption">{t("Recorded stages · source evidence on selection")}</p><ExecutionTimeline events={incident.events} currentId={current?.id} selectedId={selected?.id} onSelect={choose} active={active} follow={follow} onPauseFollow={pauseBrowsing}/>
      </section><section className="execution-dialogue-pane" aria-label={t("API dialogue")}><header><div><MessagesSquare size={17}/><h2>{t("API conversation")}</h2></div><div><span>{incident.model_calls.length}{t(" model records")}</span><button data-follow-control aria-pressed={conversationFollow} onClick={()=>setConversationFollow(!conversationFollow)}>{conversationFollow ? t('Following latest') : t('Back to latest')}</button></div></header><div className="execution-context" aria-label={t("Current step context")}>
        {selected&&<EventEvidence key={selected.id} event={selected} incident={incident}/>}
      </div><div className="execution-dialogue-scroll" tabIndex={0} aria-label={t("Conversation messages")}><div className="execution-dialogue-body">
        <p className="execution-model-context">{t(modelRelationship(incident))}</p>
        {incident.model_calls.length?<ModelConversation calls={incident.model_calls} active={active} follow={conversationFollow} onPauseFollow={()=>setConversationFollow(false)} initialCallId={autoAnalysis?firstAnalysis?.id:undefined} onReplyReady={(id,response)=>{if(id===firstAnalysis?.id)setReplyReady(`${id}:${response?.length??0}`);setShownReplies(current=>current[id]===(response?.length??0)?current:{...current,[id]:response?.length??0});}}/>:<div className="execution-no-model"><MessagesSquare size={28}/><h3>{running ? t('Waiting for saved model conversation') : t('No model conversation recorded')}</h3><p>{incident.target_id.startsWith('history:') ? t('This historical Memory preserves its original diagnosis source and call count, but the complete model messages are unavailable here.') : incident.diagnosis_source==='experience' ? t('This recovery used recorded experience.') : t('No model request or reply is available for this run.')}{t(" Actual requests and replies appear as they are recorded.")}</p></div>}
        {terminal&&<div ref={learningNode} className="execution-learning-summary" aria-label={t("Execution knowledge result")}><strong>{persisted ? t('Execution record available in knowledge') : t('Waiting for the saved execution record')}</strong><p>{newExperiences.length ? t("{0} verified new experience saved.", newExperiences.length) : t('No new experience recorded. This execution and its verification still belong in the knowledge graph.')}</p>{incident.model_calls.some(call=>call.status==='running')&&<small>{t("Agent analysis is still receiving. Its actual follow-up remains above.")}</small>}{persisted&&<a href={`/knowledge-retrieval?source=real&trace=${encodeURIComponent(incident.trace_id)}&view=update`}>{t("View updated knowledge graph ")}<ArrowUpRight size={12}/></a>}</div>}
        <details className="execution-tools"><summary>{t("Target API & fixed tool interactions ")}<span>{t("Separate from model messages")}</span></summary>{incident.events.filter(event=>['recovery_execution','verification','recovery_decision'].includes(event.stage)).map(event=><button key={event.id} onClick={()=>choose(event)}><span>{event.title}</span><small>{event.evidence.find(value=>/^(method|query|event)=/.test(value)) ?? t(event.stage)}</small></button>)}</details>
      </div></div></section></div>
      <footer className="execution-page-footer"><span>{sample ? t('Sample data · no execution') : t('Same incident and trace · original audit retained')}</span><code>{incident.trace_id}</code><a href={`/agent?source=${sample?'offline_fixture':'real'}&feed=workbench&trace=${encodeURIComponent(incident.trace_id)}`}>{t("Inspect original trace")}<ArrowUpRight size={12}/></a></footer>
    </>}
  </section>;
}
