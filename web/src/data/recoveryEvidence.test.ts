import { describe, expect, it } from 'vitest';
import { recoveryEvidence } from './recoveryEvidence';
import { demoSteps } from './demoData';

describe('current Recovery evidence', () => {
  it('does not promote preset actions or verification before their events are reached', () => {
    expect(recoveryEvidence(demoSteps, -1)).toEqual([]);
    expect(recoveryEvidence(demoSteps, 0)).toEqual([{ kind: 'failure', title: '故障依据', content: demoSteps[0].event.data.input, detail: demoSteps[0].event.data.result }]);
    expect(recoveryEvidence(demoSteps, 4).map(item => item.kind)).toEqual(['failure']);
    expect(recoveryEvidence(demoSteps, 5).map(item => item.kind)).toEqual(['failure', 'action']);
  });
  it('reads actual event fields, rather than supplying the canned scenario evidence', () => {
    const steps = demoSteps.map(step => ({ ...step, event: { ...step.event, data: { ...step.event.data } } }));
    steps[2].event.data.result = 'Recorded connection failure at another endpoint';
    steps[5].event.data.tool = 'recorded_action(target)';
    steps[5].event.data.result = 'Recorded executor rejected action';
    const items = recoveryEvidence(steps, 5);
    expect(items[0].content).toBe(steps[2].event.data.result);
    expect(items[1]).toMatchObject({ content: 'recorded_action(target)', detail: 'Recorded executor rejected action' });
  });
  it('withholds a passed result until the completion record is reached and withdraws it on rewind', () => {
    expect(recoveryEvidence(demoSteps, 6)[2].content).toContain('尚未确认通过');
    expect(recoveryEvidence(demoSteps, 6)[2].content).not.toContain('business: 200');
    expect(recoveryEvidence(demoSteps, 6)[2].detail).toBe(demoSteps[6].event.data.tool);
    expect(recoveryEvidence(demoSteps, 7)[2].content).toBe(demoSteps[6].event.data.result);
    expect(recoveryEvidence(demoSteps, 3).map(item => item.kind)).toEqual(['failure']);
  });
  it('keeps failures and missing fields honest even if a later completion event says success', () => {
    const steps = demoSteps.map(step => ({ ...step, event: { ...step.event, data: { ...step.event.data } } }));
    steps[6].event.status = 'failed';
    steps[6].event.data.result = 'Recorded business probe failed';
    expect(recoveryEvidence(steps, 7)[2].content).toBe('验证失败 · Recorded business probe failed');
    steps[5].event.data = {};
    expect(recoveryEvidence(steps, 5)[1].content).toBe('此执行事件未提供动作内容。');
    expect(recoveryEvidence(steps, 5)[1].detail).toBe('执行事件状态：成功');
  });
  it('does not use a completion record from another trace to confirm verification', () => {
    const steps = demoSteps.map(step => ({ ...step, event: { ...step.event } }));
    steps[7].event.trace_id = 'another-trace';
    expect(recoveryEvidence(steps, 7)[2].content).toContain('尚未确认通过');
  });
});
