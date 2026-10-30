import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fixtureSnapshot } from '../workbench/contract';
import { WorkbenchPage, WorkbenchView } from './WorkbenchPage';

const location=vi.hoisted(()=>({href:'/workbench'}));
vi.mock('../navigation/router',()=>({useRoute:()=>({...location,page:'workbench'}),navigate:vi.fn()}));
beforeEach(()=>{location.href='/workbench';});

const callbacks = { onMode: () => {}, onRefresh: () => {}, onTarget: () => {}, onIncident: () => {}, onEvent: () => {}, onTab: () => {} };
const render = (extra = {}) => renderToStaticMarkup(<WorkbenchView mode="offline_fixture" data={fixtureSnapshot()} loading={false} error={false}
  targetId="fixture-local-api" incidentId="fixture-incident-01" eventId={null} tab="trajectory" {...callbacks} {...extra} />);

describe('unified workbench', () => {
  it('derives sample content and disabled controls from the route source',()=>{
    location.href='/workbench?source=offline_fixture';
    const html=renderToStaticMarkup(<WorkbenchPage/>);
    expect(html).toContain('SAMPLE DATA · NOT A LIVE RUN');
    expect(html).not.toContain('ResearchLoop recovery run');
    expect(html).toContain(fixtureSnapshot().incidents[0].trace_id);
  });
  it('honors an exact sample trace on first render and never substitutes another trace',()=>{
    const data=fixtureSnapshot();
    location.href='/workbench?source=offline_fixture&trace='+data.incidents[1].trace_id;
    expect(renderToStaticMarkup(<WorkbenchPage/>)).toContain(data.incidents[1].id);
    location.href='/workbench?source=offline_fixture&trace=missing-trace';
    const html=renderToStaticMarkup(<WorkbenchPage/>);
    expect(html).not.toContain('Full incident record');
    expect(html).not.toContain(data.incidents[0].trace_id);
  });
  it('exposes follow ownership only for an active connected workspace',()=>{
    expect(render({following:true})).toContain('data-following="true"');
    expect(render({following:true,error:true})).toContain('data-following="false"');
    expect(render({following:true,active:false})).toContain('data-following="false"');
  });
  it('uses English throughout the workbench and sample content', () => {
    for (const tab of ['trajectory', 'api', 'memory']) expect(render({ tab })).not.toMatch(/[\u4e00-\u9fff]/);
  });
  it('labels samples and disables controls instead of pretending to monitor', () => {
    const html = render();
    expect(html).toContain('SAMPLE DATA · NOT A LIVE RUN');
    expect(html).toContain('Verify business recovery');
    expect(html).toMatch(/disabled=""[^>]*>Start monitoring · Not connected/);
  });
  it('shows recorded request and response and preserves unknown usage', () => {
    const data = fixtureSnapshot(); data.incidents[0].model_calls[0].input_tokens = null;
    const html = render({ data, tab: 'api' });
    expect(html).toContain('process_running'); expect(html).toContain('connection_refused');
    expect(html).toContain('api_process_exited'); expect(html).toContain('Unknown');
  });
  it('does not fabricate a model dialogue for the experience path', () => {
    const html = render({ tab: 'api', incidentId: 'fixture-incident-02' });
    expect(html).toContain('Experience-based recovery');
    expect(html).not.toContain('api_process_exited');
  });
  it('ties the graph and experience to an origin record', () => {
    const html = render({ tab: 'memory', incidentId: 'fixture-incident-02' });
    expect(html).toContain('fixture-exp-01'); expect(html).toContain('Conditions');
    expect(html).toContain('View source incident');
  });
  it('renders disconnected and error states without sample content', () => {
    const disconnected = { ...fixtureSnapshot(), source: 'real', a_status: 'not_connected', b_status: 'not_connected', targets: [], incidents: [], experiences: [] };
    const html = render({ mode: 'real', data: disconnected, targetId: null, incidentId: null });
    expect(html).toContain('Connect your first application'); expect(html).not.toContain('首次故障');
    const error = render({ mode: 'real', data: null, error: true });
    expect(error).toContain('Sample data has not been substituted'); expect(error).not.toContain('首次故障');
  });
  it('exposes workflow gaps and the starter library without inventing B records before the first incident', () => {
    const data = { ...fixtureSnapshot(), source: 'real', b_status: 'not_connected', incidents: [], experiences: [] };
    const html = render({ mode: 'real', data, incidentId: null, tab: 'memory' });
    expect(html).toContain('ReOps starter library');
    expect(html).toContain('No runtime experience matches');
    expect(html).not.toContain('View source incident');
    expect(html).toContain('No incidents recorded');
    expect(html).not.toContain('SAMPLE GRAPH');
  });
  it('keeps current unhealthy observations separate from a recovered historical incident', () => {
    const data = fixtureSnapshot(); data.targets[0].health = 'unhealthy';
    const html = render({ data });
    expect(html).toContain('Unhealthy'); expect(html).toContain('Recovered');
    expect(html).toContain('Recorded result only');
    expect(html).toContain('RECORDED INCIDENT');
    expect(html).toContain('Full incident record');
    expect(html).toContain(data.incidents[0].trace_id);
  });
  it('defaults to a quiet empty history with knowledge still available on demand', () => {
    const data = { ...fixtureSnapshot(), incidents: [], experiences: [] };
    const html = render({ data, incidentId: null });
    expect(html).toContain('No incidents recorded');
    expect(html).toContain('Memory &amp; graph');
    expect(html).not.toContain('ReOps starter library');
  });
  it('starts with verification and a closed event browser, retaining event selection and originals',()=>{
    const html=render();
    expect(html).toContain('Recorded business verification');
    expect(html).toMatch(/<details class="wb-recorded-events">/);
    expect(html).not.toContain('EVENT FOCUS');
    expect(html).not.toContain('chamber-space');
    expect(html).toContain('Selected recorded event');
    expect(html).toContain('Inspect execution');
    for(const event of fixtureSnapshot().incidents[0].events)expect(html).toContain(event.id);
  });
  it('retains long audit text behind provenance and distinguishes rule recovery from model diagnosis',()=>{
    const data=fixtureSnapshot();data.incidents[0].summary='BStore read-model persistence; original audit is unchanged. This does not establish a B model or legacy Memory loop.';
    data.incidents[0].diagnosis_source='rule';data.incidents[0].model_calls=[];
    const html=render({data});
    expect(html).toContain('Rule-based recovery');
    expect(html).toMatch(/<details class="wb-incident-provenance"><summary>Incident summary &amp; provenance/);
    expect(html).toContain(data.incidents[0].summary);
    expect(html).toContain('None recorded · total usage unknown');
    expect(html).not.toContain('Model-based diagnosis');
  });
});
