import type { NodeId, SystemPhase } from '../types/system';

// Conceptual example, independent of C API / offline fixtures.
export const overviewStory = [
  { word: 'Detect.', sub: '发现异常', phase: 'detect', detail: '关联业务失败、健康探测与步骤日志，识别故障信号。', evidence: '业务失败 + 健康探测', readout: '异常信号', nodes: { api: '请求失败', postgres: '依赖异常', monitor: '收集信号' } },
  { word: 'Locate.', sub: '确定位置', phase: 'locate', detail: '结合服务状态，沿 FastAPI → PostgreSQL 依赖路径定位 database_query 失败。', evidence: 'api → database_query → postgres', readout: '故障依赖路径', nodes: { api: '依赖排查', postgres: '定位目标', monitor: '核对状态' } },
  { word: 'Reason.', sub: '形成决策', phase: 'reason', detail: 'Monitor 汇集观测与日志；Agent 提出诊断建议，Planner / Safety 约束候选决策。', evidence: 'Observation → 诊断 → Planner / Safety', readout: '证据汇集与决策', nodes: { postgres: '故障证据', monitor: '汇集观测', agent: '诊断建议' } },
  { word: 'Recover.', sub: '受控执行', phase: 'execute', detail: '授权与安全检查通过后，执行器才映射白名单动作。本图仅示意动作目标。', evidence: '授权 + Safety → 白名单执行器 → 目标', readout: '允许的动作与目标', nodes: { postgres: '动作目标', agent: '授权 / Safety' } },
  { word: 'Verify.', sub: '重新验证', phase: 'verify', detail: '重新观测服务健康与 /users 业务结果；在线受限流程要求两次独立新样本，不能仅凭命令成功。', evidence: '新 Observation + 服务健康 + 业务响应', readout: '验证项 · 待证据确认', nodes: { api: '业务核验', postgres: '健康核验', monitor: '新样本', agent: '检查结果' } },
  { word: 'Learn.', sub: '记录证据', phase: 'learn', detail: '按 incident / trace 关联诊断、动作与 Verify，保存复盘证据；历史辅助候选评分，不放宽安全边界。', evidence: 'incident_id ↔ trace_id ↔ 动作 / Verify ↔ Memory', readout: '可追溯经验记录', nodes: { monitor: '观测引用', agent: '经验记录' } },
] satisfies { word: string; sub: string; phase: SystemPhase; detail: string; evidence: string; readout: string; nodes: Partial<Record<NodeId, string>> }[];

export function storyNode(phase: SystemPhase, node: NodeId) {
  const stage = overviewStory.find(item => item.phase === phase);
  const label = (stage?.nodes as Partial<Record<NodeId, string>> | undefined)?.[node];
  const status = node === 'worker' ? 'neutral' : node === 'postgres' && ['detect', 'locate', 'reason'].includes(phase) ? 'failed' : phase === 'verify' && label ? 'checking' : label ? 'active' : 'neutral';
  return { status, label: label ?? (node === 'worker' ? '概念节点' : '依赖组件') };
}

export function storyEdge(phase: SystemPhase, from: NodeId, to: NodeId) {
  const pair = `${from}-${to}`;
  if (['detect', 'locate'].includes(phase) && pair === 'api-postgres') return 'fault';
  if (phase === 'reason' && ['api-monitor', 'postgres-monitor', 'monitor-agent'].includes(pair)) return 'evidence';
  if (phase === 'execute' && pair === 'agent-postgres') return 'action';
  if (phase === 'verify' && ['api-monitor', 'postgres-monitor', 'monitor-agent'].includes(pair)) return 'verify';
  if (phase === 'learn' && pair === 'monitor-agent') return 'record';
  return 'neutral';
}
