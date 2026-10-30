import { describe, expect, it, vi } from 'vitest';
import { readExperimentControl, requestExperiment } from './experiments';

const reply = (value: unknown) => new Response(JSON.stringify(value), { status: 200 });

describe('C4 experiment client', () => {
  it('queues only the supported scenario with no token or challenge answer', async () => {
    const fetcher = vi.fn().mockResolvedValue(reply({ id: 'experiment-1' }));
    vi.stubGlobal('fetch', fetcher);
    try {
      await requestExperiment();
      expect(fetcher).toHaveBeenCalledWith('/api/v1/experiments', expect.objectContaining({
        method: 'POST', credentials: 'omit', mode: 'same-origin', redirect: 'error',
        body: '{"scenario":"phase8_stopped_api"}',
      }));
      const options = fetcher.mock.calls[0][1];
      expect(JSON.stringify(options)).not.toMatch(/REOPS_CONTROL_TOKEN|Bearer|challenge/);
    } finally { vi.unstubAllGlobals(); }
  });

  it('reads capabilities and records without browser authorization', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply({ entry: 'B Phase 8', scenarios: ['phase8_stopped_api'],
      request_enabled: false, request_blocked: false,
      execution: 'operator_terminal_only' })).mockResolvedValueOnce(reply({ items: [] }));
    vi.stubGlobal('fetch', fetcher);
    try {
      const data = await readExperimentControl();
      expect(data.capabilities.request_enabled).toBe(false);
      expect(data.items).toEqual([]);
      expect(fetcher.mock.calls.every((call: unknown[]) => (call[1] as RequestInit).credentials === 'omit')).toBe(true);
    } finally { vi.unstubAllGlobals(); }
  });
});
