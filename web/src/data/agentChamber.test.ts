import { describe, expect, it } from 'vitest';
import { agentFixtures } from './agentFixtures';
import { chamberPresentation } from './agentChamber';
import { setLocale } from '../i18n';

describe('Agent evidence chamber record fidelity', () => {
  it.each(['zh-CN', 'en'] as const)('localizes display labels while preserving original evidence and key collisions in %s', locale => {
    try {
      setLocale(locale);
      const original = agentFixtures[0].events.find(event => event.stage === 'root_cause_analysis')!;
      const view = chamberPresentation(original);
      expect(view.secondary).toBe(locale === 'en' ? 'Service unavailable' : '服务不可用');
      expect(view.signals[2].display).toBe(locale === 'en' ? 'Unhealthy' : '不健康');
      expect(view.signals.map(signal => signal.value)).toEqual(original.data.evidence);
      const event = { ...original, data: { root_cause: null, evidence: ['Unknown', 'Succeeded', '未知'] } };
      const before = JSON.stringify(event);
      expect(chamberPresentation(event).signals.map(signal => signal.display)).toEqual(event.data.evidence);
      expect(JSON.stringify(event)).toBe(before);
    } finally { setLocale('zh-CN'); }
  });
  it('unpacks a recorded diagnosis into three independently inspectable original evidence items', () => {
    const event = agentFixtures[0].events.find(event => event.stage === 'root_cause_analysis')!;
    const original = structuredClone(event), view = chamberPresentation(event);
    expect(view.primary).toBe('PostgreSQL');
    expect(view.secondary).toBe('服务不可用');
    expect(view.signals.map(signal => signal.value)).toEqual(event.data.evidence);
    expect(view.signals.map(signal => signal.display)).toEqual(['HTTP 500', '连接被拒绝', '不健康']);
    expect(event).toEqual(original);
    expect(chamberPresentation({ ...event, origin: 'decision_trace', data: { value: event.data } })).toEqual(view);
  });
  it('does not manufacture a diagnosis or evidence for an incomplete event', () => {
    const event = agentFixtures[2].events[1];
    const view = chamberPresentation(event);
    expect(view.primary).toBe('故障定位');
    expect(view.signals).toEqual([]);
    expect(view.secondary).not.toContain('成功');
    expect(chamberPresentation({ ...event, stage: 'root_cause_analysis', data: { root_cause: null } }).primary).toBe('根因分析');
  });
  it('preserves negated and unfamiliar evidence without promoting an HTTP value to a false conclusion', () => {
    const event = { ...agentFixtures[0].events[3], data: { root_cause: null, evidence: [
      'HTTP 500 not observed', 'API log contains no connection refused signal.', 'Expected HTTP 200; received HTTP 503',
    ] } };
    const view = chamberPresentation(event);
    expect(view.signals.map(signal => signal.display)).toEqual(event.data.evidence);
    expect(view.primary).toBe('根因分析');
  });
  it('keeps failed verification checks visible ahead of supplementary evidence', () => {
    const view = chamberPresentation(agentFixtures[1].events.at(-1)!);
    expect(view.signals).toHaveLength(3);
    expect(view.signals.every(signal => signal.value === false && signal.display !== '通过')).toBe(true);
    expect(view.primary).toContain('未恢复');
  });
});
