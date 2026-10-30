import { getLocale, t } from '../i18n';
/** Exact, field-scoped display vocabulary. Unknown protocol values remain intact. */
const verification = { recovered: '已验证恢复', not_recovered: '未恢复', inconclusive: '证据不足', not_run: '未执行验证' };
const names: Record<string, Record<string, string>> = {
  root_cause: { postgres_service_down: 'PostgreSQL 服务不可用', api_service_down: 'API 服务不可用', web_service_down: 'Web 服务不可用',
    health_check_failed_cause_unknown: '健康检查失败，原因未确定', request_failed_cause_unknown: '请求失败，原因未确定' },
  failed_component: { postgres: 'PostgreSQL', api: 'API', web: 'Web', redis: 'Redis' },
  failed_step: { database_query: '数据库查询', service_status: '服务状态', health_check: '健康检查', http_request: 'HTTP 请求' },
  failure_type: { service_failure: '服务异常', health_check_failure: '健康检查失败', request_failure: '请求异常' },
  service_status: { healthy: '健康', degraded: '降级', unhealthy: '不健康', unknown: '未知' },
  execution_status: { succeeded: '执行成功', failed: '执行失败', rejected: '拒绝执行', skipped: '已跳过' },
  verification_status: verification, status: verification, final_status: { ...verification, not_run: '未运行' },
};
const owns = (object: object, key: string) => Object.prototype.hasOwnProperty.call(object, key);
export function agentValueName(key: string, value: string): string {
  return owns(names, key) && owns(names[key], value) ? t(names[key][value]) : value;
}
export function agentSentence(value: string): string {
  // Recorded prose is evidence, even when it happens to match a UI resource.
  return value;
}
export function agentNumber(value: number): string {
  return new Intl.NumberFormat(getLocale(), { maximumFractionDigits: 2 }).format(value);
}
export function agentDuration(value: number): string { return `${agentNumber(value)} ms`; }
/** Browser-local time, with consistent precision; originals retain their timezone. */
export function agentTime(value: string | null, missing = '未提供'): string {
  if (!value) return t(missing);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t('时间不可解析');
  const part = (number: number) => String(number).padStart(2, '0');
  return `${date.getFullYear()}-${part(date.getMonth() + 1)}-${part(date.getDate())} ${part(date.getHours())}:${part(date.getMinutes())}:${part(date.getSeconds())}`;
}
