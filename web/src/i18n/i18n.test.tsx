import { afterEach, describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { setLocale, translate } from './index';
import { messages } from './messages';
import { workspaceMessages } from './workspaceMessages';
import { HeroSystem } from '../components/HeroSystem';
import { ArchitectureFlow, ArchitectureNodeDetail } from '../components/ArchitectureFlow';
import { architectureViews } from '../data/architecture';
import { RecoveryDemo } from '../components/RecoveryDemo';
import { RecoveryOutcome } from '../components/RecoveryStage';
import { Benchmark } from '../components/Benchmark';
import { LiveRecoveryView, type LiveRecoveryViewProps } from '../components/LiveRecovery';
import { agentFixtures } from '../data/agentFixtures';
import { agentValueName } from '../data/agentDisplay';
import { evidenceFactText } from '../data/evidencePresentation';
import { toReadTrace } from '../data/adapter';
import { architectureLayerPurposes, architectureNodeDescriptions } from '../data/architecturePresentation';
import { architectureLayers, systemNodes } from '../data/demoData';
import { overviewStory } from '../data/overviewStory';
import { heroNodeDetail, heroNodeState, heroStages } from '../data/heroSimulation';
import { recoveryLabState } from '../data/recoveryLab';
import { benchmarkMetrics, sampleDifference } from '../data/benchmarkStudio';

afterEach(() => setLocale('zh-CN'));

describe('UI translation coverage', () => {
  it('has complete entries and preserves interpolation parameters in both languages', () => {
    for (const entry of Object.values(messages)) {
      expect(entry['zh-CN']?.trim()).toBeTruthy();
      expect(entry.en?.trim()).toBeTruthy();
      const slots = (text: string) => (text.match(/\{\d+\}/g) ?? []).sort();
      expect(slots(entry.en!)).toEqual(slots(entry['zh-CN']!));
    }
  });

  it('covers Chinese presentation data used by every main page', () => {
    const displayed = [
      ...architectureViews.flatMap(layer => [layer.name, layer.label, layer.summary, architectureLayerPurposes[layer.id],
        ...layer.nodes.flatMap(node => [node.name, node.tag, architectureNodeDescriptions[node.id]]),
        ...layer.edges.map(edge => edge.label)]),
      ...architectureLayers.flatMap(layer => [layer.state, layer.description, ...layer.modules.map(module => module.name)]),
      ...overviewStory.flatMap(stage => [stage.word, stage.sub, stage.detail, stage.readout, ...Object.values(stage.nodes)]),
      ...heroStages.flatMap(stage => [stage.title, stage.label, ...systemNodes.flatMap(node =>
        [heroNodeState(stage.phase, node.id).label, heroNodeDetail(node.id).role, heroNodeDetail(node.id).conceptual])]),
      ...Array.from({ length: 9 }, (_, index) => recoveryLabState(index - 1)).flatMap(state => [state.title, state.description, state.evidence]),
      ...benchmarkMetrics.flatMap(metric => [metric.label, metric.shortLabel, metric.direction, metric.caveat]),
    ];
    for (const value of displayed) if (typeof value === 'string' && /\p{Script=Han}/u.test(value)) {
      expect(messages[value.trim()]?.en ?? workspaceMessages[value.trim()]?.en, value).toBeTruthy();
    }
  });

  it('uses Chinese for a missing English translation and keeps unknown source text intact', () => {
    messages['test.missing'] = { 'zh-CN': '中文回退' };
    try { expect(translate('test.missing', 'en')).toBe('中文回退'); }
    finally { delete messages['test.missing']; }
    for (const source of ['__proto__', 'unknown UI message', 'postgres_service_down', 'run-123']) {
      expect(translate(source, 'en')).toBe(source);
    }
    expect(translate('缺失/未知 {0} 项', 'en', 3)).toBe('3 missing/unknown items');
  });

  it('renders actual page headings and descriptions in both languages', () => {
    for (const [locale, expected] of [
      ['zh-CN', ['从证据出发', '为恢复而构建', '让一个依赖失效', '恢复方案，放在同一尺度上']],
      ['en', ['Start with evidence', 'Built to recover.', 'Fail a dependency', 'Compare recovery strategies on the same scale.']],
    ] as const) {
      setLocale(locale);
      const pages = [<HeroSystem />, <ArchitectureFlow />, <RecoveryDemo />, <Benchmark />];
      pages.forEach((page, index) => expect(renderToStaticMarkup(page)).toContain(expected[index]));
    }
  });

  it('localizes all architecture node descriptions without changing source data', () => {
    const before = JSON.stringify(architectureViews);
    setLocale('en');
    for (const layer of architectureViews) for (const node of layer.nodes) {
      const html = renderToStaticMarkup(<ArchitectureNodeDetail node={node} onClose={() => {}} />);
      expect(html).not.toMatch(/\p{Script=Han}/u);
    }
    expect(JSON.stringify(architectureViews)).toBe(before);
  });

  it('updates dynamic verification labels while retaining unknown protocol values', () => {
    setLocale('en');
    expect(agentValueName('root_cause', 'postgres_service_down')).toBe('PostgreSQL service unavailable');
    expect(agentValueName('root_cause', 'future_root_cause')).toBe('future_root_cause');
    expect(evidenceFactText({ key: 'health_check_passed', label: '', value: false })).toBe('Not passed');
    expect(sampleDifference({ toolCalls: 3 }, { toolCalls: 1 }, benchmarkMetrics[2])).toBe('+2 calls');
    expect(renderToStaticMarkup(<RecoveryOutcome index={6} />)).toContain('Awaiting verification');
    expect(renderToStaticMarkup(<RecoveryOutcome index={7} />)).toContain('Service and business verification passed');
    setLocale('zh-CN');
    expect(evidenceFactText({ key: 'health_check_passed', label: '', value: false })).toBe('未通过');
    expect(sampleDifference({ toolCalls: 3 }, { toolCalls: 1 }, benchmarkMetrics[2])).toBe('+2 调用');
  });

  it('localizes Agent states and controls while preserving every original fixture event', () => {
    const before = JSON.stringify(agentFixtures);
    for (const locale of ['en', 'zh-CN'] as const) {
      setLocale(locale);
      for (const fixture of agentFixtures) for (const event of fixture.events) {
        const props: LiveRecoveryViewProps = {
          source: 'offline_fixture', onSource: () => {}, onRefresh: () => {},
          selectedId: fixture.run.id, onSelectRun: () => {}, selectedEventId: event.event_id,
          onSelectEvent: () => {}, connection: 'off', status: { kind: 'idle' },
          runs: { kind: 'ready', data: { items: [fixture.run], total: 1, offset: 0, limit: 50 } },
          detail: { kind: 'ready', data: { run: fixture.run, trace: toReadTrace(fixture.run, fixture.events) } },
        };
        const html = renderToStaticMarkup(<LiveRecoveryView {...props} />);
        expect(html).toContain(locale === 'en' ? 'Read-only playback' : '只读回放');
        expect(html).toContain(locale === 'en' ? 'Previous historical event' : '上一个历史事件');
        const decode = (value: string) => value.replaceAll('&quot;', '"').replaceAll('&#x27;', "'")
          .replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&');
        const records = [...html.matchAll(/<pre>([\s\S]*?)<\/pre>/g)].flatMap(match => {
          try { return [JSON.parse(decode(match[1]))]; } catch { return []; }
        });
        expect(records).toContainEqual(event);
      }
    }
    expect(JSON.stringify(agentFixtures)).toBe(before);
  });
});
