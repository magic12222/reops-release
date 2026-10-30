import { t, getLocale } from '../i18n';
import type { StrategyMetrics } from '../types/metrics';

type MetricKey = 'successRate' | 'recoveryTime' | 'toolCalls' | 'coverage' | 'tokens';
export type ComparisonOrder = 'method' | 'ascending' | 'descending';
export type BenchmarkMetric = {
  key: MetricKey; index: string; label: string; shortLabel: string; unit: string; max: number;
  direction: string; caveat: string; format: (value: number | null) => string;
};
const format = (value: number | null) => value === null ? t("未提供") : value.toLocaleString(getLocale(), { maximumFractionDigits: 1 });
export const benchmarkMetrics: BenchmarkMetric[] = [
  { key: 'successRate', index: '01', label: 'Recovery success rate', shortLabel: "成功率", unit: '%', max: 100,
    direction: "成功率通常越高越好", caveat: "样例未提供成功判定与分母，不能用于判断真实恢复能力。", format },
  { key: 'recoveryTime', index: '02', label: 'Mean recovery time', shortLabel: "恢复时间", unit: 's', max: 30,
    direction: "同等任务与验证条件下，时间越短越好", caveat: "起止计时点与成功样本范围未定义；此处秒数不是实测恢复时延。", format },
  { key: 'toolCalls', index: '03', label: 'Mean tool calls', shortLabel: "工具调用", unit: 'calls', max: 12,
    direction: "调用量比较 · 不据此判定优劣", caveat: "工具调用应结合成功率、任务复杂度与工具范围判断；调用更少不等于方案更好。", format },
  { key: 'coverage', index: '04', label: 'Failure coverage', shortLabel: "故障覆盖", unit: '%', max: 100,
    direction: "覆盖比例 · 场景全集未定义", caveat: "故障类别与覆盖分母未提供，不能把样例覆盖率当作已验证的支持范围。", format },
  { key: 'tokens', index: '05', label: 'Token consumption', shortLabel: "Token 消耗", unit: 'tokens', max: 8000,
    direction: "正负差值表示数量增减，不代表性能提升", caveat: "差值为当前方案减参照方案的 Token 数量。Rule-based 的 0 tokens 来自静态视觉样例；未提供实际 usage，不能据此确认是否调用 LLM。模型和输入输出范围未提供，不能作为实测记录。", format },
];

// Reject absent, non-finite or out-of-domain values instead of inventing a plotted result.
export function metricValue(item: Partial<StrategyMetrics>, metric: BenchmarkMetric): number | null {
  const value = item[metric.key];
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= metric.max ? value : null;
}
export function comparisonRows(items: StrategyMetrics[], metric: BenchmarkMetric, order: ComparisonOrder) {
  if (order === 'method') return [...items];
  return [...items].sort((a, b) => {
    const left = metricValue(a, metric), right = metricValue(b, metric);
    if (left === null) return right === null ? 0 : 1;
    if (right === null) return -1;
    return order === 'ascending' ? left - right : right - left;
  });
}
export function sampleDifference(current: Partial<StrategyMetrics>, reference: Partial<StrategyMetrics>, metric: BenchmarkMetric) {
  const left = metricValue(current, metric), right = metricValue(reference, metric);
  if (left === null || right === null) return t("数据不足");
  const delta = Number((left - right).toFixed(1));
  return `${delta > 0 ? '+' : delta < 0 ? '−' : ''}${format(Math.abs(delta))} ${metric.unit === '%' ? 'pp' : t(metric.unit)}`;
}
