import { t } from '../i18n';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ArchitectureFlow, ArchitectureNodeDetail } from './ArchitectureFlow';
import { architectureContractFlows, architectureContractVersion, architectureNeighbors, architectureTabIndex, architectureViews } from '../data/architecture';
import { architectureLayerPurposes, architectureNodeDescriptions } from '../data/architecturePresentation';
import actionSchema from '../../../shared/recovery_action.schema.json';
import resultSchema from '../../../shared/recovery_result.schema.json';
import eventSchema from '../../../shared/agent_event.schema.json';
import diagnosisSchema from '../../../shared/diagnosis.schema.json';

describe('Architecture evidence and exploration', () => {
  it('uses the actual shared version and preserves object/producer distinctions', () => {
    for (const schema of [actionSchema, resultSchema, eventSchema, diagnosisSchema]) expect(schema.properties.schema_version.const).toBe(architectureContractVersion);
    expect(resultSchema.required).toContain('post_observation_id');
    expect(resultSchema.properties.verification.required).toContain('business_request_passed');
    expect(eventSchema.required).toContain('data');
    expect(architectureContractFlows.map(flow => flow.object)).toEqual(['Observation', 'RecoveryAction', 'RecoveryResult', 'Diagnosis', 'AgentEvent']);
    expect(architectureContractFlows.find(flow => flow.object === 'RecoveryResult')?.receiver).toBe('B Verify');
  });
  it('does not turn schema actions or offline implementation into online permission', () => {
    const [system, agent, evaluation] = architectureViews;
    expect(system.nodes.find(node => node.id === 'api')?.evidence).toContain('F02');
    expect(system.nodes.find(node => node.id === 'redis')?.evidence).toContain('cache_write');
    expect(agent.nodes.find(node => node.id === 'planner')?.boundary).toContain('Phase 8 仅 start(web)');
    expect(agent.nodes.find(node => node.id === 'memory')?.boundary).toContain('Skill 自动生成仍为概念');
    expect(evaluation.nodes.find(node => node.id === 'experiments')?.status).toBe('pending');
    expect(evaluation.nodes.find(node => node.id === 'benchmark')?.status).toBe('offline');
    expect(evaluation.nodes.find(node => node.id === 'evidence')?.boundary).toContain('不填真实成功率');
  });
  it('keeps relationship endpoints valid and highlights only direct associations', () => {
    for (const layer of architectureViews) {
      const ids = layer.nodes.map(node => node.id);
      expect(new Set(ids).size).toBe(ids.length);
      for (const edge of layer.edges) { expect(ids).toContain(edge.from); expect(ids).toContain(edge.to); }
      for (const node of layer.nodes) expect(node.references.length).toBeGreaterThan(0);
    }
    expect(architectureNeighbors(architectureViews[0], 'postgres').sort()).toEqual(['api', 'docker']);
    expect(architectureNeighbors(architectureViews[2], 'evidence')).toEqual(['sqlite']);
  });
  it('supports vertical tab navigation, wraparound and Home/End', () => {
    expect(architectureTabIndex(2, 'ArrowDown', 3)).toBe(0);
    expect(architectureTabIndex(0, 'ArrowUp', 3)).toBe(2);
    expect(architectureTabIndex(1, 'Home', 3)).toBe(0);
    expect(architectureTabIndex(1, 'End', 3)).toBe(2);
    expect(architectureTabIndex(0, 'Tab', 3)).toBeNull();
  });
  it('distinguishes the A HTTP boundary, B scoped executor and C file ingestion', () => {
    const action = architectureContractFlows.find(flow => flow.object === 'RecoveryAction')!;
    expect(action.sender).toBe('B Planner');
    expect(action.explanation).toContain('POST /actions');
    expect(action.explanation).toContain('B 在线：scoped Docker');
    expect(action.explanation).toContain('HTTP 联调未确认');
    const event = architectureContractFlows.find(flow => flow.object === 'AgentEvent')!;
    expect(event.receiver).toBe('C SQLite');
    expect(event.explanation).toContain('JSONL');
    expect(event.explanation).toContain('在线待验收');
    expect(architectureContractFlows.find(flow => flow.object === 'Diagnosis')?.explanation).toContain('非直连诊断 API');
    for (const flow of architectureContractFlows) expect(flow.references).toContain(`shared/${flow.object.replace(/([a-z])([A-Z])/g, '$1_$2').toLowerCase()}.schema.json`);
  });
  it('removes developer documentation from the presentation while keeping its verified source data', () => {
    const html = renderToStaticMarkup(<ArchitectureFlow />);
    for (const text of ['View data contracts', 'Implementation details', '代码已实现', '历史验收摘要', 'SHARED', '<details', '<dl', '<code']) expect(html).not.toContain(text);
    for (const flow of architectureContractFlows) {
      expect(flow.references.length).toBeGreaterThan(0);
      expect(html).not.toContain(flow.explanation);
    }
    for (const layer of architectureViews) for (const node of layer.nodes) for (const reference of node.references) expect(html).not.toContain(reference);
    expect(html).not.toContain('data-detail-node=');
    expect(html).not.toContain('aria-controls="arch-node-detail"');
  });
  it('shows only each component name and brief responsibility, keeping constrained execution explicit', () => {
    expect(Object.keys(architectureNodeDescriptions).sort()).toEqual(architectureViews.flatMap(layer => layer.nodes.map(node => node.id)).sort());
    expect(Object.keys(architectureLayerPurposes).sort()).toEqual(architectureViews.map(layer => layer.id).sort());
    for (const layer of architectureViews) for (const node of layer.nodes) {
      const html = renderToStaticMarkup(<ArchitectureNodeDetail node={node} onClose={() => {}} />);
      expect(html).toContain(t(node.name));
      expect(html).toContain(architectureNodeDescriptions[node.id]);
      for (const text of ['<details', '<dl', '<code', 'arch-evidence-state', node.input, node.output, node.evidence, node.boundary]) expect(html).not.toContain(text);
      expect(html.match(/<p>/g)).toHaveLength(1);
      expect(html).toContain('关闭组件详情');
    }
    expect(architectureNodeDescriptions.safety).toContain('独立授权');
    expect(architectureNodeDescriptions.experiments).toContain('不直接触发恢复');
    expect(architectureNodeDescriptions.trajectory).toContain('不重新执行恢复');
    expect(architectureNodeDescriptions.benchmark).toContain('离线报告');
  });
  it('exposes one layer and six unselected components, without pretending to show runtime health', () => {
    const html = renderToStaticMarkup(<ArchitectureFlow />);
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1);
    expect(html.match(/aria-pressed="true"/g)).toBeNull();
    expect(html.match(/aria-pressed="false"/g)).toHaveLength(6);
    expect(html.match(/data-architecture-node=/g)).toHaveLength(6);
    expect(html).toContain('非在线拓扑');
    expect(html).toContain('非实时执行');
    expect(html).toContain('在线联调待验收');
    expect(html).toContain('逻辑示意');
    expect(html).not.toContain('Observation</span><span>→</span><span>AgentEvent');
  });
});
