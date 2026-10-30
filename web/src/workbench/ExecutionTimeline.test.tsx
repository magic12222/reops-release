import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {describe,it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {ExecutionTimeline} from './ExecutionTimeline';
import {ModelConversation,conversationMessages,requestPreview,typewriterStep} from './ModelConversation';
import {DependencyDiagnosisControl,hasAutomaticConversation,needsLiveAnalysis} from './DependencyDiagnosisControl';
import {fixtureSnapshot} from './contract';

describe('generic execution and actual API messages',()=>{
  it('keeps completed, unknown and authorization-waiting history read-only even with eligible evidence',()=>{
    const base=fixtureSnapshot().incidents[0];
    for(const status of ['recovered','failed','unknown','waiting_human'] as const){
      const incident={...base,status,target_id:'reops-vikunja-demo',model_calls:[],events:base.events.map(e=>({...e,evidence:['profile=dependency-audit-v1']}))};
      expect(needsLiveAnalysis(incident)).toBe(false);
      expect(renderToStaticMarkup(<DependencyDiagnosisControl incident={incident} active onChanged={()=>{}}/>)).toBe('');
    }
  });
  it('retains ongoing dependency analysis while excluding mixed evidence and already recorded conversations',()=>{
    const base=fixtureSnapshot().incidents[0];
    const incident={...base,status:'verifying' as const,target_id:'reops-vikunja-demo',model_calls:[],events:base.events.map(e=>({...e,evidence:['profile=dependency-audit-v1']}))};
    expect(needsLiveAnalysis(incident)).toBe(true);
    expect(needsLiveAnalysis({...incident,events:[...incident.events,{...incident.events[0],evidence:[]}]})).toBe(false);
    expect(needsLiveAnalysis({...incident,target_id:'other-target'})).toBe(false);
    expect(needsLiveAnalysis({...incident,model_calls:[{...base.model_calls[0],request:JSON.stringify({analysis_mode:'dependency-live-conversation-v1'})}]})).toBe(false);
  });
  it('supports service-independent stages and animates only an explicitly active event',()=>{
    const events=fixtureSnapshot().incidents[0].events;
    const html=renderToStaticMarkup(<ExecutionTimeline events={events} currentId={events[1].id} onSelect={()=>{}}/>);
    expect(html.match(/data-running="true"/g)).toHaveLength(1);
    expect(html).toContain('Succeeded · latest signal');
    expect(html).not.toContain('Working now');
    const inactive=renderToStaticMarkup(<ExecutionTimeline events={events} currentId={events[1].id} active={false} onSelect={()=>{}}/>);
    expect(inactive).not.toContain('data-running="true"');
    expect(renderToStaticMarkup(<ExecutionTimeline events={[]} onSelect={()=>{}}/>)).not.toContain('<li');
  });
  it('shows exact request roles and model text without generated conversation',()=>{
    const call={id:'actual-test-call',model:'fixture-model',status:'succeeded' as const,request:JSON.stringify({http_request:{messages:[{role:'system',content:'Exact system instruction'},{role:'user',content:'Exact user payload'}]}}),response:JSON.stringify({content:'Actual model reply',usage:{prompt_tokens:13}}),duration_ms:100,input_tokens:13,output_tokens:null,redacted:true as const};
    expect(conversationMessages(call)).toEqual([{role:'system',content:'Exact system instruction'},{role:'user',content:'Exact user payload'},{role:'assistant',content:'Actual model reply'}]);
    const html=renderToStaticMarkup(<ModelConversation calls={[call]}/>);
    expect(html).toContain('Exact user payload');expect(html).toContain('Actual model reply');expect(html).toContain('Output Unknown tokens');
    call.response='';expect(conversationMessages(call).some(item=>item.role==='assistant')).toBe(false);
  });
  it('does not animate an abandoned pending request as live work',()=>{
    const call={id:'abandoned',model:'fixture',status:'running' as const,request:JSON.stringify({requested_at:'2020-01-01T00:00:00Z'}),response:null,duration_ms:null,input_tokens:null,output_tokens:null,redacted:true as const};
    const html=renderToStaticMarkup(<ModelConversation calls={[call]}/>);
    expect(html).toContain('outcome unknown');expect(html).toContain('data-animate="false"');
  });
  it('keeps application errors out of the assistant bubble and preserves actual partial replies',()=>{
    const call={id:'failed',model:'fixture',status:'unknown' as const,request:'Actual prompt',response:'Model request failed or response invalid. Budget consumed; no retry and no recovery action.',duration_ms:359,input_tokens:null,output_tokens:null,redacted:true as const};
    expect(conversationMessages(call)).toEqual([{role:'user',content:'Actual prompt'}]);
    const html=renderToStaticMarkup(<ModelConversation calls={[call]}/>);
    expect(html).not.toContain('Model → ReOps');expect(html).toContain('execution-model-error');
    call.response=JSON.stringify({content:'Actual partial reply',error:'stream_interrupted'});
    expect(conversationMessages(call).at(-1)?.content).toBe('Actual partial reply');
  });
  it('shows a compact request without losing the exact source payload',()=>{
    const call={...fixtureSnapshot().incidents[0].model_calls[0],request:JSON.stringify({analysis_mode:'dependency-conversation-v2',request_summary:'Brief actual request',http_request:{messages:[{role:'user',content:'Full actual payload'}]}})};
    expect(requestPreview(call,'Full actual payload')).toBe('Brief actual request');
    const html=renderToStaticMarkup(<ModelConversation calls={[call]}/>);
    expect(html).toContain('Brief actual request');expect(html).toContain('Full actual payload');
    expect(html).toContain('Replay conversation');
    expect(hasAutomaticConversation({...fixtureSnapshot().incidents[0],model_calls:[call]})).toBe(true);
  });
  it('reveals incoming text progressively and never advances beyond the actual reply',()=>{
    expect(typewriterStep(0,300)).toBeGreaterThan(0);
    expect(typewriterStep(0,300)).toBeLessThan(300);
    expect(typewriterStep(299,300)).toBe(300);
    expect(typewriterStep(300,300)).toBe(300);
  });
  it('shows real multi-turn rounds together without duplicating their chat history',()=>{
    const base=fixtureSnapshot().incidents[0].model_calls[0];
    const first={...base,id:'live-first',status:'succeeded' as const,
      request:JSON.stringify({analysis_mode:'dependency-live-conversation-v1',round:1,phase:'diagnosis',http_request:{messages:[{role:'user',content:'First observation'}]}}),
      response:JSON.stringify({content:'First real reply'})};
    const second={...base,id:'live-second',status:'running' as const,
      request:JSON.stringify({analysis_mode:'dependency-live-conversation-v1',round:2,phase:'progress',http_request:{messages:[{role:'user',content:'First observation'},{role:'assistant',content:'First real reply'},{role:'user',content:'Actual SQL is ready'}]}}),
      response:JSON.stringify({content:'Second actual partial reply'})};
    expect(conversationMessages(second)).toEqual([{role:'user',content:'Actual SQL is ready'},{role:'assistant',content:'Second actual partial reply'}]);
    const html=renderToStaticMarkup(<ModelConversation calls={[first,second]}/>);
    expect(html).toContain('Round 1');expect(html).toContain('Round 2');
    expect(html).toContain('First real reply');expect(html).toContain('Second actual partial reply');
    expect(html).not.toContain('Earlier model requests');
  });
});
