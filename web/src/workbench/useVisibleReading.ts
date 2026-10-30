import {useEffect,useRef} from 'react';
import type {RefObject} from 'react';
// A visible reading interval begins only after the committed content and its finite
// animations settle. Hidden/off-page/paused time never counts as reading time.
export function useVisibleReading(node:RefObject<HTMLElement|null>,key:string,enabled:boolean,duration:number,onComplete:()=>void){
  const callback=useRef(onComplete);callback.current=onComplete;
  const progress=useRef({key,elapsed:0});
  useEffect(()=>{
    if(progress.current.key!==key)progress.current={key,elapsed:0};
    if(!enabled||!node.current)return;
    let disposed=false,frame=0,last=0,settled=false;
    let focus=node.current.closest('.knowledge-retrieval-page')?.querySelector<HTMLElement>('[data-reading-focus="true"]')??node.current.querySelector<HTMLElement>('[data-reading-focus="true"]')??node.current;
    focus.scrollIntoView?.({block:'center',behavior:'instant'});
    const settle=async()=>{
      const animations=node.current?.getAnimations?.({subtree:true}).filter(a=>{
        const target=(a.effect as KeyframeEffect|null)?.target;
        // CSS animations in a closed details/hidden cached page may never finish.
        // Only visible animations inside this reading surface govern its clock.
        return Number.isFinite(Number(a.effect?.getComputedTiming().endTime))&&a.playState!=='paused'
          &&(!(target instanceof Element)||target.getClientRects().length>0);
      })??[];
      await Promise.allSettled(animations.map(a=>a.finished));if(!disposed)settled=true;
    };
    // Two committed frames also cover reduced motion and empty graphs.
    let frames=0;
    const tick=(now:number)=>{
      if(disposed)return;
      const rect=focus.getBoundingClientRect();
      if(document.hidden||rect.bottom<=0||rect.top>=window.innerHeight){last=0;frame=requestAnimationFrame(tick);return;}
      if(frames++===1){
        const updated=node.current?.closest('.knowledge-retrieval-page')?.querySelector<HTMLElement>('[data-reading-focus="true"]')??node.current?.querySelector<HTMLElement>('[data-reading-focus="true"]');
        if(updated&&updated!==focus){focus=updated;focus.scrollIntoView?.({block:'center',behavior:'instant'});}
        void settle();
      }
      if(settled&&last)progress.current.elapsed+=Math.min(100,now-last);
      last=settled?now:0;
      if(progress.current.elapsed>=duration){callback.current();return;}
      frame=requestAnimationFrame(tick);
    };
    frame=requestAnimationFrame(tick);
    return()=>{disposed=true;cancelAnimationFrame(frame);};
  },[node,key,enabled,duration]);
}
