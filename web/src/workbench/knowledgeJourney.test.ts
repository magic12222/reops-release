import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fixtureSnapshot } from './contract';
import { beginKnowledgeJourney, createKnowledgeCompletionFollower, knowledgeConversationSettled, readKnowledgeSpeed, readyKnowledgeJourney, rememberKnowledgeSpeed, takeKnowledgeJourney } from './knowledgeJourney';
import type { ModelCall } from './contract';

function saved() {
  const data = fixtureSnapshot(); data.source = 'real';
  const incident = data.incidents[0];
  const experience = data.experiences.find(item => item.incident_id === incident.id)!;
  incident.status = 'recovered'; incident.verification.status = 'passed'; experience.status = 'verified';
  incident.events.push({ ...incident.events[0], id: 'save-receipt', stage: 'experience_update', status: 'succeeded' });
  return { data, incident, experience };
}
afterEach(() => vi.unstubAllGlobals());

describe('automatic knowledge presentation after a followed recovery', () => {
  it('requires a verified recovery, linked experience and successful save in the same real incident', () => {
    const { data, incident, experience } = saved();
    expect(readyKnowledgeJourney(data, incident)?.experienceId).toBe(experience.id);
    incident.verification.status = 'pending'; expect(readyKnowledgeJourney(data, incident)).toBeNull();
    incident.verification.status = 'passed'; incident.status = 'failed'; expect(readyKnowledgeJourney(data, incident)).toBeNull();
    incident.status = 'recovered'; experience.status = 'unverified'; expect(readyKnowledgeJourney(data, incident)).toBeNull();
    experience.status = 'verified'; incident.experience_ids = []; expect(readyKnowledgeJourney(data, incident)).toBeNull();
  });
  it('does not navigate for pending persistence, a different target, or sample data', () => {
    const { data, incident, experience } = saved();
    incident.events = incident.events.filter(event => event.stage !== 'experience_update');
    expect(readyKnowledgeJourney(data, incident)).toBeNull();
    incident.events.push({ ...incident.events[0], id: 'pending-save', stage: 'experience_update', status: 'running' });
    expect(readyKnowledgeJourney(data, incident)).toBeNull();
    incident.events.at(-1)!.status = 'succeeded'; experience.target_id = 'other';
    expect(readyKnowledgeJourney(data, incident)).toBeNull();
    data.source = 'offline_fixture'; expect(readyKnowledgeJourney(data, incident)).toBeNull();
  });
  it('leaves history and refresh readable, then follows a new active recovery exactly once', () => {
    const { data, incident } = saved(); const follower = createKnowledgeCompletionFollower();
    const ready = readyKnowledgeJourney(data, incident)!;
    follower.observe(incident, true); expect(follower.eligible(ready)).toBe(false);
    follower.observe({ ...incident, status: 'executing' }, false); expect(follower.eligible(ready)).toBe(false);
    follower.observe({ ...incident, status: 'executing' }, true); expect(follower.eligible(ready)).toBe(true);
    follower.complete(ready); follower.observe({ ...incident, status: 'executing' }, true);
    expect(follower.eligible(ready)).toBe(false);
    expect(createKnowledgeCompletionFollower().eligible(ready)).toBe(false);
  });
  it('continues to allow a second independently followed recovery', () => {
    const { data, incident } = saved(); const follower = createKnowledgeCompletionFollower();
    const first = readyKnowledgeJourney(data, incident)!;
    follower.observe({ ...incident, status: 'verifying' }, true); follower.complete(first);
    const second = { ...first, traceId: 'trace-next', experienceId: 'experience-next', eventId: 'save-next' };
    follower.observe({ ...incident, trace_id: second.traceId, status: 'executing' }, true);
    expect(follower.eligible(second)).toBe(true); expect(follower.eligible(first)).toBe(false);
  });
  it('waits for the real final model round and never blocks a run without model calls', () => {
    const { incident } = saved(); incident.model_calls = [];
    expect(knowledgeConversationSettled(incident)).toBe(true);
    const call = (phase: string, status: ModelCall['status']): ModelCall => ({
      id: phase, model: 'isolated-test', request: JSON.stringify({ analysis_mode: 'dependency-live-conversation-v1', phase }),
      status, response: null, duration_ms: null, input_tokens: null, output_tokens: null, redacted: true,
    });
    incident.model_calls = [call('diagnosis', 'succeeded'), call('progress', 'succeeded')];
    expect(knowledgeConversationSettled(incident)).toBe(false);
    incident.model_calls.push(call('verification', 'running')); expect(knowledgeConversationSettled(incident)).toBe(false);
    incident.model_calls.at(-1)!.status = 'failed'; expect(knowledgeConversationSettled(incident)).toBe(true);
  });
  it('hands off the exact saved experience once, without any external write', () => {
    const { data, incident } = saved(); const journey = readyKnowledgeJourney(data, incident)!;
    const href = beginKnowledgeJourney(journey); const url = new URL(href, 'http://localhost');
    const token = url.searchParams.get('integration');
    expect(url.searchParams.get('knowledge')).toBe('record'); expect(url.searchParams.get('trace')).toBe(incident.trace_id);
    expect(takeKnowledgeJourney(data, 'another-token')).toBeNull();
    expect(takeKnowledgeJourney({ ...data, source: 'offline_fixture' }, token)).toBeNull();
    expect(takeKnowledgeJourney(data, token)).toMatchObject(journey);
    expect(takeKnowledgeJourney(data, token)).toBeNull();
  });
  it('retains a terminal execution when model analysis failed before a verification round existed',()=>{
    const {incident}=saved();incident.status='failed';
    incident.model_calls=[{id:'failed-initial',model:'offline-fixture',status:'failed',request:JSON.stringify({analysis_mode:'dependency-live-conversation-v1',phase:'diagnosis'}),response:null,duration_ms:null,input_tokens:null,output_tokens:null,redacted:true}];
    expect(knowledgeConversationSettled(incident)).toBe(true);
    incident.model_calls[0].status='running';expect(knowledgeConversationSettled(incident)).toBe(false);
  });
  it('retains an explicitly selected playback speed and tolerates unavailable storage', () => {
    const values = new Map<string, string>();
    vi.stubGlobal('sessionStorage', { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) });
    expect(readKnowledgeSpeed()).toBe(2200); rememberKnowledgeSpeed(3600); expect(readKnowledgeSpeed()).toBe(3600);
    rememberKnowledgeSpeed(0); expect(readKnowledgeSpeed()).toBe(3600);
    vi.stubGlobal('sessionStorage', { getItem: () => { throw new Error('disabled'); }, setItem: () => { throw new Error('disabled'); } });
    expect(readKnowledgeSpeed()).toBe(2200); expect(() => rememberKnowledgeSpeed(1000)).not.toThrow();
  });
});
