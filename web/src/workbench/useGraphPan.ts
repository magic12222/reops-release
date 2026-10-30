import {useEffect} from 'react';
import type {RefObject} from 'react';

// Drag the existing scrollable canvas; a short press still selects its node.
export function useGraphPan(ref:RefObject<HTMLElement|null>,enabled:boolean){
  useEffect(()=>{
    const pane=ref.current;if(!pane||!enabled)return;
    pane.dataset.draggable='true';
    let start:{id:number;x:number;y:number;left:number;top:number}|undefined,dragged=false,suppressClick=false;
    const down=(event:PointerEvent)=>{
      const target=event.target;
      if(!event.isPrimary||event.button!==0||target instanceof Element&&target.closest('button,a,input,select,textarea,summary'))return;
      start={id:event.pointerId,x:event.clientX,y:event.clientY,left:pane.scrollLeft,top:pane.scrollTop};dragged=false;suppressClick=false;
    };
    const move=(event:PointerEvent)=>{
      if(!start||event.pointerId!==start.id)return;
      const x=event.clientX-start.x,y=event.clientY-start.y;
      if(!dragged&&Math.hypot(x,y)<5)return;
      if(!dragged){dragged=true;pane.dataset.panning='true';pane.setPointerCapture(event.pointerId);}
      event.preventDefault();pane.scrollLeft=start.left-x;pane.scrollTop=start.top-y;
    };
    const up=(event:PointerEvent)=>{
      if(!start||event.pointerId!==start.id)return;
      suppressClick=dragged;
      if(pane.hasPointerCapture(event.pointerId))pane.releasePointerCapture(event.pointerId);
      start=undefined;delete pane.dataset.panning;
    };
    const click=(event:MouseEvent)=>{if(suppressClick){suppressClick=false;event.preventDefault();event.stopImmediatePropagation();}};
    pane.addEventListener('pointerdown',down);pane.addEventListener('pointermove',move);pane.addEventListener('click',click,true);
    window.addEventListener('pointerup',up);window.addEventListener('pointercancel',up);
    return()=>{if(start&&pane.hasPointerCapture(start.id))pane.releasePointerCapture(start.id);delete pane.dataset.draggable;delete pane.dataset.panning;pane.removeEventListener('pointerdown',down);pane.removeEventListener('pointermove',move);pane.removeEventListener('click',click,true);window.removeEventListener('pointerup',up);window.removeEventListener('pointercancel',up);};
  },[ref,enabled]);
}
