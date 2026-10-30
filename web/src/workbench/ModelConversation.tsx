import { t, useLocale } from '../i18n';
import {useEffect,useRef,useState} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import {ArrowUpRight,Bot,AlertCircle,RotateCcw,Terminal} from 'lucide-react';
import type {ModelCall} from './contract';
import './ModelConversation.css';
import {useLatestScroll} from './useLatestScroll';
import {knowledgeRetrieval} from './knowledgeRetrieval';

const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
function parse(value:string|null):unknown {try{return JSON.parse(value??'null');}catch{return value;}}
export function conversationMessages(call:ModelCall):{role:string;content:string}[] {
  const request=parse(call.request);
  const body=object(request)&&object(request.http_request)?request.http_request:request;
  const messages=object(body)&&Array.isArray(body.messages)?body.messages:null;
  let output=messages?.filter((m):m is {role:string;content:string}=>object(m)&&typeof m.role==='string'&&typeof m.content==='string')
    ??[{role:'user',content:call.request}];
  if(object(request)&&request.analysis_mode==='dependency-live-conversation-v1') {
    const lastUser=output.map(message=>message.role).lastIndexOf('user');
    if(lastUser>=0)output=output.slice(lastUser); // Prior turns stay in their own bubbles.
  }
  const response=parse(call.response);
  // A local failure message is never presented as something the model said.
  const content=object(response)&&typeof response.content==='string'?response.content
    :call.status==='succeeded'?call.response:null;
  return [...output,...(content?[{role:'assistant',content}]:[])];
}
export function requestPreview(call:ModelCall,content:string) {
  const request=parse(call.request);
  if(object(request)&&typeof request.request_summary==='string')return request.request_summary;
  const data=parse(content);
  if(object(data)&&Array.isArray(data.events)) {
    const verification=object(data.verification)?data.verification.status:'unknown';
    return t('Analyze the cause, evidence and suggested next steps from {0} recorded events. Business verification: {1}.', data.events.length, t(String(verification)));
  }
  return content.length>360?content.slice(0,360)+'…':content;
}
export function replyText(content:string) {
  const data=parse(content);
  if(object(data)&&typeof data.root_cause==='string')return [
    `${t('Root cause')}\n${data.root_cause}`,
    typeof data.suggested_plan==='string'?`${t('Suggested action')}\n${data.suggested_plan==='no_action'?t('No additional recovery action'):data.suggested_plan}`:'',
    typeof data.uncertainty==='string'&&data.uncertainty?`${t('Notes')}\n${data.uncertainty}`:'',
  ].filter(Boolean).join('\n\n');
  return content;
}
export function MessageContent({content}:{content:string}) {
  useLocale();
  return <div className="execution-message-text">{replyText(content)}<span data-text-end="true" aria-hidden="true"/></div>;
}
export function typewriterStep(current:number,total:number){return Math.min(total,current+Math.max(1,Math.ceil((total-current)/70)));}
function Typewriter({text,active,animate,onComplete,completionKey,readingFocus}:{text:string;active:boolean;animate:boolean;onComplete?:()=>void;completionKey?:string;readingFocus?:boolean}) {
  useLocale();
  const reduced=useReducedMotion();
  const [length,setLength]=useState(animate&&!reduced?0:text.length);
  useEffect(()=>{
    if(!animate||reduced){setLength(text.length);return;}
    if(!active)return;
    const timer=window.setInterval(()=>{
      if(document.hidden)return;
      setLength(count=>{const next=typewriterStep(count,text.length);if(next>=text.length)window.clearInterval(timer);return next;});
    },24);
    return()=>window.clearInterval(timer);
  },[text,active,animate,reduced]);
  const typing=animate&&!reduced&&length<text.length;
  const completed=useRef(onComplete);completed.current=onComplete;
  useEffect(()=>{if(active&&!typing)completed.current?.();},[active,typing,text,completionKey]);
  return <div className="execution-message-text execution-typewriter" aria-label={typing ? t('Model reply appearing') : undefined}>
    {text.slice(0,animate&&!reduced?length:text.length)}<span data-text-end="true" data-reading-focus={readingFocus} aria-hidden="true" className={typing?'execution-typing-caret':'execution-text-end'}/>
  </div>;
}
const errors:Record<string,string>={authentication_rejected:'The gateway rejected the current key. Check API settings.',
  rate_limited:'The gateway rate limit was reached.',gateway_rejected:'The gateway rejected this model request.',
  model_timeout:'The model request timed out. The outcome is unknown.',model_network_error:'The model connection was interrupted. The outcome is unknown.',
  stream_interrupted:'The stream was interrupted. Only received text is shown.',response_invalid:'The gateway response could not be validated.',
  response_empty_or_too_large:'The reply was empty or exceeded the response limit.',worker_unavailable:'The model analysis worker could not start.'};
function ConversationCall({call,active,onReplyReady,focus}:{call:ModelCall;active:boolean;onReplyReady?:(id:string,response:string|null)=>void;focus?:boolean}) {
  useLocale();
  const reduced=useReducedMotion();
  const [replay,setReplay]=useState(0);
  const request=parse(call.request),response=parse(call.response);
  const round=object(request)&&typeof request.round==='number'?request.round:null;
  const phase=object(request)&&typeof request.phase==='string'?({diagnosis:'Fault analysis',progress:'Recovery progress',verification:'Business verification'} as Record<string,string>)[request.phase]:null;
  const recent=object(request)&&typeof request.requested_at==='string'&&Date.now()-Date.parse(request.requested_at)<90000;
  const failed=call.status==='failed'||call.status==='unknown';
  const modelMessages=conversationMessages(call);
  const errorCode=object(response)&&typeof response.error==='string'?response.error:null;
  const error=errorCode?errors[errorCode]??'This model request is incomplete.':failed?'This historical request is incomplete; no error category was recorded.':null;
  const httpStatus=object(response)&&typeof response.http_status==='number'?response.http_status:null;
  const retrieval=knowledgeRetrieval(call);
  return <section className="execution-call" data-current-conversation={active} aria-label={t("Model call {0}", call.id)}>
    <header><span>{round ? t("Round {0} · {1} · ", t(round), t(phase??'Analysis')) : ''}{call.model}</span><span>{replay ? t('Recorded conversation · replay') : call.status==='running' ? t('Receiving model response') : call.status==='succeeded' ? t('Analysis complete') : t('Request incomplete')}{call.duration_ms!==null ? t(" · {0}s", (call.duration_ms/1000).toFixed(1)) : ''}</span>
      {modelMessages.some(message=>message.role==='assistant')&&<button className="execution-replay" onClick={()=>setReplay(v=>v+1)}><RotateCcw size={12}/>{t("Replay conversation")}</button>}
    </header>
    {retrieval&&(!round||round===1)&&<section className="execution-knowledge-retrieval" aria-label={t("Knowledge retrieval before model request")}>
      <header><strong>{t("ReOps → Knowledge library")}</strong><span>{retrieval.status==='hit' ? t('Verified experience found') : retrieval.status==='miss' ? t('No eligible experience') : t('Knowledge source unavailable')} · {t(retrieval.duration_ms)}{t("ms")}</span></header>
      <p>{t("Search verified prior incidents for this target and recovery profile.")}</p>
      {retrieval.matches.map(match=><article key={match.experience_id}><strong>{t("Experience → Model context")}</strong><p>{match.symptom}</p><p>{match.action}</p><a href={`/workbench?source=real&trace=${encodeURIComponent(match.trace_id)}`}>{t("Inspect source experience →")}</a><details><summary>{t("Matching conditions & source")}</summary><pre>{JSON.stringify(match,null,2)}</pre></details></article>)}
      <small>{retrieval.status==='hit' ? t('The following model request includes these records. Current recovery still requires its own Safety, approval and fresh checks.') : retrieval.status==='miss' ? t('The model analyzes current evidence without historical experience.') : t('Retrieval failed. Current evidence remains available; no historical match is claimed.')}</small>
    </section>}
    {modelMessages.filter(message=>message.role!=='system').map((message,index)=><motion.article key={`${call.id}:${index}`} initial={reduced?false:{opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{duration:.2}} className={`execution-message ${message.role==='assistant'?'from-model':'to-model'}`}>
      <div className="execution-message-heading">{message.role==='assistant'?<Bot size={15}/>:<ArrowUpRight size={15}/>}<strong>{message.role==='assistant' ? t('Model → ReOps') : t('ReOps → Model')}</strong><span>{message.role==='assistant' ? t((call.status==='running'?'Receiving':'Model reply')) : t('Request summary')}</span></div>
      {message.role==='assistant'?<Typewriter key={`${call.id}:${replay}:${index}`} text={replyText(message.content)} active={active} animate={!!recent||replay>0} readingFocus={focus} completionKey={call.status} onComplete={()=>{if(call.status!=='running')onReplyReady?.(call.id,call.response);}}/>:<MessageContent content={requestPreview(call,message.content)}/>}
    </motion.article>)}
    {error&&<div className="execution-model-error" role="status"><AlertCircle size={15}/><div><strong>{t("Model request incomplete")}{httpStatus ? t(" · HTTP {0}", t(httpStatus)) : ''}</strong><p>{t(error)}</p><small>{t("System status, not a model reply. No automatic retry or extra recovery action.")}</small></div></div>}
    {call.status==='running'&&<div className="execution-receiving" data-animate={active&&!!recent} role="status"><Terminal size={14}/>{recent ? t('Analyzing this incident…') : t('No completion recorded · outcome unknown')}<span/><span/><span/></div>}
    {object(response)&&response.finish_reason==='length'&&<p className="execution-limit-note">{t("The reply reached the output limit; the received text is preserved.")}</p>}
    <footer><span>{t("Input ")}{t(call.input_tokens??'Unknown')}{t(" tokens")}</span><span>{t("Output ")}{t(call.output_tokens??'Unknown')}{t(" tokens")}</span><details><summary>{t("Full request, response & usage")}</summary><pre>{call.request}</pre><pre>{call.response??t('No response recorded yet')}</pre></details></footer>
  </section>;
}
export function visibleConversationCalls(calls:ModelCall[]){
  const live=calls.filter(call=>{const value=parse(call.request);return object(value)&&value.analysis_mode==='dependency-live-conversation-v1';});
  return live.length?live:calls.length?[calls[calls.length-1]]:[];
}
export function ModelConversation({calls,active=true,follow=true,onReplyReady,initialCallId,onPauseFollow}:{calls:ModelCall[];active?:boolean;follow?:boolean;onReplyReady?:(id:string,response:string|null)=>void;initialCallId?:string;onPauseFollow?:()=>void}) {
  useLocale();
  const node=useRef<HTMLDivElement>(null);
  const newest=calls.at(-1);
  const live=calls.filter(call=>{const value=parse(call.request);return object(value)&&value.analysis_mode==='dependency-live-conversation-v1';});
  const visible=live.length?live:newest?[newest]:[];
  const old=calls.filter(call=>!visible.includes(call));
  useLatestScroll(node,'.execution-dialogue-scroll',active,follow,newest?.id??'',onPauseFollow);
  return <div ref={node} className="execution-conversation">{!!live.length&&<p className="execution-conversation-mode">{t("Live model analysis · recovery runs independently")}</p>}{visible.map(call=><ConversationCall key={call.id} call={call} active={active} focus={call.id===initialCallId} onReplyReady={onReplyReady}/>)}
    {!!old.length&&<details className="execution-previous"><summary>{t("Earlier model requests (")}{old.length})</summary>{old.map(call=><ConversationCall key={call.id} call={call} active={false}/>)}</details>}
  </div>;
}
