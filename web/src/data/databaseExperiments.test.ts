import { afterEach, describe, expect, it, vi } from 'vitest';
import { freshBusinessVerifications, readDatabaseExperiments, repairUsage } from './databaseExperiments';

afterEach(() => vi.unstubAllGlobals());

describe('database experiment evidence', () => {
  it('keeps called-but-missing usage unknown and does not read SDK estimates', () => {
    expect(repairUsage({ model_calls: 1, repair_usage: null, token_usage: { input_tokens: 100 }, measurements: {} })).toBeNull();
  });
  it('accepts same-run server usage and distinguishes no-model-call evidence', () => {
    const usage = { input_tokens: 603, output_tokens: 134, source: 'server_usage' };
    expect(repairUsage({ model_calls: 1, repair_usage: usage, measurements: { usage } })?.total).toBe(737);
    const report = { model_calls: 0, diagnosis_source: 'memory/rule-supported',
      repair_usage: { input_tokens: 0, output_tokens: 0, source: 'no_model_calls' },
      measurements: { provider_attempts: 0, requests: [] } };
    expect(repairUsage(report)?.source).toBe('no_model_calls');
    expect(repairUsage({ ...report, model_calls: 1 })).toBeNull();
    expect(repairUsage({ ...report, measurements: { provider_attempts: 0 } })).toBeNull();
    expect(repairUsage({ ...report, measurements: { provider_attempts: 1, requests: [] } })).toBeNull();
  });
  it('rejects invalid counts and contradictory usage', () => {
    for (const bad of [true, -1, NaN, Infinity, 1.5]) {
      expect(repairUsage({ model_calls: 1, repair_usage: { input_tokens: bad, output_tokens: 2, source: 'server_usage' }, measurements: {} })).toBeNull();
    }
    expect(repairUsage({ model_calls: 1, repair_usage: { input_tokens: 3, output_tokens: 2, source: 'server_usage' },
      measurements: { usage: { input_tokens: 4, output_tokens: 2, source: 'server_usage' } } })).toBeNull();
  });
  it('does not upgrade duplicate or unrelated verification samples', () => {
    const sample = { incident_id: 'incident', trace_id: 'trace', observation_id: 'one',
      business: { read_valid: true, database_sql_valid: true, probe_read_valid: true, write_valid: true } };
    const report = { incident_id: 'incident', trace_id: 'trace', recovery_verified: true,
      verify_observations: [sample, { ...sample, observation_id: 'two' }] };
    expect(freshBusinessVerifications(report)).toBe(2);
    expect(freshBusinessVerifications({ ...report, verify_observations: [sample, sample] })).toBe(0);
    expect(freshBusinessVerifications({ ...report, verify_observations: [sample, { ...sample, trace_id: 'other' }] })).toBe(0);
  });
  it('only reads the independent same-origin real ledger without credentials', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      scenario: 'researchloop_stopped_postgres', execution: 'operator_terminal_only', experiments: [] }) });
    vi.stubGlobal('fetch', fetcher);
    expect(await readDatabaseExperiments()).toEqual([]);
    expect(fetcher).toHaveBeenCalledWith('/api/v1/researchloop/experiments', expect.objectContaining({ credentials: 'omit', redirect: 'error' }));
    expect(fetcher.mock.calls[0][1].method).toBeUndefined();
  });
  it('rejects wrong source and does not fall back to fixtures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      scenario: 'phase8_stopped_api', execution: 'operator_terminal_only', experiments: [] }) }));
    await expect(readDatabaseExperiments()).rejects.toThrow('database_ledger_invalid');
  });
});
