import { t } from '../i18n';
export type BenchmarkSource = 'real' | 'offline_fixture' | 'simulation';
export type Rate = { numerator: number; denominator: number; rate: number | null; missing: number; status: string };
export type BenchmarkGroup = { strategy: string; suite: string; sample_count: number; metrics: Record<string, Rate>;
  fixture_model_calls: number | null; real_model_calls: number | null; recovery_latency_ms: number | null;
  case_ids: string[]; outcomes: { not_executed: number; result_unknown: number; rejected: number } };
export type ReportSummary = { id: string; source: BenchmarkSource; mode: string; sample_count: number };
export type BenchmarkReport = ReportSummary & { provenance: Record<string, unknown>; groups: BenchmarkGroup[] };
export const benchmarkSources: BenchmarkSource[] = ['real', 'offline_fixture', 'simulation'];
export const sourceNames: Record<BenchmarkSource, string> = { real: 'REAL', offline_fixture: 'OFFLINE FIXTURE', simulation: 'SIMULATION' };
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const optionalNumber = (value: unknown) => value === null || typeof value === 'number' && Number.isFinite(value) && value >= 0;
export function validRate(value: unknown): value is Rate {
  if (!object(value) || !count(value.numerator) || !count(value.denominator) || !count(value.missing)
    || value.numerator > value.denominator || value.missing > value.denominator) return false;
  if (value.status === 'available') return value.missing === 0 && value.denominator > 0
    && typeof value.rate === 'number' && Math.abs(value.rate - value.numerator / value.denominator) < 1e-9;
  return value.rate === null && (value.status === 'empty_denominator' && value.denominator === 0
    || value.status === 'missing_fields' && value.missing > 0);
}
function validSummary(value: unknown, source: BenchmarkSource): value is ReportSummary & Record<string, unknown> {
  return object(value) && value.source === source && typeof value.id === 'string' && value.id.length > 0
    && typeof value.mode === 'string' && count(value.sample_count);
}
export function reportPage(value: unknown, source: BenchmarkSource) {
  if (!object(value) || value.source !== source || !Array.isArray(value.items)
    || !value.items.every(item => validSummary(item, source))) throw new Error('invalid_response');
  return { items: value.items as ReportSummary[], importError: Boolean(value.last_import_error) };
}
export function reportDetail(value: unknown, source: BenchmarkSource, id: string): BenchmarkReport {
  if (!validSummary(value, source) || value.id !== id || !object(value) || !object(value.provenance)
    || !Array.isArray(value.groups) || !value.groups.every(group => object(group)
      && typeof group.strategy === 'string' && typeof group.suite === 'string' && count(group.sample_count)
      && Array.isArray(group.case_ids) && group.case_ids.length === group.sample_count && group.case_ids.every(id => typeof id === 'string')
      && object(group.metrics) && Object.values(group.metrics).every(validRate)
      && object(group.outcomes) && count(group.outcomes.not_executed) && count(group.outcomes.rejected) && count(group.outcomes.result_unknown)
      && optionalNumber(group.fixture_model_calls) && optionalNumber(group.real_model_calls) && optionalNumber(group.recovery_latency_ms))) {
    throw new Error('invalid_response');
  }
  return value as BenchmarkReport;
}
export async function readBenchmarkJson(path: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(path, { method: 'GET', cache: 'no-store', credentials: 'omit', mode: 'same-origin', signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  try { return await response.json(); } catch { throw new Error('invalid_response'); }
}
export function reportReadFailure(error: unknown) {
  const message = error instanceof Error ? error.message : '';
  if (/^HTTP 5\d{2}$/.test(message)) return t('{0} · 只读服务暂不可用，请重试。', message);
  if (/^HTTP \d{3}$/.test(message)) return t('{0} · 请求失败，请重试。', message);
  if (message === 'invalid_response') return t('响应格式无效，未展示此响应中的指标。');
  return t('请求未完成，请检查 C 只读服务连接后重试。');
}
