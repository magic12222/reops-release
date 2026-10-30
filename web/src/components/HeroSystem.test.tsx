import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { advanceHeroClock, heroCycleDuration, heroEdgeKind, heroNeighbors, heroNodeState, heroStageAt, heroStages } from '../data/heroSimulation';
import { HeroSystem } from './HeroSystem';
import { SystemTopology } from './SystemTopology';

describe('Hero simulation', () => {
  it('has four stable ordered stages and wraps the presentation clock', () => {
    expect(heroStages.map(stage => heroStageAt(stage.at).phase)).toEqual(['healthy', 'failed', 'reason', 'recovered']);
    expect(heroStageAt(2199).index).toBe(0);
    expect(heroStageAt(2200).index).toBe(1);
    expect(heroStageAt(8599).index).toBe(2);
    expect(heroStageAt(8600).index).toBe(3);
    expect(heroStageAt(heroCycleDuration).index).toBe(0);
    expect(advanceHeroClock(11000, 300)).toBe(100);
    expect(advanceHeroClock(4600, 0)).toBe(4600);
    expect(advanceHeroClock(4600, -100)).toBe(4600);
  });

  it('keeps signals, evidence, constrained actions and verification distinct', () => {
    expect(heroNodeState('failed', 'postgres').status).toBe('failed');
    expect(heroNodeState('failed', 'api').label).toBe('请求失败');
    expect(heroNodeState('reason', 'api').status).toBe('checking');
    expect(heroNodeState('reason', 'agent').label).toBe('受控决策');
    expect(heroEdgeKind('failed', 'api', 'postgres')).toBe('fault');
    expect(heroEdgeKind('reason', 'monitor', 'agent')).toBe('evidence');
    expect(heroEdgeKind('reason', 'agent', 'postgres')).toBe('action');
    expect(heroEdgeKind('recovered', 'postgres', 'monitor')).toBe('verify');
    expect(heroNeighbors('agent')).toEqual(['monitor', 'postgres']);
  });

  it('shows explicit simulation and cycle time without invented live metrics', () => {
    const html = renderToStaticMarkup(<HeroSystem />);
    expect(html).toContain('SIMULATION');
    expect(html).toContain('非在线状态');
    expect(html).toContain('循环 0.0s');
    expect(html).toContain('首页演示下一阶段');
    expect(html).not.toContain('Autonomous recovery');
    for (const stage of heroStages) {
      const graph = renderToStaticMarkup(<SystemTopology phase={stage.phase} heroDemo paused />);
      expect(graph.match(/class="system-node/g)).toHaveLength(6);
      expect(graph).toContain('node-worker concept');
      expect(graph).toContain('不连接真实执行器');
      for (const misleading of ['12 ms', '2 ms', '8 ms', 'RECOVERY VERIFIED', 'ALL SYSTEMS NOMINAL', 'class="flow']) expect(graph).not.toContain(misleading);
    }
  });
});
