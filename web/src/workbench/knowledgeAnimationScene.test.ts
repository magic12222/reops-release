import {describe,it,expect} from 'vitest';
import type {KnowledgeAnimation} from './knowledgeAnimation';
import type {KnowledgeNode} from './knowledge';
import {knowledgeAnimationScene} from './knowledgeAnimationScene';

function plan():KnowledgeAnimation{
  const node=(id:string,kind:KnowledgeNode['kind'],incidentId:string,provenance:KnowledgeNode['provenance']='recorded'):KnowledgeNode=>({id,kind,incidentId,provenance,label:id,value:id,record:id,field:'recorded field',column:0});
  return {graph:{nodes:[node('library:reops','library','','curated'),node('starter:one','experience','','curated'),node('incident:current','incident','current'),node('event:current','action','current'),node('experience:current','experience','current'),node('incident:source','incident','source'),node('experience:source','experience','source'),node('condition:source','condition','source'),node('experience:unrelated','experience','unrelated')],edges:[{from:'library:reops',to:'experience:unrelated',label:'saved experience',field:'original'},{from:'experience:source',to:'incident:current',label:'retrieved for analysis',field:'recorded receipt'},{from:'experience:source',to:'condition:source',label:'requires',field:'original condition'}],omitted:0},frames:[{title:'Current incident',ids:['incident:current']},{title:'Matched source',ids:['experience:source']},{title:'Source conditions',ids:['condition:source']},{title:'Current execution',ids:['event:current']},{title:'Verified save',ids:['experience:current']},{title:'Complete network',ids:['incident:current']}],existingIds:[],networkStep:1};
}
describe('same-network playback visibility',()=>{
  it('keeps the whole starter structure and current fault without the historical gallery',()=>{
    const scene=knowledgeAnimationScene(plan(),'current',0);
    expect(scene.nodes.map(n=>n.id)).toEqual(['library:reops','starter:one','incident:current']);
  });
  it('shows only the currently matched experience and its revealed source evidence',()=>{
    const scene=knowledgeAnimationScene(plan(),'current',2);
    expect(scene.nodes.map(n=>n.id)).toEqual(['library:reops','starter:one','incident:current','incident:source','experience:source','condition:source']);
    expect(scene.edges.some(e=>e.from==='experience:source'&&e.to==='incident:current')).toBe(true);
    expect(scene.edges.every(e=>scene.nodes.some(n=>n.id===e.from)&&scene.nodes.some(n=>n.id===e.to))).toBe(true);
  });
  it('keeps the newly saved experience staged until its real frame',()=>{
    const data=plan();
    expect(knowledgeAnimationScene(data,'current',3).nodes.some(n=>n.id==='experience:current')).toBe(false);
    expect(knowledgeAnimationScene(data,'current',4).nodes.some(n=>n.id==='experience:current')).toBe(true);
    expect(knowledgeAnimationScene(data,'current',4).nodes.some(n=>n.id==='experience:source')).toBe(false);
  });
  it('restores the exact complete graph at completion or an explicit full-network request',()=>{
    const data=plan(),before=JSON.stringify(data);
    expect(knowledgeAnimationScene(data,'current',5)).toBe(data.graph);
    expect(knowledgeAnimationScene(data,'current',0,undefined,true)).toBe(data.graph);
    expect(JSON.stringify(data)).toBe(before);
  });
});
