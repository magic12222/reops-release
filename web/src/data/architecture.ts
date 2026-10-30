import observationSchema from '../../../shared/observation.schema.json';

export type ArchitectureStatus = 'implemented' | 'historical' | 'offline' | 'pending' | 'concept';
export const architectureStatusLabels: Record<ArchitectureStatus, string> = {
  implemented: '代码已实现', historical: '历史验收摘要', offline: '离线已验证', pending: '在线待验收', concept: '概念预览',
};
export const architectureContractVersion = observationSchema.properties.schema_version.const;
export type ArchitectureNode = {
  id: string; name: string; tag: string; x: number; y: number;
  role: string; input: string; output: string; evidence: string; boundary: string;
  status: ArchitectureStatus; references: string[];
};
export type ArchitectureEdge = {
  from: string; to: string; label: string; labelX: number; labelY: number;
  route: string; arrow: string; kind: 'dependency' | 'data' | 'control'; external?: boolean;
};
export type ArchitectureLayer = {
  id: string; name: string; number: string; label: string; state: string;
  summary: string; description: string; nodes: ArchitectureNode[]; edges: ArchitectureEdge[];
};

// These object-specific logical flows are shared by all views. Transport is not
// inferred from the graph: the current B online path does not call A's HTTP API.
export const architectureContractFlows = [
  { object: 'Observation', sender: 'A 观测 / B 本地适配器', receiver: 'B 诊断',
    explanation: 'A：POST /observations；B 在线路径本地采样。C 从事件载荷读取快照。',
    references: ['shared/observation.schema.json', 'infra/monitoring/control.py', 'reops_agent/docker_executor.py', 'dashboard_api/normalize.py'] },
  { object: 'RecoveryAction', sender: 'B Planner', receiver: 'A 或 B 固定执行器',
    explanation: 'A：POST /actions；B 在线：scoped Docker + 独立授权。B→A HTTP 联调未确认。',
    references: ['shared/recovery_action.schema.json', 'infra/monitoring/control.py', 'reops_agent/planner.py', 'reops_agent/phase8_online.py', 'reops_agent/phase8b_online.py'] },
  { object: 'RecoveryResult', sender: 'A 执行器 / B 结果封装', receiver: 'B Verify',
    explanation: 'A 返回执行证据；B 适配器结果另行封装，用新观测核验。C 读取事件中结果。',
    references: ['shared/recovery_result.schema.json', 'infra/monitoring/control.py', 'reops_agent/recovery_smoke.py', 'reops_agent/recovery.py'] },
  { object: 'Diagnosis', sender: 'B 诊断', receiver: 'B 决策 · C 证据读取',
    explanation: 'B 生成并嵌入 AgentEvent；C 从事件文件读取，非直连诊断 API。',
    references: ['shared/diagnosis.schema.json', 'reops_agent/pipeline.py', 'reops_agent/agent_event.py', 'dashboard_api/normalize.py'] },
  { object: 'AgentEvent', sender: 'B Journal / Memory', receiver: 'C SQLite',
    explanation: 'JSONL 导入 / 配置后跟随 → 只读 GET / SSE；C 离线已验证，在线待验收。',
    references: ['shared/agent_event.schema.json', 'reops_agent/trace_journal.py', 'reops_agent/memory.py', 'dashboard_api/import_data.py', 'dashboard_api/live.py', 'dashboard_api/api.py'] },
];

// Logical relationships grounded in the references below; never live traces.
export const architectureViews: ArchitectureLayer[] = [
  {
    id: 'system', name: 'System', number: '01', label: 'THE FOUNDATION', state: 'A · 实现 / 历史验收摘要', summary: 'A reliable place to fail.',
    description: '服务依赖、观测与固定执行器。A 的独立验收不等于 A/B/C 全链路在线联调。',
    nodes: [
      { id: 'docker', name: 'Docker', tag: 'Compose 环境', x: 16, y: 24, status: 'implemented', role: '编排 api、postgres、redis 三个目标服务。', input: 'Compose 配置与固定服务映射', output: '容器状态、日志与健康检查', evidence: 'reops-lab · restart: no', boundary: '描述已定义的环境，本页未连接真实容器。', references: ['docker-compose.yml', 'tools/system_tools.py'] },
      { id: 'api', name: 'FastAPI', tag: '业务与探测', x: 50, y: 24, status: 'historical', role: '提供健康接口与依赖数据库、缓存的业务请求。', input: 'GET /health/live · /health · /users', output: '业务响应、失败步骤与依赖健康', evidence: 'F02 · API 数据库密码错误 · database_query', boundary: 'A 文档有历史验收摘要，原始报告未作为本页运行数据接入。', references: ['target_system/api/main.py', 'docs/a-acceptance-report.md'] },
      { id: 'observer', name: 'Observer', tag: '观测快照', x: 84, y: 24, status: 'implemented', role: '采集健康探测、/users 结果、基础指标与观测日志。', input: 'API 健康与业务响应 + incident / trace', output: 'Observation 1.0 · observation_id', evidence: 'services · request · logs · metrics', boundary: '观测接口有实现，本页不请求真实观测或展示实时延迟。', references: ['infra/monitoring/observer.py', 'shared/observation.schema.json'] },
      { id: 'postgres', name: 'PostgreSQL', tag: '数据库依赖', x: 16, y: 74, status: 'historical', role: '为 /users 提供数据库查询。', input: 'FastAPI · database_query', output: '查询结果或数据库失败证据', evidence: 'F01 · PostgreSQL 停机 · database_query', boundary: 'F01 是 A 独立故障场景，未从 C4 开放在线实验。', references: ['target_system/api/main.py', 'fault_injection/service_failure.py', 'docs/a-acceptance-report.md'] },
      { id: 'redis', name: 'Redis', tag: '缓存依赖', x: 50, y: 74, status: 'historical', role: '在 /users 请求中执行缓存写入。', input: 'FastAPI · cache_write', output: '缓存写入结果或失败证据', evidence: 'F03 · Redis 停机 · cache_write', boundary: 'A 独立验收摘要存在，不代表 B 在线策略已开放 Redis 恢复。', references: ['target_system/api/main.py', 'fault_injection/service_failure.py', 'docs/a-acceptance-report.md'] },
      { id: 'executor', name: 'Executor', tag: '固定白名单', x: 84, y: 74, status: 'implemented', role: '验证结构化动作并映射到固定系统操作。', input: 'RecoveryAction · action_id · 受限参数', output: 'RecoveryResult · 执行状态 · 后观测引用', evidence: 'start / stop / restart · api normal 配置', boundary: 'A 白名单不等于 B 在线候选；鉴权、审批、去重仍有效，拒绝任意 shell。', references: ['infra/monitoring/control.py', 'shared/recovery_action.schema.json', 'shared/recovery_result.schema.json'] },
    ],
    edges: [
      { from: 'docker', to: 'api', kind: 'dependency', label: 'Compose', route: 'M 24 24 H 41', arrow: 'M 31 24 H 33', labelX: 33, labelY: 7 },
      { from: 'docker', to: 'postgres', kind: 'dependency', label: '容器', route: 'M 16 38 V 60', arrow: 'M 16 47 V 49', labelX: 10, labelY: 50 },
      { from: 'api', to: 'postgres', kind: 'dependency', label: 'query', route: 'M 45 38 C 45 52 22 46 20 60', arrow: 'M 35 48 L 33 49', labelX: 34, labelY: 42 },
      { from: 'api', to: 'redis', kind: 'dependency', label: 'cache_write', route: 'M 50 38 V 60', arrow: 'M 50 47 V 49', labelX: 65, labelY: 50 },
      { from: 'api', to: 'observer', kind: 'data', label: 'health / users', route: 'M 59 24 H 75', arrow: 'M 65 24 H 67', labelX: 67, labelY: 7 },
      { from: 'executor', to: 'docker', kind: 'control', label: '白名单操作', route: 'M 84 88 V 95 H 1 V 24 H 7', arrow: 'M 42 95 H 40', labelX: 34, labelY: 90 },
    ],
  },
  {
    id: 'agent', name: 'Agent', number: '02', label: 'THE INTELLIGENCE', state: 'B · 受控闭环 / 历史摘要', summary: 'Reason before recovery.',
    description: '证据、建议与安全约束共同形成决策。真实执行需要独立授权；经验不能扩大白名单。',
    nodes: [
      { id: 'diagnosis', name: 'Diagnosis', tag: '检测与定位', x: 16, y: 24, status: 'implemented', role: '校验 Observation，检测故障并定位组件与失败步骤。', input: 'Observation · observation_id', output: 'Diagnosis · failed_component / failed_step', evidence: 'observe → detect → build_diagnosis', boundary: '规则诊断是已有基线，不将未知证据补成确定根因。', references: ['reops_agent/pipeline.py', 'reops_agent/diagnosis.py', 'shared/diagnosis.schema.json'] },
      { id: 'rca', name: 'RCA', tag: '可选诊断建议', x: 50, y: 24, status: 'implemented', role: '通过可选 provider 分析观测、诊断与历史证据。', input: 'Observation + Diagnosis + Memory', output: '经校验的 RCA 建议 / 拒绝或 fallback', evidence: '可选 Nexent provider · 结构化校验', boundary: '模型不持有执行器；本页不调用模型，建议不能替代 Safety。', references: ['reops_agent/rca.py', 'reops_agent/nexent_provider.py'] },
      { id: 'planner', name: 'Planner', tag: '受限方案选择', x: 84, y: 24, status: 'implemented', role: '根据证据、策略和历史比较允许的候选。', input: 'Diagnosis · RCA 建议 · 安全合格的历史', output: 'RecoveryAction · action / target / risk', evidence: 'decision_basis · 候选与拒绝原因', boundary: 'shared 动作枚举不是在线许可；Phase 8 仅 start(web)，8B 才受控允许 start/restart(web)。', references: ['reops_agent/planner.py', 'reops_agent/phase8_online.py', 'reops_agent/phase8b_online.py'] },
      { id: 'memory', name: 'Memory', tag: '可追溯经验', x: 16, y: 74, status: 'historical', role: '记录事件，按故障和位置检索经验，参与后续受限决策。', input: '已关联的 Diagnosis / Action / Result 事件', output: '历史证据与候选评分依据', evidence: 'Phase 8B 摘要记录 start → restart', boundary: '历史摘要不等于本页在线复验；Memory 已实现，Skill 自动生成仍为概念预览。', references: ['reops_agent/memory.py', 'docs/phase8b-online-acceptance.md'] },
      { id: 'verify', name: 'Verify', tag: '新观测核验', x: 50, y: 74, status: 'implemented', role: '重新诊断执行后的观测，同时核对服务健康和业务成功。', input: '新 Observation + 已报告的执行结果', output: 'RecoveryResult.verification · AgentEvent', evidence: '真实 7D/8 路径要求两次 fresh Verify', boundary: '命令完成、cleanup 成功或一次健康均不能代替恢复确认。', references: ['reops_agent/verification.py', 'reops_agent/recovery_smoke.py', 'shared/recovery_result.schema.json'] },
      { id: 'safety', name: 'Safety', tag: '执行前约束', x: 84, y: 74, status: 'implemented', role: '执行前再次校验 schema、白名单、当前故障和关联上下文。', input: 'RecoveryAction + 当前 Observation', output: '允许 / 拒绝 · 独立授权后才执行', evidence: 'AuthorizationGate · TTL · 单次消费', boundary: '默认 mock；真实旁路须显式 scope、授权与固定执行器，不执行任意 shell。', references: ['reops_agent/safety.py', 'reops_agent/authorization.py', 'reops_agent/recovery_smoke.py'] },
    ],
    edges: [
      { from: 'diagnosis', to: 'rca', kind: 'data', label: '可选建议', route: 'M 25 24 H 41', arrow: 'M 31 24 H 33', labelX: 33, labelY: 7 },
      { from: 'rca', to: 'planner', kind: 'data', label: '证据', route: 'M 59 24 H 75', arrow: 'M 65 24 H 67', labelX: 72, labelY: 7 },
      { from: 'diagnosis', to: 'planner', kind: 'data', label: '规则基线', route: 'M 16 10 V 5 H 84 V 10', arrow: 'M 64 5 H 66', labelX: 50, labelY: 5 },
      { from: 'planner', to: 'safety', kind: 'control', label: 'Action', route: 'M 84 38 V 60', arrow: 'M 84 47 V 49', labelX: 93, labelY: 50 },
      { from: 'safety', to: 'verify', kind: 'data', label: '执行结果 / 新观测', route: 'M 75 74 H 59', arrow: 'M 69 74 H 67', labelX: 67, labelY: 92, external: true },
      { from: 'verify', to: 'memory', kind: 'data', label: '结果记录', route: 'M 41 74 H 25', arrow: 'M 35 74 H 33', labelX: 33, labelY: 92 },
      { from: 'memory', to: 'rca', kind: 'data', label: '历史证据', route: 'M 16 60 C 16 46 46 53 46 38', arrow: 'M 28 51 L 30 50', labelX: 30, labelY: 42 },
    ],
  },
  {
    id: 'evaluation', name: 'Evaluation', number: '03', label: 'THE EVIDENCE', state: 'C · 离线评测 / 在线待验收', summary: 'Evidence before conclusions.',
    description: '按来源关联轨迹、实验和报告。C 只展示证据，不代替 B 的 Verify，也不从缺失报告推算真实指标。',
    nodes: [
      { id: 'import', name: 'Event import', tag: 'JSONL 导入', x: 16, y: 24, status: 'implemented', role: '导入既有 B TraceJournal / Memory 事件，检查链路与冲突。', input: 'AgentEvent JSONL + 显式 source', output: '来源分区的 run / event 与文件指纹', evidence: '整文件事务 · SHA256 · 重复不扩样本', boundary: 'source 是操作者声明，文件指纹不是来源签名。', references: ['dashboard_api/import_data.py', 'dashboard_api/store.py'] },
      { id: 'sqlite', name: 'SQLite', tag: 'C 独立存储', x: 50, y: 24, status: 'implemented', role: '保存 C 的运行、事件、实验台账及离线报告。', input: '同 source 的导入记录与关联 ID', output: '一致性快照与只读 API', evidence: 'source + incident_id + trace_id', boundary: '这是 C 自有 SQLite，不使用 A 目标 PostgreSQL。', references: ['dashboard_api/store.py', 'dashboard_api/experiments.py', 'dashboard_api/benchmark.py'] },
      { id: 'trajectory', name: 'Trajectory', tag: '轨迹与回放', x: 84, y: 24, status: 'implemented', role: '按运行与事件顺序读取轨迹，支持只读展示和回放。', input: '已存储的 AgentEvent / 运行记录', output: '事件列表、关联引用与 SSE 展示', evidence: 'parent_event_id 只表示事件顺序', boundary: '回放不重执行恢复；offline_fixture 不标为 real。', references: ['dashboard_api/api.py', 'dashboard_api/live.py', 'shared/agent_event.schema.json'] },
      { id: 'experiments', name: 'Experiments', tag: '请求与台账', x: 16, y: 74, status: 'pending', role: '登记固定 Phase 8 场景请求，独立记录授权、执行、Verify 和 cleanup。', input: 'phase8_stopped_api 请求意图', output: '实验 ID、ground truth 与运行关联', evidence: '请求默认关闭 · 服务端原授权入口', boundary: 'C4 离线回归已完成，在线联调待验收；登记不注入故障，不代理 A 写接口。', references: ['dashboard_api/experiments.py', 'docs/phase-c4-experiment-control.md'] },
      { id: 'benchmark', name: 'Benchmark', tag: '离线评测', x: 50, y: 74, status: 'offline', role: '读取 B 已生成的 fixture 报告，按 case 重算已有指标。', input: 'offline-fixture / offline-fixture-comparison', output: '分子、分母、rate、缺字段与 null', evidence: '只接收 offline_fixture · 真实计量留空', boundary: '离线 provider 次数不是实际模型调用，未开放 real benchmark 导入。', references: ['dashboard_api/benchmark.py', 'docs/benchmark-design.md', 'dashboard_api/README.md'] },
      { id: 'evidence', name: 'Evidence', tag: '证据与缺口', x: 84, y: 74, status: 'implemented', role: '核对已报告的执行、Verify 引用与同源实验，展示缺口和冲突。', input: 'run / events / experiments 一致性快照', output: 'reported 字段、gaps、conflicts、指纹', evidence: 'GET /api/v1/evaluation-evidence', boundary: '原始真实报告与评测口径待交付；不认定独立 Verify，不填真实成功率或恢复时延。', references: ['dashboard_api/evidence.py', 'docs/phase-c6-evidence-readiness.md'] },
    ],
    edges: [
      { from: 'import', to: 'sqlite', kind: 'data', label: '事件', route: 'M 25 24 H 41', arrow: 'M 31 24 H 33', labelX: 33, labelY: 7 },
      { from: 'sqlite', to: 'trajectory', kind: 'data', label: '只读', route: 'M 59 24 H 75', arrow: 'M 65 24 H 67', labelX: 67, labelY: 7 },
      { from: 'experiments', to: 'sqlite', kind: 'data', label: '运行关联', route: 'M 20 60 C 22 46 45 52 45 38', arrow: 'M 32 51 L 34 50', labelX: 32, labelY: 42 },
      { from: 'benchmark', to: 'sqlite', kind: 'data', label: '离线报告', route: 'M 50 60 V 38', arrow: 'M 50 51 V 49', labelX: 60, labelY: 55 },
      { from: 'sqlite', to: 'evidence', kind: 'data', label: '同源快照', route: 'M 55 38 C 55 53 80 46 80 60', arrow: 'M 65 48 L 67 49', labelX: 72, labelY: 42 },
    ],
  },
];

export function architectureNeighbors(layer: ArchitectureLayer, id: string) {
  return layer.edges.flatMap(edge => edge.from === id ? [edge.to] : edge.to === id ? [edge.from] : []);
}

export function architectureTabIndex(index: number, key: string, length: number): number | null {
  if (key === 'Home') return 0;
  if (key === 'End') return length - 1;
  if (key === 'ArrowDown') return (index + 1) % length;
  if (key === 'ArrowUp') return (index + length - 1) % length;
  return null;
}
