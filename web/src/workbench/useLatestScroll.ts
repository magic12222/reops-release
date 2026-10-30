import {useLayoutEffect,useRef} from 'react';
import type {RefObject} from 'react';

// Follow layout growth (including streamed text), not polling timestamps.
// Only deliberate user input pauses following; programmatic scroll never does.
export function useLatestScroll(content:RefObject<HTMLElement|null>,selector:string,active:boolean,follow:boolean,key:string,onPause?:()=>void){
  const pause=useRef(onPause);pause.current=onPause;
  const paused=useRef(!follow),previousFollow=useRef(follow);
  useLayoutEffect(()=>{
    const node=content.current,pane=node?.closest<HTMLElement>(selector);
    if(!node||!pane||!active)return;
    if(previousFollow.current!==follow){paused.current=!follow;previousFollow.current=follow;}
    let frame=0,touchY:number|undefined,reveal=true;
    const stop=()=>{if(!paused.current){paused.current=true;pause.current?.();}};
    const update=()=>{
      if(frame)return;
      frame=requestAnimationFrame(()=>{
        frame=0;
        if(paused.current||!follow||document.hidden)return;
        // The newest request wins over a still-typing older reply. Follow text,
        // including the last received character, rather than usage/tool footers.
        const latest=node.querySelector('[data-current-conversation="true"]:last-of-type');
        const text=latest?.querySelectorAll<HTMLElement>('[data-text-end]').item((latest?.querySelectorAll('[data-text-end]').length??0)-1);
        const target=text??Array.from(node.querySelectorAll<HTMLElement>('[data-text-end]')).at(-1);
        if(!target){pane.scrollTop=pane.scrollHeight;return;}
        if(reveal){
          reveal=false;
          const panel=pane.closest<HTMLElement>('.execution-dialogue-pane')??pane;
          const panelBox=panel.getBoundingClientRect();
          if(panelBox.bottom>window.innerHeight||panelBox.top<80)panel.scrollIntoView?.({block:'end',behavior:'instant'});
        }
        const box=target.getBoundingClientRect(),area=pane.getBoundingClientRect();
        const bottom=Math.min(area.bottom,window.innerHeight)-56,top=Math.max(area.top,0)+18;
        if(box.bottom>bottom||box.top<top)pane.scrollTop+=box.bottom-bottom;
      });
    };
    const wheel=(event:WheelEvent)=>{if(event.deltaY<0)stop();};
    const keyboard=(event:KeyboardEvent)=>{if(['PageUp','Home','ArrowUp'].includes(event.key))stop();};
    const touchStart=(event:TouchEvent)=>{touchY=event.touches[0]?.clientY;};
    const touchMove=(event:TouchEvent)=>{const next=event.touches[0]?.clientY;if(next!==undefined&&touchY!==undefined&&next>touchY+2)stop();touchY=next;};
    const pointer=(event:PointerEvent)=>{const target=event.target as HTMLElement;if(target.closest('summary,button,input,select,a')||event.clientX>=pane.getBoundingClientRect().right-Math.max(10,pane.offsetWidth-pane.clientWidth))stop();};
    const scrolled=()=>{if(!paused.current)update();else if(follow&&!pause.current&&pane.scrollHeight-pane.scrollTop-pane.clientHeight<4){paused.current=false;update();}};
    const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(update);observer?.observe(node);observer?.observe(pane);if(pane.firstElementChild)observer?.observe(pane.firstElementChild);
    const mutations=new MutationObserver(update);mutations.observe(node,{subtree:true,childList:true,characterData:true});
    pane.addEventListener('wheel',wheel,{passive:true});pane.addEventListener('keydown',keyboard);pane.addEventListener('touchstart',touchStart,{passive:true});pane.addEventListener('touchmove',touchMove,{passive:true});pane.addEventListener('pointerdown',pointer);pane.addEventListener('scroll',scrolled,{passive:true});document.addEventListener('visibilitychange',update);
    update();
    return()=>{cancelAnimationFrame(frame);observer?.disconnect();mutations.disconnect();pane.removeEventListener('wheel',wheel);pane.removeEventListener('keydown',keyboard);pane.removeEventListener('touchstart',touchStart);pane.removeEventListener('touchmove',touchMove);pane.removeEventListener('pointerdown',pointer);pane.removeEventListener('scroll',scrolled);document.removeEventListener('visibilitychange',update);};
  },[content,selector,active,follow,key]);
}
