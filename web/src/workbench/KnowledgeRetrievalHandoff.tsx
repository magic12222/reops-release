import { t, useLocale, getLocale } from '../i18n';
import {useEffect,useMemo,useState,useRef} from 'react';
import {useVisibleReading} from './useVisibleReading';
import type {Incident} from './contract';
import {knowledgeRetrieval,lookupCanContinue,completeExperienceLookup,parseKnowledgeRetrieval,retrievalFailure} from './knowledgeRetrieval';
import type {KnowledgeRetrieval} from './knowledgeRetrieval';
import {navigate} from '../navigation/router';
import {smoothRecoveryNavigate} from './recoveryNavigation';
import './KnowledgeRetrievalHandoff.css';

export function KnowledgeRetrievalHandoff({incident,active,onRetrieved,onStage,onResult,graphReady=false}:{incident:Incident;active:boolean;onRetrieved?:(id:string|undefined)=>void;onStage?:(stage:number)=>void;onResult?:(result:KnowledgeRetrieval|null)=>void;graphReady?:boolean}) {
  useLocale();
  const first=incident.model_calls.find(call=>knowledgeRetrieval(call));
  const [local,setLocal]=useState<KnowledgeRetrieval|null>(null);
  const [error,setError]=useState<ReturnType<typeof retrievalFailure>|null>(null);
  const [retry,setRetry]=useState(0);
  const result=useMemo(()=>first?knowledgeRetrieval(first):local,[first?.request,local]);
  const node=useRef<HTMLElement>(null);
  const [stage,setStage]=useState(0);
  const automatic=lookupCanContinue(incident.trace_id);
  useEffect(()=>onStage?.(stage),[stage,onStage]);
  useEffect(()=>onResult?.(result),[result,onResult]);
  useVisibleReading(node,`${incident.trace_id}:lookup-complete`,active&&lookupCanContinue(incident.trace_id)&&graphReady,350,()=>{
    void smoothRecoveryNavigate(()=>{completeExperienceLookup(incident.trace_id);return `/execution?source=real&trace=${encodeURIComponent(incident.trace_id)}`;},()=>lookupCanContinue(incident.trace_id));
  });
  const execution=`/execution?source=real&trace=${encodeURIComponent(incident.trace_id)}`;
  const finish=()=>{completeExperienceLookup(incident.trace_id);navigate(execution);};
  useEffect(()=>{
    if(!active||first)return;
    const abort=new AbortController();let timedOut=false;
    setError(null);setLocal(null);
    const timer=window.setTimeout(()=>{timedOut=true;abort.abort();},10000);
    void fetch('/api/v1/researchloop/control/dependency-diagnosis/knowledge/'+encodeURIComponent(incident.id),{credentials:'same-origin',cache:'no-store',redirect:'error',signal:abort.signal})
      .then(async response=>{if(!response.ok)throw response.status;const result=parseKnowledgeRetrieval(await response.json(),incident.trace_id);if(!result)throw 0;if(!abort.signal.aborted){setLocal(result);setError(null);}})
      .catch(status=>{if(!abort.signal.aborted||timedOut){setError(retrievalFailure(timedOut?408:typeof status==='number'?status:0));}})
      .finally(()=>window.clearTimeout(timer));
    return()=>{window.clearTimeout(timer);abort.abort();};
  },[active,first?.id,incident.id,incident.trace_id,retry]);
  useEffect(()=>onRetrieved?.(result?.status==='hit'?result.matches[0]?.experience_id:undefined),[result?.status,result?.matches[0]?.experience_id,onRetrieved]);
  return <section ref={node} className="knowledge-handoff" aria-label={t("Experience retrieval and Agent handoff")}>
    <header><div><span>{t("EXPERIENCE LOOKUP")}</span><h2>{error&&!result ? t(error.title) : result?.status==='hit' ? t("{0} verified {1} matched", result.matches.length, result.matches.length===1 ? t('memory') : t('memories')) : result?.status==='miss' ? t('No matching experience') : result?.status==='unavailable' ? t('Knowledge source unavailable') : t('Finding a verified precedent')}</h2></div><span className="lookup-status">{error&&!result ? t('Connection required') : first ? t('Passed to Agent') : result ? t('Lookup complete') : t('Searching')}{result ? t(" · {0}ms", result.duration_ms<1 ? '<1' : t(result.duration_ms)) : ''}</span></header>

    {!automatic&&<ol className="lookup-steps" aria-label={t("Recorded experience workflow")}><li><span>{t("Fault context")}</span></li><li><span>{t("Verified history")}</span></li><li><span>{t("Agent context")}</span></li></ol>}
    {error&&!result&&<div className="knowledge-handoff-error" role="alert"><p>{t(error.message)}</p><button onClick={()=>{setStage(0);setRetry(v=>v+1);}}>{t("Retry knowledge lookup")}</button><a href="/api">{t("Check API service →")}</a></div>}
    {(!automatic||stage>=2)&&!!result?.matches.length&&<div className="lookup-results">{result.matches.map((match,index)=><article className="lookup-result" key={match.experience_id}><span className="lookup-rank">{String(index+1).padStart(2,'0')}</span><div><h3>{match.root_cause || match.symptom}</h3><p>{match.source_started_at ? t(new Date(match.source_started_at).toLocaleString(getLocale(),{timeZone:'Asia/Shanghai',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'})) : t("Source · {0}", match.trace_id.slice(-12))}<span>{t("Verified recovery")}</span></p></div><a href={`/workbench?source=real&trace=${encodeURIComponent(match.trace_id)}`}>{t("Source ↗")}</a><details><summary>{t("Evidence")}</summary><pre>{JSON.stringify(match,null,2)}</pre></details></article>)}</div>}
    {(!automatic||stage>=2)&&result?.matches[0]&&<div className="lookup-context"><span>{t("HISTORICAL PLAN")}</span><p>{result.matches[0].action}</p><small>{Array.isArray(result.matches[0].matched_conditions) ? result.matches[0].matched_conditions.filter(value=>typeof value==='string').map(value=>{const labels:Record<string,string>={'same_target':'Same target','prior_verified_incident':'Earlier verified incident','dependency-audit-v1':'Matching dependency evidence','vikunja_dependency_v1':'Matching recovery plan'};return Object.prototype.hasOwnProperty.call(labels,value)?t(labels[value]):value;}).join(' · ') : t('Applicability conditions are unavailable in this record. Full source evidence remains above.')}</small></div>}
    {result?.status==='miss'&&<p className="lookup-note">{t("No historical experience is included in this lookup. Saved Agent records, if available, remain the source of truth.")}</p>}
    {result?.status==='unavailable'&&<p className="lookup-note">{t("The knowledge source is unavailable. No historical match is claimed.")}</p>}
    {(!automatic||stage>=3)&&first&&<details><summary>{t("Actual context passed to Agent")}</summary><pre>{first.request}</pre></details>}
    <footer><span role="status">{error&&!result ? t('Retrieval could not be verified. Retry the lookup or inspect the execution record.') : first ? t('Context retained in the actual API request.') : t('Recorded lookup · no additional approval required.')}</span><a href={execution} onClick={event=>{event.preventDefault();finish();}}>{t("View execution ↗")}</a></footer>
  </section>;
}
