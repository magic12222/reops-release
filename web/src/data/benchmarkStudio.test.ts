import { describe, expect, it } from 'vitest';
import { benchmarkData } from './demoData';
import { benchmarkMetrics, comparisonRows, metricValue, sampleDifference } from './benchmarkStudio';

describe('Benchmark sample comparison boundaries', () => {
  it('keeps every sample in the same zero-based domain', () => {
    for (const metric of benchmarkMetrics) for (const item of benchmarkData) {
      expect(metricValue(item, metric)).toBe(item[metric.key]);
      expect(item[metric.key] / metric.max).toBeGreaterThanOrEqual(0);
      expect(item[metric.key] / metric.max).toBeLessThanOrEqual(1);
    }
  });
  it('uses percentage points and signed seconds, with no invented measurement', () => {
    expect(sampleDifference(benchmarkData[2], benchmarkData[0], benchmarkMetrics[0])).toBe('+26 pp');
    expect(sampleDifference(benchmarkData[0], benchmarkData[2], benchmarkMetrics[0])).toBe('−26 pp');
    expect(sampleDifference(benchmarkData[2], benchmarkData[0], benchmarkMetrics[1])).toBe('−16.2 s');
    expect(sampleDifference({}, benchmarkData[0], benchmarkMetrics[0])).toBe('数据不足');
  });
  it('keeps zero tokens and rejects absent, invalid and out-of-domain data', () => {
    expect(metricValue(benchmarkData[0], benchmarkMetrics[4])).toBe(0);
    for (const value of [NaN, Infinity, -1, 101, undefined]) {
      expect(metricValue({ successRate: value }, benchmarkMetrics[0])).toBeNull();
    }
  });
  it('sorts numerical quantity without reversing values or mutating the input', () => {
    expect(comparisonRows(benchmarkData, benchmarkMetrics[1], 'ascending').map(item => item.id)).toEqual(['reops', 'llm', 'rule']);
    expect(comparisonRows(benchmarkData, benchmarkMetrics[2], 'descending').map(item => item.id)).toEqual(['llm', 'rule', 'reops']);
    expect(benchmarkData.map(item => item.id)).toEqual(['rule', 'llm', 'reops']);
  });
  it('keeps quantity differences signed, including zero, without claiming improvement', () => {
    expect(sampleDifference(benchmarkData[2], benchmarkData[0], benchmarkMetrics[3])).toBe('+37 pp');
    expect(sampleDifference(benchmarkData[2], benchmarkData[1], benchmarkMetrics[2])).toBe('−5 调用');
    expect(sampleDifference(benchmarkData[1], benchmarkData[0], benchmarkMetrics[4])).toBe('+6,400 tokens');
    expect(sampleDifference(benchmarkData[2], benchmarkData[1], benchmarkMetrics[4])).toBe('−3,600 tokens');
    expect(sampleDifference(benchmarkData[0], benchmarkData[0], benchmarkMetrics[4])).toBe('0 tokens');
  });
  it('separates null and missing quantities from zero, and sorts missing values last', () => {
    const metric = benchmarkMetrics[4];
    expect(metricValue(JSON.parse('{"tokens":null}'), metric)).toBeNull();
    expect(metricValue({}, metric)).toBeNull();
    expect(sampleDifference(JSON.parse('{"tokens":null}'), benchmarkData[0], metric)).toBe('数据不足');
    const items = [{ ...benchmarkData[0], tokens: NaN }, benchmarkData[1], benchmarkData[2]];
    expect(comparisonRows(items, metric, 'ascending').map(item => item.id)).toEqual(['reops', 'llm', 'rule']);
    expect(comparisonRows(items, metric, 'descending').map(item => item.id)).toEqual(['llm', 'reops', 'rule']);
  });
});
