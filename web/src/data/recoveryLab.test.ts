import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { recoveryLabState } from './recoveryLab';
import { RecoveryTopology } from '../components/RecoveryTopology';
import { RecoveryOutcome } from '../components/RecoveryStage';
import { demoSteps } from './demoData';
import { snapshotAt } from './source';

describe('Recovery Lab evidence boundaries', () => {
  it('withholds business success through execution and post-action checking', () => {
    for (const step of demoSteps.slice(0, 7)) {
      const index = snapshotAt(step.at).index;
      expect(recoveryLabState(index).complete).toBe(false);
      expect(recoveryLabState(index).request).not.toBe('200 OK');
    }
    expect(recoveryLabState(5).database).toBe('recovering');
    expect(recoveryLabState(6).database).toBe('checking');
    expect(recoveryLabState(7)).toMatchObject({ complete: true, database: 'healthy', request: '200 OK' });
  });
  it('keeps healthy API process and Redis separate from a failed business dependency', () => {
    const html = renderToStaticMarkup(createElement(RecoveryTopology, { index: 3, moving: false }));
    expect(html).toContain('进程存活');
    expect(html).toContain('503 ERROR');
    expect(html).toContain('lab-redis');
    expect(html).toContain('根因 / POSTGRESQL');
    expect(html).not.toContain('Worker');
    expect(html).not.toContain('概念节点');
    expect(html).not.toContain('lab-concept-wire');
    expect(html).not.toContain('latency');
    expect(html).toContain('非实时探测');
  });
  it('maps all existing events without dropping intermediate diagnosis and decision', () => {
    expect([-1, 0, 1, 2, 3, 4, 5, 6, 7].map(index => recoveryLabState(index).stage)).toEqual([0, 1, 2, 2, 2, 2, 3, 4, 4]);
    expect(recoveryLabState(2).evidence).toContain('Connection refused');
    expect(recoveryLabState(4).evidence).toContain('restart_service');
  });
  it('keeps the outcome unverified when the operation and follow-up checks are pending', () => {
    for (const index of [0, 3, 4, 5, 6]) {
      const html = renderToStaticMarkup(createElement(RecoveryOutcome, { index }));
      expect(html).not.toContain('服务与业务验证均通过');
      expect(html).not.toContain('503 → 200');
    }
    const html = renderToStaticMarkup(createElement(RecoveryOutcome, { index: 7 }));
    expect(html).toContain('503 → 200');
    expect(html).toContain('服务与业务验证均通过');
  });
});
