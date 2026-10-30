import { afterEach, describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { Navbar } from '../components/Navbar';
import { WorkbenchView } from '../pages/WorkbenchPage';
import { ExecutionPage } from '../pages/ExecutionPage';
import { KnowledgeRetrievalPage } from '../pages/KnowledgeRetrievalPage';
import { ApiPage } from '../pages/ApiPage';
import { KnowledgeExplorer } from '../workbench/KnowledgeExplorer';
import { ExecutionTimeline } from '../workbench/ExecutionTimeline';
import { ModelConversation } from '../workbench/ModelConversation';
import { RecordedEventBrowser, IncidentOverview } from '../workbench/WorkbenchIncidentEvidence';
import { IncidentFlow } from '../workbench/IncidentFlow';
import { RunOutcome } from '../pages/execution/ExecutionEvidence';
import { fixtureSnapshot } from '../workbench/contract';
import { globalKnowledgeGraph } from '../workbench/knowledgeAtlas';
import { setLocale } from '../i18n';
import { workspaceMessages } from '../i18n/workspaceMessages';
import { pages, resolveRoute } from './routes';

afterEach(() => setLocale('zh-CN'));

describe('candidate navigation restored without replacing existing pages', () => {
  it('exposes all nine candidate destinations in both languages', () => {
    expect(pages.map(page => page.href)).toEqual(['/', '/workbench', '/execution', '/knowledge-retrieval', '/architecture', '/agent', '/recovery', '/benchmark', '/api']);
    for (const locale of ['zh-CN', 'en'] as const) {
      setLocale(locale);
      const html = renderToStaticMarkup(<Navbar />);
      for (const page of pages) expect(html).toContain(`href="${page.href}"`);
      for (const text of locale === 'en' ? ['Workbench', 'Execution', 'Knowledge', 'API'] : ['工作台', '执行', '知识', 'API']) expect(html).toContain(text);
    }
  });

  it('keeps direct routes, exact traces and local knowledge views independent of locale', () => {
    for (const locale of ['zh-CN', 'en'] as const) {
      setLocale(locale);
      for (const path of ['/workbench', '/execution', '/knowledge-retrieval', '/api']) {
        const url = path + '?source=real&trace=trace-exact';
        expect(resolveRoute(new URL(url, 'http://localhost')).href).toBe(url);
      }
      expect(resolveRoute(new URL('http://localhost/workbench?knowledge=record')).page).toBe('workbench');
      expect(resolveRoute(new URL('http://localhost/knowledge-retrieval')).page).toBe('knowledge-retrieval');
    }
  });

  it('renders the restored pages as real components in both languages', () => {
    const data = fixtureSnapshot();
    for (const locale of ['zh-CN', 'en'] as const) {
      setLocale(locale);
      const workbench = renderToStaticMarkup(<WorkbenchView mode="offline_fixture" data={data} loading={false} error={false}
        targetId={data.targets[0].id} incidentId={data.incidents[0].id} eventId={null} tab="trajectory"
        onMode={() => {}} onRefresh={() => {}} onTarget={() => {}} onIncident={() => {}} onEvent={() => {}} onTab={() => {}} active={false} />);
      expect(workbench).toContain(locale === 'en' ? 'Operations ' : '运维 ');
      expect(workbench).toContain(data.incidents[0].title);
      expect(renderToStaticMarkup(<ExecutionPage active={false} />)).toContain(locale === 'en' ? 'Execution ' : '执行 ');
      expect(renderToStaticMarkup(<KnowledgeRetrievalPage active={false} />)).toContain(locale === 'en' ? 'Knowledge' : '知识');
      expect(renderToStaticMarkup(<ApiPage />)).toContain(locale === 'en' ? 'API Management' : 'API 管理');
    }
  });

  it('translates knowledge nodes before splitting their visual lines and supports Chinese search', () => {
    const data = fixtureSnapshot(), original = JSON.stringify(data);
    setLocale('zh-CN');
    const graph = globalKnowledgeGraph(data, data.experiences, false, undefined, '数据库');
    expect(graph.nodes.some(node => node.id === 'starter:postgres-startup')).toBe(true);
    setLocale('en');
    expect(globalKnowledgeGraph(data, data.experiences, false, undefined, '数据库').nodes.some(node => node.id === 'starter:postgres-startup')).toBe(true);
    setLocale('zh-CN');
    const html = renderToStaticMarkup(<KnowledgeExplorer data={data} targetId="" incidentId={null} active={false}
      initiallyUnselected autoIntegrate={false} onEvent={() => {}} onIncident={() => {}} />);
    expect(html).toContain('数据库就绪后恢复');
    expect(html).toContain('选择节点以查看详情和来源');
    expect(JSON.stringify(data)).toBe(original);
  });

  it('localizes dynamic event labels while retaining raw event status and original model payloads', () => {
    const data = fixtureSnapshot(), incident = data.incidents[0], before = JSON.stringify(data);
    for (const locale of ['zh-CN', 'en'] as const) {
      setLocale(locale);
      const html = renderToStaticMarkup(<ExecutionTimeline events={incident.events} onSelect={() => {}} active={false} />);
      expect(html).toContain(locale === 'en' ? 'Succeeded' : '成功');
      expect(html).toContain('data-status="succeeded"');
      expect(html).toContain(incident.events[0].title);
      const call = incident.model_calls[0];
      if (call) {
        const model = renderToStaticMarkup(<ModelConversation calls={[call]} active={false} />);
        const escape = (value: string) => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#x27;');
        expect(model).toContain(escape(call.request));
        if (call.response) expect(model).toContain(escape(call.response));
      }
    }
    expect(JSON.stringify(data)).toBe(before);
  });

  it('has complete restored-page resources with compatible placeholders', () => {
    for (const value of Object.values(workspaceMessages)) {
      expect(value['zh-CN']?.trim()).toBeTruthy();
      expect(value.en?.trim()).toBeTruthy();
      const slots = (text: string) => (text.match(/\{\d+\}/g) ?? []).sort();
      expect(slots(value['zh-CN']!)).toEqual(slots(value.en!));
    }
  });

  it('keeps raw values even when they collide with translation keys and translates generated counts', () => {
    const data = fixtureSnapshot(), incident = data.incidents[0];
    incident.verification.checks = ['Unknown'];
    incident.events[0].title = 'Succeeded';
    incident.events[0].evidence = ['Unknown'];
    const model = { id: 'Unknown', model: 'Unknown', status: 'succeeded' as const, request: 'Unknown',
      response: 'Unknown', duration_ms: null, input_tokens: null, output_tokens: null, redacted: true as const };
    for (const locale of ['zh-CN', 'en'] as const) {
      setLocale(locale);
      const conversation = renderToStaticMarkup(<ModelConversation calls={[model]} active={false} />);
      expect(conversation).toContain('execution-typewriter">Unknown<span');
      expect(conversation).toContain('<pre>Unknown</pre>');
      const evidence = renderToStaticMarkup(<RecordedEventBrowser incident={incident} event={incident.events[0]}
        open onOpen={() => {}} onEvent={() => {}} />);
      expect(evidence).toContain('<li>Unknown</li>');
      expect(renderToStaticMarkup(<IncidentOverview incident={incident} />)).toContain('<li>Unknown</li>');
      expect(renderToStaticMarkup(<RunOutcome incident={incident} onSelect={() => {}} />)).toContain('<span>Unknown</span>');
      const flow = renderToStaticMarkup(<IncidentFlow data={data} incident={incident} target={data.targets[0]}
        onEvent={() => {}} onKnowledge={() => {}} />);
      expect(flow).toContain(locale === 'zh-CN' ? '条模型记录' : 'model records');
      expect(flow).toContain('<li>Unknown</li>');
      expect(flow).toContain('<span>Succeeded</span>');
    }
  });
});
