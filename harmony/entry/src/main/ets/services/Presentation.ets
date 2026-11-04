import { IncidentRecord, WorkbenchSnapshot, WorkbenchEvent, ExperienceRecord } from '../models/ApiModels';

export interface IncidentCounts { total: number; recovered: number; failed: number; active: number; unknown: number; }
export interface RecentEvent { incidentId: string; traceId: string; event: WorkbenchEvent; }

export function incidentTitle(value: string): string {
  return value === 'Automatic dependency recovery' ? '依赖服务自动恢复' : value;
}

export function statusLabel(value: string): string {
  const labels: Record<string, string> = {
    'not_started': '未开始', 'healthy': '健康', 'unhealthy': '异常', 'degraded': '降级', 'unavailable': '不可用', 'unknown': '未知',
    'observing': '观测中', 'diagnosing': '诊断中', 'waiting_human': '等待人工', 'executing': '执行中',
    'verifying': '验证中', 'recovered': '已恢复', 'failed': '失败', 'pending': '待验证', 'passed': '通过',
    'succeeded': '成功', 'running': '进行中', 'skipped': '已跳过', 'verified': '已验证',
    'unverified': '未验证', 'retired': '已停用', 'rule': '规则', 'model': '模型', 'experience': '历史经验',
    'ready': '已连接', 'not_connected': '未连接', 'observe': '观测', 'failure_detection': '故障检测',
    'localization': '故障定位', 'root_cause_analysis': '根因分析', 'recovery_decision': '恢复决策',
    'recovery_execution': '恢复执行', 'verification': '恢复验证', 'experience_update': '经验更新'
  };
  return labels[value] ?? value;
}
export function timeLabel(value: string | null): string {
  if (!value) return '时间不可用';
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN') : `时间不可解析：${value}`;
}
function timestamp(value: string): number {
  // No timezone means chronological position is ambiguous across hosts.
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value)) return Number.NaN;
  return Date.parse(value);
}
export function sortedIncidents(snapshot: WorkbenchSnapshot): IncidentRecord[] {
  return snapshot.incidents.slice().sort((a: IncidentRecord, b: IncidentRecord) => {
    const left = timestamp(a.started_at); const right = timestamp(b.started_at);
    if (!Number.isFinite(left)) return Number.isFinite(right) ? 1 : 0;
    return Number.isFinite(right) ? right - left : -1;
  });
}
export function incidentCounts(snapshot: WorkbenchSnapshot): IncidentCounts {
  const result: IncidentCounts = { total: snapshot.incidents.length, recovered: 0, failed: 0, active: 0, unknown: 0 };
  snapshot.incidents.forEach((i: IncidentRecord) => {
    if (i.status === 'recovered') result.recovered++;
    else if (i.status === 'failed') result.failed++;
    else if (i.status === 'unknown') result.unknown++;
    else result.active++;
  });
  return result;
}
export function recentEvents(snapshot: WorkbenchSnapshot): RecentEvent[] {
  const result: RecentEvent[] = [];
  snapshot.incidents.forEach((i: IncidentRecord) => i.events.forEach((e: WorkbenchEvent) => {
    if (Number.isFinite(timestamp(e.timestamp))) result.push({ incidentId: i.id, traceId: i.trace_id, event: e });
  }));
  return result.sort((a: RecentEvent, b: RecentEvent) => timestamp(b.event.timestamp) - timestamp(a.event.timestamp)).slice(0, 3);
}
export function relatedExperiences(snapshot: WorkbenchSnapshot, incident: IncidentRecord): ExperienceRecord[] {
  return snapshot.experiences.filter((e: ExperienceRecord) => incident.experience_ids.includes(e.id) && e.target_id === incident.target_id);
}
export function stageEvents(incident: IncidentRecord, stages: string[]): WorkbenchEvent[] {
  return incident.events.filter((e: WorkbenchEvent) => stages.includes(e.stage));
}
