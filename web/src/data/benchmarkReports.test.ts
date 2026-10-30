import { afterEach, describe, expect, it, vi } from 'vitest';
import { reportPage, reportDetail, validRate, reportReadFailure, readBenchmarkJson } from './benchmarkReports';

describe('Benchmark report response validation', () => {
  const summary = { id: 'sha', source: 'offline_fixture', mode: 'offline-fixture', sample_count: 1 };
  const group = { strategy: 'reops', suite: 'offline', sample_count: 1, case_ids: ['case'],
    metrics: { success: { numerator: 1, denominator: 1, rate: 1, missing: 0, status: 'available' } },
    fixture_model_calls: 1, real_model_calls: null, recovery_latency_ms: null,
    outcomes: { not_executed: 0, rejected: 0, result_unknown: 0 } };
  it('rejects cross-source lists and details, malformed objects and absent evidence fields', () => {
    expect(() => reportPage({ source: 'real', items: [summary] }, 'real')).toThrow();
    expect(() => reportDetail({ ...summary, provenance: {}, groups: [group] }, 'real', 'sha')).toThrow();
    for (const value of [null, {}, { ...summary, provenance: {}, groups: [{ ...group, outcomes: null }] },
      { ...summary, provenance: {}, groups: [{ ...group, case_ids: [] }] }]) {
      expect(() => reportDetail(value, 'offline_fixture', 'sha')).toThrow();
    }
  });
  it('preserves missing latency and real-model counts rather than filling them from fixtures', () => {
    const report = reportDetail({ ...summary, provenance: {}, groups: [group] }, 'offline_fixture', 'sha');
    expect(report.groups[0].real_model_calls).toBeNull();
    expect(report.groups[0].recovery_latency_ms).toBeNull();
    expect(reportPage({ source: 'real', items: [] }, 'real').items).toEqual([]);
  });
  it('accepts empty denominators and missing fields but refuses inconsistent rates', () => {
    expect(validRate({ numerator: 0, denominator: 0, rate: null, missing: 0, status: 'empty_denominator' })).toBe(true);
    expect(validRate({ numerator: 0, denominator: 1, rate: null, missing: 1, status: 'missing_fields' })).toBe(true);
    expect(validRate({ numerator: 1, denominator: 2, rate: .94, missing: 0, status: 'available' })).toBe(false);
    expect(validRate(null)).toBe(false);
    expect(validRate({ numerator: -1, denominator: 2, rate: .5, missing: 0, status: 'available' })).toBe(false);
  });
  it('classifies HTTP and invalid responses without exposing arbitrary backend errors', () => {
    expect(reportReadFailure(new Error('HTTP 500'))).toContain('HTTP 500');
    expect(reportReadFailure(new Error('invalid_response'))).toContain('响应格式无效');
    expect(reportReadFailure(new Error('private server details'))).not.toContain('private');
  });
});

describe('Benchmark read failures', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('preserves HTTP failures and retries the original source without a fallback', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('', { status: 500 }));
    vi.stubGlobal('fetch', fetch);
    const signal = new AbortController().signal;
    const path = '/api/v1/benchmarks?source=offline_fixture';
    for (let attempt = 0; attempt < 2; attempt++) {
      await expect(readBenchmarkJson(path, signal)).rejects.toThrow('HTTP 500');
    }
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch).toHaveBeenLastCalledWith(path, {
      method: 'GET', cache: 'no-store', credentials: 'omit', mode: 'same-origin', signal,
    });
  });
  it('rejects invalid JSON and preserves cancellation for evidence reads', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response('not JSON'))
      .mockRejectedValueOnce(new DOMException('Aborted', 'AbortError'));
    vi.stubGlobal('fetch', fetch);
    const signal = new AbortController().signal;
    const path = '/api/v1/evaluation-evidence?source=real&offset=0&limit=20';
    await expect(readBenchmarkJson(path, signal)).rejects.toThrow('invalid_response');
    await expect(readBenchmarkJson(path, signal)).rejects.toMatchObject({ name: 'AbortError' });
  });
});
