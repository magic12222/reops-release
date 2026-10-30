import type { AgentEvent, TraceStep } from '../types/agent';
import type { SystemNode } from '../types/system';
import type { StrategyMetrics } from '../types/metrics';

export const demoMeta = {
  mode: 'simulation' as const, incidentId: 'demo-incident-001', traceId: 'demo-trace-001',
  duration: 8400, toolCalls: 6, confidence: 0.94, verification: 'Passed',
  prompt: 'Observe evidence. Localize the failing step. Compare recovery actions by risk and scope. Use only allowlisted tools. Verify service AND business health before declaring recovery.',
};

export const systemNodes: SystemNode[] = [
  { id: 'api', label: 'FastAPI', detail: '业务入口 · GET /users', x: 24, y: 29, latency: '12 ms' },
  { id: 'redis', label: 'Redis', detail: '缓存依赖 · cache_write', x: 18, y: 70, latency: '2 ms' },
  { id: 'postgres', label: 'PostgreSQL', detail: '数据库依赖 · database_query', x: 51, y: 58, latency: '8 ms' },
  { id: 'worker', label: 'Worker', detail: '概念节点 · 后续任务消费者', x: 78, y: 80, latency: 'concept', conceptual: true },
  { id: 'monitor', label: 'Monitor', detail: '健康检查与日志观测', x: 63, y: 17, latency: 'observing' },
  { id: 'agent', label: 'ReOps Agent', detail: 'Nexent / LLM · 演示流程', x: 85, y: 43, latency: 'standby', conceptual: true },
];
export const topologyEdges = [
  ['api', 'redis'], ['api', 'postgres'], ['postgres', 'worker'],
  ['api', 'monitor'], ['postgres', 'monitor'], ['monitor', 'agent'], ['agent', 'postgres'],
] as const;

const eventBase = { schema_version: '1.0' as const, incident_id: demoMeta.incidentId, trace_id: demoMeta.traceId, status: 'success' as const, component: 'postgres' };
const definitions: Omit<TraceStep, 'event'>[] = [
  { at: 0, phase: 'failed', title: 'Observe the failure', subtitle: '故障已注入 · PostgreSQL 不可用', input: 'GET /users → 503', reason: '业务请求失败，但 API 进程存活。读取依赖状态与步骤日志。', tool: 'system.status()', result: 'postgres: unhealthy · api: healthy · redis: healthy' },
  { at: 800, phase: 'detect', title: 'Detect an anomaly', subtitle: '从健康探测和业务响应识别异常', input: 'Observation / obs-demo-001', reason: '关联 unhealthy 状态和 503 业务响应，确认依赖故障。', tool: 'health_check()', result: 'Failure detected · database_query' },
  { at: 1800, phase: 'locate', title: 'Narrow the search', subtitle: '依赖排查 · 锁定数据库访问步骤', input: 'api → database_query → postgres', reason: 'Redis 探测通过，API 存活；故障范围缩小到 PostgreSQL。', tool: 'get_logs(postgres)', result: 'Connection refused · postgres:5432' },
  { at: 2800, phase: 'reason', title: 'Identify the root cause', subtitle: '根因分析 · 数据库服务停止', input: 'Health evidence + connection error', reason: '服务停机与连接拒绝一致，没有配置变更或认证错误证据。', tool: 'get_service_status(postgres)', result: 'Root cause: postgres_service_down' },
  { at: 3800, phase: 'decide', title: 'Choose the smallest action', subtitle: '选择低风险、最小影响的恢复方案', input: '4 candidate recovery actions', reason: '局部重启只影响数据库；重启 API 无法修复根因，整栈重启影响过大。', tool: 'RecoveryAction / restart_service', result: 'target: postgres · risk: 0.10 · allowlisted' },
  { at: 5000, phase: 'execute', title: 'Execute the recovery', subtitle: '白名单执行器恢复 PostgreSQL', input: 'RecoveryAction / act-demo-001', reason: '动作范围受限，参数为空，不含任意 shell。', tool: 'restart_service(postgres)', result: 'execution_status: succeeded' },
  { at: 7000, phase: 'verify', title: 'Verify beyond green lights', subtitle: '同时验证服务健康和业务请求', input: 'Post-action Observation', reason: '命令成功不等于业务恢复；重新检查数据库探测和 /users。', tool: 'health_check() + GET /users', result: 'postgres: healthy · business: 200' },
  { at: 8400, phase: 'recovered', title: 'System recovered', subtitle: '验证完成 · 恢复经验等待沉淀', input: 'RecoveryResult / result-demo-001', reason: '服务与业务检查均通过，可将这条诊断和动作轨迹用于后续经验学习。', tool: 'experience_update (preview)', result: 'Verification passed · skill preview ready' },
];
const stages: AgentEvent['stage'][] = ['observe', 'failure_detection', 'localization', 'root_cause_analysis', 'recovery_decision', 'recovery_execution', 'verification', 'experience_update'];
export const demoSteps: TraceStep[] = definitions.map((step, i) => ({
  ...step,
  event: { ...eventBase, event_id: `evt-demo-${i + 1}`, parent_event_id: i ? `evt-demo-${i}` : null,
    timestamp: new Date(Date.UTC(2026, 9, 3, 4, 0, 0) + step.at).toISOString(), stage: stages[i],
    message: step.subtitle, confidence: i >= 2 ? demoMeta.confidence : null,
    observation_id: i < 6 ? 'obs-demo-001' : 'obs-demo-002',
    diagnosis_id: i >= 3 ? 'diag-demo-001' : null, action_id: i >= 4 ? 'act-demo-001' : null,
    result_id: i >= 6 ? 'result-demo-001' : null,
    data: { source: 'mock', tool: step.tool, input: step.input, reason: step.reason, result: step.result } },
}));

export const candidateActions = [
  { name: 'Restart PostgreSQL', code: 'restart_service · postgres', status: 'Recommended', reason: '修复根因，影响仅限目标服务。', risk: 0.1, impact: '1 service', time: '8.4s', confidence: 0.94 },
  { name: 'Restart API', code: 'restart_service · api', status: 'Rejected', reason: 'API 存活，重启不会修复数据库停机。', risk: 0.2, impact: 'API traffic', time: '—', confidence: 0.12 },
  { name: 'Restart entire stack', code: 'outside current allowlist', status: 'Too disruptive', reason: '无必要地扩大影响范围；当前执行器也不支持整栈动作。', risk: 0.85, impact: 'All services', time: '> 30s', confidence: 0.71 },
  { name: 'Rollback', code: 'not implemented in A', status: 'Not required', reason: '没有版本回归证据，当前 A 也未实现此动作。', risk: 0.6, impact: 'Deployment', time: '—', confidence: 0.08 },
];

// Illustrative fixtures, NOT measured competition results.
export const benchmarkData: StrategyMetrics[] = [
  { id: 'rule', name: 'Rule-based', successRate: 68, recoveryTime: 24.6, toolCalls: 9, tokens: 0, coverage: 38, samples: 24, sparkline: [35, 53, 41, 60, 54, 68, 62, 68], provenance: 'demo' },
  { id: 'llm', name: 'LLM only', successRate: 81, recoveryTime: 16.2, toolCalls: 11, tokens: 6400, coverage: 62, samples: 24, sparkline: [50, 57, 72, 68, 79, 70, 81, 81], provenance: 'demo' },
  { id: 'reops', name: 'ReOps', successRate: 94, recoveryTime: 8.4, toolCalls: 6, tokens: 2800, coverage: 75, samples: 24, sparkline: [62, 74, 70, 83, 88, 84, 94, 94], provenance: 'demo' },
];

export const architectureLayers = [
  { id: 'system', number: '01', name: 'System', label: 'THE FOUNDATION', state: 'A · 已完成并验收', summary: 'A reliable place to fail.', description: '可重复注入故障、采集证据，并通过受限执行器恢复目标服务。', modules: [
    { name: 'FastAPI', detail: '/health/live · /health · /users' }, { name: 'PostgreSQL', detail: 'F01 停机 · F02 配置错误' }, { name: 'Redis', detail: 'F03 停机 · cache_write' }, { name: 'Docker', detail: 'api / postgres / redis · Compose' }, { name: 'Observation', detail: '健康状态、业务步骤、日志与基础指标' }, { name: 'Executor', detail: '白名单动作 · 鉴权 · 持久化去重' },
  ] },
  { id: 'agent', number: '02', name: 'Agent', label: 'THE INTELLIGENCE', state: 'B · 受控闭环已验收', summary: 'Reason before recovery.', description: '用证据定位到失败步骤，比较方案、执行恢复，验证真实业务结果。', modules: [
    { name: 'Detection', detail: '识别异常 Observation' }, { name: 'Localization', detail: '缩小故障组件和步骤范围' }, { name: 'RCA', detail: '关联证据与根因' }, { name: 'Decision', detail: '评估风险和影响范围' }, { name: 'Verification', detail: '服务健康 + 业务成功' }, { name: 'Memory / Skill', detail: 'Recovery Memory 已实现；Skill 为概念预览' },
  ] },
  { id: 'evaluation', number: '03', name: 'Evaluation', label: 'THE EVIDENCE', state: 'C · 只读展示 / 离线评测', summary: 'Measure every recovery.', description: '统一关联每一次故障、执行轨迹和验证结果，支持可比较的评测。', modules: [
    { name: 'Trajectory', detail: '消费 shared AgentEvent 1.0' }, { name: 'Dashboard', detail: '系统、故障、恢复状态' }, { name: 'Experiments', detail: '关联 incident_id / trace_id' }, { name: 'Benchmark', detail: '按来源读取已导入的离线报告' }, { name: 'Metrics', detail: '按证据展示指标；缺少真实计量时留空' }, { name: 'Evidence', detail: '区分模拟数据与真实记录' },
  ] },
];
