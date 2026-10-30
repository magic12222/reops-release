import { describe, expect, it, vi } from 'vitest';
import { DashboardApiError, readEvents, readRun, readRuns, readSystemStatus } from './api';
import { toReadTrace } from './adapter';
import type { EventRecord, RunRecord } from '../types/dashboard';

const run: RunRecord = {
  id: 'run-1', incident_id: 'incident-1', trace_id: 'trace-1', case_id: null, fault_id: null,
  source: 'real', status: 'unknown', started_at: null, finished_at: null,
  model_calls: null, action_count: null, recovery_latency_ms: null, success: null, metadata: {},
};
const event: EventRecord = {
  event_id: 'event-1', run_id: run.id, incident_id: run.incident_id, trace_id: run.trace_id,
  case_id: null, ordinal: 1, parent_event_id: null, stage: 'verification', status: null,
  timestamp: null, message: 'Verification evidence', source: 'real', origin: 'decision_trace',
  original_event_id: 'raw-1', data: { value: { status: 'not_recovered' } },
};
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json' },
});

describe('C read API client', () => {
  it('uses only same-origin GET without credentials or control token', async () => {
    const fetcher = vi.fn().mockResolvedValue(reply({ items: [run], total: 1, limit: 50, offset: 0 }));
    const page = await readRuns('real', undefined, fetcher as typeof fetch);
    expect(page.items[0].source).toBe('real');
    expect(fetcher).toHaveBeenCalledWith('/api/v1/runs?source=real&limit=50&offset=0',
      expect.objectContaining({ method: 'GET', credentials: 'omit', mode: 'same-origin', redirect: 'error' }));
    expect(fetcher.mock.calls[0][1].headers).toBeUndefined();
  });

  it('keeps unavailable system status instead of reporting healthy', async () => {
    const fetcher = vi.fn().mockResolvedValue(reply({ status: 'unavailable', source: 'real', components: {
      api: 'unavailable', postgres: 'unavailable', redis: 'unavailable', users: 'unavailable', control: 'unavailable',
    } })) as typeof fetch;
    expect((await readSystemStatus(undefined, fetcher)).status).toBe('unavailable');
  });

  it('keeps offline fixtures separate from real runs', async () => {
    const fixture = { ...run, source: 'offline_fixture' };
    const fetcher = vi.fn().mockResolvedValue(reply({ items: [fixture], total: 1, limit: 50, offset: 0 })) as typeof fetch;
    expect((await readRuns('offline_fixture', undefined, fetcher)).items[0].source).toBe('offline_fixture');
    await expect(readRuns('real', undefined, fetcher)).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('reports 404, network failure and malformed responses separately', async () => {
    const missing = vi.fn().mockResolvedValue(reply({ detail: 'missing' }, 404)) as typeof fetch;
    await expect(readRun(run.id, undefined, missing)).rejects.toMatchObject({ code: 'not_found' });
    const offline = vi.fn().mockRejectedValue(new TypeError('failed to fetch')) as typeof fetch;
    await expect(readRuns('real', undefined, offline)).rejects.toMatchObject({ code: 'unavailable' });
    const wrongSource = vi.fn().mockResolvedValue(reply({ items: [{ ...run, source: 'simulation' }], total: 1, limit: 50, offset: 0 })) as typeof fetch;
    await expect(readRuns('real', undefined, wrongSource)).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('accepts nullable event fields and preserves ordered evidence', async () => {
    const fetcher = vi.fn().mockResolvedValue(reply({ run_id: run.id, items: [event], total: 1 })) as typeof fetch;
    const page = await readEvents(run.id, undefined, fetcher);
    expect(page.items[0].timestamp).toBeNull();
    const earlier = { ...event, event_id: 'event-0', ordinal: 0, status: 'failed' as const };
    const trace = toReadTrace(run, [event, earlier]);
    expect(trace.map(step => step.event.event_id)).toEqual(['event-0', 'event-1']);
    expect(trace[0].time).toBe('无独立时间戳');
    expect(trace[0].event.status).toBe('failed');
  });

  it('rejects run/event correlation or provenance mismatch', () => {
    expect(() => toReadTrace(run, [{ ...event, source: 'simulation' }])).toThrow('trajectory_correlation_mismatch');
    expect(() => toReadTrace(run, [event, { ...event, event_id: 'other' }])).toThrow('trajectory_order_conflict');
    expect(new DashboardApiError('invalid_response').code).toBe('invalid_response');
  });
});
