import { t, useLocale, getLocale } from '../i18n';
import {useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import type {Incident,Snapshot} from './contract';
import type {KnowledgeRetrieval} from './knowledgeRetrieval';
import {knowledgeText} from './knowledgeText';
import {kindLabels} from './knowledge';
import {atlasPositions} from './knowledgeAtlas';
import {knowledgeAnimation} from './knowledgeAnimation';
import {knowledgeAnimationScene,graphAnimationRates,readGraphAnimationRate,rememberGraphAnimationRate} from './knowledgeAnimationScene';
import {useVisibleReading} from './useVisibleReading';
import {useGraphPan} from './useGraphPan';
import './KnowledgeExplorer.css';
import './KnowledgeJourneyStage.css';

const stamp=(data:Snapshot,id:string)=>{const origin=data.incidents.find(i=>i.id===id);return origin?new Date(origin.started_at).toLocaleString(getLocale(),{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}):'';};
const lines=(value:string)=>{const limit=/[\u3400-\u9fff]/.test(value)?13:24;if(value.length<=limit)return [value];let split=value.lastIndexOf(' ',limit);if(split<limit/2)split=limit;const tail=value.slice(split).trim();return [value.slice(0,split),tail.length>limit?tail.slice(0,limit-1)+'…':tail];};
export function KnowledgeJourneyStage({data,incident,mode,retrieval,active,onComplete}:{data:Snapshot;incident:Incident;mode:'lookup'|'update';retrieval?:KnowledgeRetrieval|null;active:boolean;onComplete?:()=>void}){
  useLocale();
  const [plan,setPlan]=useState(()=>knowledgeAnimation(data,incident,mode,retrieval));
  const [step,setStep]=useState(0),[paused,setPaused]=useState(false),[selected,setSelected]=useState<string>(),[overview,setOverview]=useState(true),[showAll,setShowAll]=useState(false),[rate,setRate]=useState(readGraphAnimationRate),[cameraReady,setCameraReady]=useState(false),[viewportWidth,setViewportWidth]=useState(800);
  const [settled,setSettled]=useState(false),[browseZoom,setBrowseZoom]=useState(1);
  const browsing=showAll||mode==='update'&&settled;
  const node=useRef<HTMLElement>(null),viewport=useRef<HTMLDivElement>(null),completed=useRef(false);
  const reduced=useReducedMotion(),marker=useId().replace(/:/g,'');
  useGraphPan(viewport,active&&browsing&&browseZoom>0);
  const evidenceKey=JSON.stringify([incident.status,incident.summary,incident.verification,incident.events,incident.experience_ids,incident.model_calls.map(c=>c.request),data.experiences.filter(e=>e.incident_id===incident.id)]);
  useEffect(()=>{if(mode!=='update')return;const next=knowledgeAnimation(data,incident,mode);setPlan(next);if(showAll||settled){setStep(next.frames.length-1);return;}setStep(0);setSelected(undefined);setOverview(true);setShowAll(false);setSettled(false);setBrowseZoom(1);completed.current=false;},[mode,evidenceKey]);
  useEffect(()=>{if(active&&mode==='update'){setStep(0);setPaused(false);setSelected(undefined);setOverview(true);setShowAll(false);setSettled(false);setBrowseZoom(1);completed.current=false;}},[active,mode]);
  useLayoutEffect(()=>{const el=viewport.current;if(!el)return;const observer=new ResizeObserver(()=>setViewportWidth(el.clientWidth));observer.observe(el);setViewportWidth(el.clientWidth);return()=>observer.disconnect();},[]);
  // Fit the entire visible structure, not a zoomed crop. Hidden history is only
  // filtered for playback and rejoins this same graph in the final frame.
  const scene=knowledgeAnimationScene(plan,incident.id,step,selected,browsing);
  const layout=atlasPositions(scene);
  const frame=plan.frames[Math.min(step,plan.frames.length-1)],focal=layout.positions.get(selected??frame.ids[0])??{x:560,y:200};
  const cameraWidth=Math.max(210,Math.min(900,viewportWidth)),cameraHeight=520*cameraWidth/Math.max(210,viewportWidth);
  const camera=browsing||overview?`0 0 1120 ${layout.height}`:`${focal.x-cameraWidth/2} ${focal.y-cameraHeight/2} ${cameraWidth} ${cameraHeight}`;
  useEffect(()=>{if(!active)return;setCameraReady(false);const timer=setTimeout(()=>setCameraReady(true),reduced?0:1100/rate);return()=>clearTimeout(timer);},[active,camera,reduced,rate]);
  const finished=step===plan.frames.length-1,shown=scene.nodes;
  const detail=plan.graph.nodes.find(n=>n.id===(selected??frame.ids[0])),relationships=plan.graph.edges.filter(e=>e.from===detail?.id||e.to===detail?.id);
  const experience=data.experiences.find(e=>e.id===detail?.record),origin=data.incidents.find(i=>i.id===detail?.incidentId);
  useVisibleReading(node,`${incident.trace_id}:${mode}:${step}:${rate}`,active&&!paused&&!browsing&&cameraReady&&!completed.current,(finished?5000:2000)/rate,()=>{if(step<plan.frames.length-1){setSelected(undefined);setStep(s=>s+1);}else{completed.current=true;setSettled(true);onComplete?.();}});
  const select=(id:string)=>{setSelected(id);setPaused(true);};
  const advance=(delta:number)=>{setSelected(undefined);setPaused(true);setStep(s=>s+delta);};
  const focusSelected=()=>{setPaused(true);if(browsing){const zoom=browseZoom||1;if(!browseZoom)setBrowseZoom(1);requestAnimationFrame(()=>{const pane=viewport.current;if(pane)pane.scrollTo({left:Math.max(0,focal.x*zoom-pane.clientWidth/2),top:Math.max(0,focal.y*zoom-pane.clientHeight/2),behavior:reduced?'instant':'smooth'});});}else setOverview(false);};
  return <section ref={node} className="kg kg-atlas knowledge-journey" aria-label={t(mode==='lookup'?'Animated knowledge lookup':'Animated execution integration')} data-step={step} data-overview={overview} data-speed={rate} data-display={browsing?'browse':'animation'}>
    <header className="kg-heading"><div><h3>{t("ReOps Knowledge")}</h3><p>{mode==='lookup'?t('Trace the match in the existing network.'):t('Existing knowledge and this execution, in the same network.')}</p></div></header>
    {!browsing&&<div className="kg-journey"><h2 aria-live="polite">{t(frame.title)}</h2><span>{step+1} {t(" / ")}{plan.frames.length}</span><label className="knowledge-journey-rate">{t("Speed ")}<select aria-label={t("Graph animation speed")} value={rate} onChange={event=>{const next=Number(event.target.value);setRate(next);rememberGraphAnimationRate(next);}}>{graphAnimationRates.map(value=><option key={value} value={value}>{value}{t("×")}</option>)}</select></label><button onClick={()=>{setSelected(undefined);setPaused(p=>!p);}}>{paused?t('Continue animation'):t('Pause animation')}</button></div>}
    <div className="kg-workspace"><div className="kg-canvas-area"><div className="kg-canvas-tools"><span>{shown.length} {t(" nodes · ")}{finished||showAll?t('complete knowledge network'):t('current experience · history returns at completion')}</span><button aria-pressed={browsing} onClick={()=>{setOverview(true);setShowAll(true);setPaused(true);}}>{t("Browse connected network")}</button><button aria-pressed={!overview} onClick={focusSelected}>{t("Focus selected")}</button>{browsing?<label>{t("Zoom ")}<select aria-label={t("Updated graph zoom")} value={browseZoom} onChange={event=>setBrowseZoom(Number(event.target.value))}><option value={0}>{t("Fit")}</option><option value={1}>{t("100%")}</option><option value={1.25}>{t("125%")}</option><option value={1.5}>{t("150%")}</option></select></label>:<><button disabled={step===0} onClick={()=>advance(-1)}>{t("Previous focus")}</button><button disabled={finished} onClick={()=>advance(1)}>{t("Next focus")}</button></>}</div>
    <div ref={viewport} className="kg-canvas knowledge-journey-viewport" data-reading-focus="true" tabIndex={0} aria-label={t("Original knowledge network viewport")}>
      <motion.svg className="knowledge-journey-network" width={browsing&&browseZoom>0?1120*browseZoom:"100%"} height={browsing&&browseZoom>0?layout.height*browseZoom:520} role="group" aria-label={t("Original knowledge graph and execution branch")} initial={false} animate={{viewBox:camera}} transition={{duration:reduced?0:1/rate,ease:'easeInOut'}}>
        <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z"/></marker></defs>
        {scene.edges.map(e=>{const a=layout.positions.get(e.from),b=layout.positions.get(e.to);if(!a||!b)return null;const connected=e.from===detail?.id||e.to===detail?.id,dx=b.x-a.x,dy=b.y-a.y,vertical=Math.abs(dy)>Math.abs(dx),x1=a.x+(vertical?0:Math.sign(dx)*96),y1=a.y+(vertical?Math.sign(dy)*28:0),x2=b.x-(vertical?0:Math.sign(dx)*96),y2=b.y-(vertical?Math.sign(dy)*28:0);return <motion.g key={`${e.from}:${e.to}`} data-edge-from={e.from} data-edge-to={e.to} className={`kg-edge ${connected?'connected':''}`} initial={reduced?false:{opacity:0}} animate={{opacity:connected||overview?1:.25}}><title>{e.label} {t(" · ")}{e.field}</title><path d={`M${x1} ${y1} C${x1} ${(y1+y2)/2},${x2} ${(y1+y2)/2},${x2} ${y2}`} markerEnd={`url(#${marker})`}/>{connected&&<text x={(x1+x2)/2+ (vertical?35:0)} y={(y1+y2)/2-6} textAnchor="middle">{e.label}</text>}</motion.g>;})}
        {shown.map(n=>{const p=layout.positions.get(n.id);if(!p)return null;const current=n.id===detail?.id,date=n.kind==='experience'&&n.provenance==='recorded'?stamp(data,n.incidentId):'',label=date?date.split(' '):lines(n.provenance==='curated'?t(n.label):n.label);return <motion.g key={n.id} data-node-id={n.id} data-current-run={n.incidentId===incident.id} data-current={current} role="button" tabIndex={0} aria-label={`${t(kindLabels[n.kind])}: ${n.label}`} aria-pressed={current} className={`kg-node kg-${n.kind} knowledge-journey-node ${current?'selected':''}`} initial={reduced?false:{opacity:0,x:p.x-96,y:p.y-28}} animate={{opacity:1,x:p.x-96,y:p.y-28}} transition={{duration:reduced?0:.4/rate}} onClick={()=>select(n.id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(n.id);}}}><title>{n.label}</title><rect width={192} height={56} rx={8}/><text x={12} y={14} className="kg-node-kind">{t(kindLabels[n.kind])}</text>{label.map((line,i)=><text key={i} x={12} y={label.length===1?38:32+i*15}>{line}</text>)}</motion.g>;})}
      </motion.svg>
    </div><div className="kg-legend">{[...new Set(shown.map(n=>n.kind))].map(kind=><span key={kind} className={`kg-${kind}`}><i/>{t(kindLabels[kind])}</span>)}</div></div>
    <aside className="kg-detail knowledge-journey-detail" aria-label={t("Focused graph evidence")}><span className="kg-detail-kind">{detail?t(kindLabels[detail.kind]):t('Recorded source')}</span><h4>{detail?.provenance==='curated'?t(detail.label):detail?.label}</h4>{detail?.kind==='experience'&&detail.provenance==='recorded'&&<time>{stamp(data,detail.incidentId)} {t(" CST")}</time>}<p className="kg-value">{experience?experience.root_cause:detail?knowledgeText(detail):t('No additional evidence in this record.')}</p>
      {experience&&<p className="kg-value">{experience.action}</p>}{origin&&<p className="kg-origin-check">{t("Recorded verification · ")}<strong>{t(origin.verification.status)}</strong> {t(" · ")}{origin.verification.checks.length} {t(" checks")}</p>}
      {detail?.kind==='experience'&&retrieval?.matches.filter(m=>`experience:${m.experience_id}`===detail.id).map(m=><p className="kg-value" key={m.experience_id}>{t("Match conditions: ")}{m.matched_conditions?.join(' · ')||'Not included in this receipt'}</p>)}
      <h5>{t("Evidence links · ")}{relationships.length}</h5><ul>{relationships.map(e=>{const id=e.from===detail?.id?e.to:e.from;return <li key={`${e.from}:${e.to}`}><button onClick={()=>select(id)}><span>{e.label} {t(" →")}</span>{plan.graph.nodes.find(n=>n.id===id)?.label}</button></li>;})}</ul><details><summary>{t("Conditions & complete record")}</summary><code>{detail?.id}<br/>{detail?.field}<br/>{detail?.record}</code><pre>{JSON.stringify({node:detail,experience,event:origin?.events.find(e=>e.id===detail?.eventId)},null,2)}</pre></details>
    </aside></div>
  </section>;
}
