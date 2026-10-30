import { systemNodes, topologyEdges } from './demoData';
import type { NodeId, SystemPhase } from '../types/system';

// Presentation timing only. This clock never reads or drives the recovery workspace.
export const heroStages = [
  { at: 0, phase: 'healthy', title: 'Watching. Quietly.', label: '示例正常', tone: 'green' },
  { at: 2200, phase: 'failed', title: 'A dependency fails.', label: '故障信号', tone: 'red' },
  { at: 4600, phase: 'reason', title: 'Evidence before action.', label: '诊断与受控动作', tone: 'cyan' },
  { at: 8600, phase: 'recovered', title: 'Verify the outcome.', label: '模拟核验', tone: 'green' },
] as const;
export const heroCycleDuration = 11200;

export function heroStageAt(elapsed: number) {
  const time = ((elapsed % heroCycleDuration) + heroCycleDuration) % heroCycleDuration;
  let index = 0;
  heroStages.forEach((stage, i) => { if (stage.at <= time) index = i; });
  return { ...heroStages[index], index };
}

export function advanceHeroClock(elapsed: number, delta: number) {
  return (elapsed + Math.max(0, delta)) % heroCycleDuration;
}

export function heroNodeState(phase: SystemPhase, node: NodeId) {
  if (node === 'worker') return { status: 'concept', label: '概念节点' };
  if (node === 'agent') return phase === 'reason' ? { status: 'active', label: '受控决策' } : phase === 'recovered' ? { status: 'active', label: '证据记录' } : { status: 'neutral', label: '演示待命' };
  if (node === 'monitor') return { status: phase === 'healthy' ? 'neutral' : 'active', label: phase === 'failed' ? '故障信号' : phase === 'reason' ? '汇集观测' : phase === 'recovered' ? '模拟核验' : '观测示意' };
  if (node === 'postgres' && (phase === 'failed' || phase === 'reason')) return { status: 'failed', label: phase === 'reason' ? '故障证据' : '示例故障' };
  if (node === 'api' && (phase === 'failed' || phase === 'reason')) return { status: 'checking', label: phase === 'reason' ? '故障信号' : '请求失败' };
  return { status: 'healthy', label: phase === 'recovered' ? '模拟核验' : '示例正常' };
}

export function heroEdgeKind(phase: SystemPhase, from: NodeId, to: NodeId) {
  if ((phase === 'failed' || phase === 'reason') && from === 'api' && to === 'postgres') return 'fault';
  if (phase === 'reason') {
    if (to === 'monitor' || (from === 'monitor' && to === 'agent')) return 'evidence';
    if (from === 'agent' && to === 'postgres') return 'action';
  }
  if (phase === 'recovered' && (to === 'monitor' || (from === 'monitor' && to === 'agent'))) return 'verify';
  return 'neutral';
}

export function heroNeighbors(node: NodeId): NodeId[] {
  return topologyEdges.flatMap(([from, to]) => from === node ? [to] : to === node ? [from] : []);
}

export function heroNodeDetail(node: NodeId) {
  const current = systemNodes.find(item => item.id === node)!;
  const role = node === 'agent' ? '诊断建议 · Planner / Safety 约束动作' : current.detail;
  const related = heroNeighbors(node).map(id => systemNodes.find(item => item.id === id)!.label).join(' / ');
  return { role, related, conceptual: node === 'worker' ? ' · 概念连接' : '' };
}
