import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { overviewStory, storyEdge, storyNode } from '../data/overviewStory';
import { SystemTopology } from './SystemTopology';
import { ScrollStory, stageAtPosition } from './ScrollStory';

describe('Overview conceptual narrative', () => {
  it('keeps six ordered stages and explicit provenance separate from live data', () => {
    expect(overviewStory.map(stage => stage.phase)).toEqual(['detect', 'locate', 'reason', 'execute', 'verify', 'learn']);
    const html = renderToStaticMarkup(<ScrollStory />);
    expect(html).toContain('CONCEPT · 概念示意');
    expect(html).toContain('非在线状态');
    expect(html.match(/data-phase="detect"/g)).toHaveLength(1);
    expect(html.match(/data-story-marker/g)).toHaveLength(6);
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1);
  });

  it('derives stages from native scroll in both directions, including fast entry and exit', () => {
    const tops = [0, 300, 600, 900, 1200, 1500];
    expect(stageAtPosition(tops, -100)).toBe(0);
    expect([0, 300, 600, 900, 1200, 1500].map(offset => stageAtPosition(tops, offset))).toEqual([0, 1, 2, 3, 4, 5]);
    expect([1500, 1200, 900, 600, 300, 0].map(offset => stageAtPosition(tops, offset))).toEqual([5, 4, 3, 2, 1, 0]);
    expect(stageAtPosition(tops, 3000)).toBe(5);
    expect(stageAtPosition(tops.map(top => top - 1000), 98)).toBe(3);
  });

  it('moves emphasis from faulty dependency to evidence, action, verification and records', () => {
    expect(storyEdge('locate', 'api', 'postgres')).toBe('fault');
    expect(storyEdge('locate', 'postgres', 'worker')).toBe('neutral');
    expect(storyEdge('reason', 'monitor', 'agent')).toBe('evidence');
    expect(storyEdge('execute', 'agent', 'postgres')).toBe('action');
    expect(storyEdge('verify', 'api', 'monitor')).toBe('verify');
    expect(storyEdge('learn', 'monitor', 'agent')).toBe('record');
    expect(storyNode('detect', 'postgres').status).toBe('failed');
    expect(storyNode('verify', 'postgres').status).toBe('checking');
  });

  it('never asserts execution, successful Verify, runtime metrics or Worker health in the concept graph', () => {
    for (const stage of overviewStory) {
      const html = renderToStaticMarkup(<SystemTopology phase={stage.phase} narrative paused />);
      expect(html).toContain(stage.readout);
      expect(html).toContain('概念节点');
      for (const misleading of ['RECOVERY VERIFIED', '04 / 04', 'restarting…', '12 ms', '8 ms', 'just-recovered']) expect(html).not.toContain(misleading);
      expect(storyNode(stage.phase, 'worker').status).toBe('neutral');
      expect(html).not.toContain('class="flow');
    }
  });

  it('preserves Hero simulation when narrative mode is absent', () => {
    const html = renderToStaticMarkup(<SystemTopology phase="recovered" />);
    expect(html).toContain('恢复已验证');
    expect(html).toContain('12 ms');
    expect(html).not.toContain('narrative-topology');
  });
});
