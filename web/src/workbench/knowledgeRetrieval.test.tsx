import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {describe,it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {fixtureSnapshot} from './contract';
import {ModelConversation} from './ModelConversation';
import {knowledgeRetrieval,beginExperienceLookup,lookupCanContinue,completeExperienceLookup,retrievalFailure} from './knowledgeRetrieval';
import {incidentKnowledgeGraph} from './knowledgeAtlas';

describe('actual knowledge retrieval in API conversation',()=>{
  it('opens retrieval before execution once, without replaying on a historical URL',()=>{
    expect(lookupCanContinue('trace/new')).toBe(false);
    expect(beginExperienceLookup('trace/new')).toBe('/knowledge-retrieval?source=real&trace=trace%2Fnew');
    expect(lookupCanContinue('trace/new')).toBe(true);completeExperienceLookup('trace/new');
    expect(lookupCanContinue('trace/new')).toBe(false);
  });
  it('distinguishes a missing endpoint, missing incident and timeout from a valid miss',()=>{
    expect(retrievalFailure(404).title).toContain('needs an update');
    expect(retrievalFailure(409).title).toContain('Incident record');
    expect(retrievalFailure(408).title).toContain('timed out');
    expect(retrievalFailure(0).message).toContain('No experience match');
  });
  it('shows a local retrieval separately from model replies and links the exact source',()=>{
    const data=fixtureSnapshot(),origin=data.incidents[0],experience=data.experiences.find(e=>e.incident_id===origin.id)!;
    const current={...origin,id:'new-incident',trace_id:'new-trace',experience_ids:[],model_calls:[]};
    const retrieval={profile:'dependency-knowledge-retrieval-v1',incident_id:current.id,trace_id:current.trace_id,status:'hit',duration_ms:2,query:{target_id:current.target_id},matches:[{experience_id:experience.id,incident_id:origin.id,trace_id:origin.trace_id,source_event_id:origin.events[0].id,target_id:origin.target_id,symptom:'Recorded symptom',action:'Recorded advice',used_as:'model_context',execution_applied:false}]};
    const call={...origin.model_calls[0],request:JSON.stringify({trace_id:current.trace_id,knowledge_retrieval:retrieval,http_request:{messages:[{role:'user',content:'Actual prompt with retrieved record'}]}})};
    expect(knowledgeRetrieval(call)?.status).toBe('hit');
    const html=renderToStaticMarkup(<ModelConversation calls={[call]}/>);
    expect(html).toContain('ReOps → Knowledge library');expect(html).toContain('Experience → Model context');
    expect(html).toContain(encodeURIComponent(origin.trace_id));expect(html).toContain('Actual prompt with retrieved record');
    const graph=incidentKnowledgeGraph({...data,incidents:[...data.incidents,{...current,model_calls:[call]}]}, {...current,model_calls:[call]});
    expect(graph.edges.some(e=>e.label==='retrieved for analysis')).toBe(true);
    retrieval.matches[0].source_event_id='missing-source';
    const bad={...call,request:JSON.stringify({trace_id:current.trace_id,knowledge_retrieval:retrieval})};
    expect(incidentKnowledgeGraph({...data,incidents:[...data.incidents,current]}, {...current,model_calls:[bad]}).edges.some(e=>e.label==='retrieved for analysis')).toBe(false);
  });
  it('does not fabricate a hit for a missing or unavailable source',()=>{
    const base=fixtureSnapshot().incidents[0].model_calls[0];
    expect(knowledgeRetrieval(base)).toBe(null);
    for(const status of ['miss','unavailable']){
      const call={...base,request:JSON.stringify({trace_id:'trace',knowledge_retrieval:{profile:'dependency-knowledge-retrieval-v1',trace_id:'trace',status,duration_ms:1,query:{target_id:'target'},matches:[]}})};
      const html=renderToStaticMarkup(<ModelConversation calls={[call]}/>);
      expect(html).toContain(status==='miss'?'No eligible experience':'Knowledge source unavailable');
      expect(html).not.toContain('Experience → Model context');
    }
  });
});
