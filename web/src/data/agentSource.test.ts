import { describe, expect, it, vi } from 'vitest';
import { agentSource } from './agentSource';
import { toReadTrace } from './adapter';

describe('Agent independent offline source', () => {
  it('browses all three validated scenarios without fetching or needing services', async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError('C API offline'));
    const reader = agentSource('offline_fixture', fetcher);
    const page = await reader.readRuns();
    expect(page.total).toBe(3);
    expect(page.items.map(run => run.status)).toEqual(['recovered', 'failed', 'diagnosing']);
    const counts: number[] = [];
    for (const listed of page.items) {
      const run = await reader.readRun(listed.id);
      const events = await reader.readEvents(run.id);
      const trace = toReadTrace(run, events.items);
      expect(run.source).toBe('offline_fixture');
      expect(run.metadata.simulated).toBe(true);
      expect(trace.every(step => step.event.source === 'offline_fixture')).toBe(true);
      counts.push(trace.length);
    }
    expect(counts).toEqual([7, 5, 3]);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('preserves tool success separately from failed verification and incomplete evidence', async () => {
    const reader = agentSource('offline_fixture');
    const { items: runs } = await reader.readRuns();
    const failed = await reader.readEvents(runs[1].id);
    expect(failed.items.at(-2)?.status).toBe('success');
    expect(failed.items.at(-2)?.data.stdout).toContain('\n');
    expect(failed.items.at(-1)?.status).toBe('failed');
    expect(failed.items.at(-1)?.data.business_request_passed).toBe(false);
    const partial = await reader.readEvents(runs[2].id);
    expect(runs[2].success).toBeNull();
    expect(runs[2].finished_at).toBeNull();
    expect(partial.items.map(item => item.ordinal)).toEqual([0, 2, 5]);
    expect(partial.items[1]).toMatchObject({ status: null, timestamp: null, data: {} });
    expect(partial.items.some(item => item.stage === 'recovery_execution')).toBe(false);
  });

  it('returns independent snapshots and never routes missing local IDs to the API', async () => {
    const fetcher = vi.fn();
    const reader = agentSource('offline_fixture', fetcher);
    const page = await reader.readRuns();
    page.items[0].metadata.simulated = false;
    const events = await reader.readEvents(page.items[0].id);
    events.items[0].data.services = 'mutated';
    expect((await reader.readRun(page.items[0].id)).metadata.simulated).toBe(true);
    expect((await reader.readEvents(page.items[0].id)).items[0].data.services).toBeTypeOf('object');
    await expect(reader.readRun('not-local')).rejects.toMatchObject({ code: 'not_found' });
    await expect(reader.readEvents('not-local')).rejects.toMatchObject({ code: 'not_found' });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('honors cancellation before publishing a local snapshot', async () => {
    const controller = new AbortController();
    const pending = agentSource('offline_fixture').readRuns(controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('keeps REAL and server SIMULATION on the API without fixture fallback', async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError('C API offline'));
    for (const source of ['real', 'simulation'] as const) {
      const reader = agentSource(source, fetcher);
      await expect(reader.readRuns()).rejects.toMatchObject({ code: 'unavailable' });
      expect(fetcher).toHaveBeenLastCalledWith(`/api/v1/runs?source=${source}&limit=50&offset=0`, expect.any(Object));
      await expect(reader.readRun('fixture-postgres-recovered')).rejects.toMatchObject({ code: 'unavailable' });
      await expect(reader.readEvents('fixture-postgres-recovered')).rejects.toMatchObject({ code: 'unavailable' });
    }
    expect(fetcher).toHaveBeenCalledTimes(6);
  });
});
