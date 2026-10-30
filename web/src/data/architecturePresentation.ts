// Product-facing copy only. Verified contracts, paths and evidence stay in
// architecture.ts and the project documentation; graph relationships are reused.
export const architectureLayerPurposes: Readonly<Record<string, string>> = {
  system: 'A · 服务与故障环境',
  agent: 'B · 诊断与受限决策',
  evaluation: 'C · 只读回放与离线评估',
};

export const architectureNodeDescriptions: Readonly<Record<string, string>> = {
  docker: '编排基础服务，提供可复现的故障实验环境。',
  api: '提供业务与健康检查入口，连接数据库和缓存。',
  observer: '采集服务健康与请求结果，为故障诊断提供观测。',
  postgres: '为业务请求提供数据库查询。',
  redis: '为业务请求提供缓存写入。',
  executor: '校验恢复动作，并通过白名单执行固定操作。',
  diagnosis: '根据观测发现异常，定位故障组件和失败环节。',
  rca: '结合观测与历史证据，提供可选的诊断建议。',
  planner: '基于诊断结果与安全约束选择候选恢复动作。',
  memory: '记录和检索历史经验，为受约束的决策提供参考。',
  verify: '重新观测并核对服务健康与业务结果，验证恢复。',
  safety: '在执行前检查动作与安全条件，独立授权后才允许执行。',
  import: '导入并整理 Agent 事件，为轨迹回放与评估提供数据。',
  sqlite: '保存运行、事件与评估记录，提供一致的数据视图。',
  trajectory: '以只读方式展示事件轨迹并支持回放，不重新执行恢复。',
  experiments: '登记实验请求并关联运行记录，不直接触发恢复。',
  benchmark: '读取离线报告，核对场景指标与评估结果。',
  evidence: '核对执行与验证记录，呈现证据缺口和冲突。',
};
