import { t, useLocale, getLocale } from '../i18n';
import {motion,useReducedMotion} from 'motion/react';
import {useRef} from 'react';
import {useLatestScroll} from './useLatestScroll';
import {Activity,Check,ChevronRight,Circle,Minus,Clock,KeyRound,ShieldCheck} from 'lucide-react';
import type {WorkbenchEvent} from './contract';
import {eventPhase,phaseNames} from '../pages/execution/presentation';

export {eventPhase,phaseNames};
export function ExecutionTimeline({events,currentId,selectedId,onSelect,active=true,follow=false,onPauseFollow}:{events:WorkbenchEvent[];currentId?:string;selectedId?:string;onSelect:(event:WorkbenchEvent)=>void;active?:boolean;follow?:boolean;onPauseFollow?:()=>void}) {
  useLocale();
  const reduced=useReducedMotion();
  const list=useRef<HTMLOListElement>(null);
  useLatestScroll(list,'.execution-timeline-pane',active,follow,`${events.at(-1)?.id}:${events.at(-1)?.status}`,onPauseFollow);
  return <ol ref={list} className="execution-timeline" aria-label={t("Recovery execution timeline")}>
    {events.map((event,index)=>{const running=active&&event.id===currentId;const phase=eventPhase(event);const delta=index?Math.max(0,(Date.parse(event.timestamp)-Date.parse(events[index-1].timestamp))/1000):0;
      return <motion.li key={event.id} initial={reduced?false:{opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{duration:.24}} data-running={running} data-selected={selectedId===event.id} data-status={event.status}>
        <span className="execution-node">{event.status==='failed'?'!':phase==='authorization'?<KeyRound size={11}/>:phase==='safety'?<ShieldCheck size={11}/>:event.status==='succeeded'?<Check size={12}/>:event.status==='skipped'?<Minus size={12}/>:event.status==='waiting_human'?<Clock size={12}/>:event.status==='running'?<Activity size={12}/>:<Circle size={10}/>}</span>
        <button onClick={()=>onSelect(event)} aria-pressed={selectedId===event.id}><span className="execution-phase">{t(phaseNames[phase]??phase)}<small>{t(new Date(event.timestamp).toLocaleTimeString(getLocale(),{timeZone:'Asia/Shanghai',hour12:false}))}</small></span><strong>{event.title}<ChevronRight size={13}/></strong><span className="execution-event-meta">{t(event.status.replaceAll('_',' '))}{running ? t(' · latest signal') : ''}<span>{index&&Number.isFinite(delta) ? t("+{0}s", delta.toFixed(1)) : index ? t('Time unavailable') : t('First signal')}</span></span></button>
      </motion.li>;
    })}
  </ol>;
}
