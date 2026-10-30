import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { describe, expect, it, vi } from 'vitest';
import { createControlClient } from './webControl';
import type { PendingConfirmation, WebJob } from './webControl';

const pending: PendingConfirmation = { id: 'confirmation-fixture', challenge: 'AUTHORIZE recovery 0123456789abcdef',
  expires_at: 1900000000, request: { purpose: 'recovery', binding: { target: 'postgres' } } };
const job: WebJob = { id: 'job-fixture', strategy: 'model', state: 'running', incident_id: 'incident-fixture',
  trace_id: 'trace-fixture', experiment_id: null, result: null, error: null, cancel_requested: false, confirmation: pending };
const status = { enabled: true, busy: true, csrf: 'fixture-session-token', model: {
  configured: true, verified: true, source: 'existing_local', model: 'model-fixture', endpoint: 'endpoint-fixture', storage: 'server_process_memory',
}, job };
const reply = (value: unknown, code = 200) => new Response(JSON.stringify(value), { status: code });

describe('independent browser manual authorization client', () => {
  it('binds an edit to the configuration revision read by the editor',async()=>{
    const fetcher=vi.fn().mockResolvedValueOnce(reply(status)).mockResolvedValue(reply({id:'candidate',revision:'next'}));
    const client=createControlClient(fetcher as typeof fetch);await client.status();
    await client.saveService({name:'Candidate',provider:'Fixture',model:'model',endpoint:'https://fixture.example/v1',api_key:''},'candidate','original-revision');
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({expected_revision:'original-revision',as_candidate:true});
    expect(fetcher.mock.calls[1][0]).toBe('/api/v1/researchloop/control/services/candidate');
  });
  it('keeps session token out of rendering state and sends only the actual typed answer', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply(status)).mockResolvedValueOnce(reply({ accepted: true }));
    const client = createControlClient(fetcher as typeof fetch);
    const state = await client.status();
    expect(JSON.stringify(state)).not.toContain(status.csrf);
    await client.confirm(job, pending, 'manually-typed-wrong-answer');
    expect(fetcher.mock.calls[1]).toEqual(['/api/v1/researchloop/control/jobs/job-fixture/confirmation',
      expect.objectContaining({ method: 'POST', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { 'Content-Type': 'application/json', 'X-ReOps-UI-Token': status.csrf },
        body: JSON.stringify({ confirmation_id: pending.id, answer: 'manually-typed-wrong-answer' }) })]);
    expect(fetcher.mock.calls[1][1].body).not.toContain(pending.challenge);
  });
  it('submits a key only to the fixed local endpoint and does not echo raw errors', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply(status)).mockResolvedValueOnce(reply({ detail: 'fixture-private-key' }, 500));
    const client = createControlClient(fetcher as typeof fetch);
    await client.status();
    await expect(client.setKey('fixture-private-key')).rejects.toMatchObject({ code: 'web_control_rejected' });
    expect(fetcher.mock.calls[1][0]).toBe('/api/v1/researchloop/control/model');
    expect(fetcher.mock.calls[1][1].method).toBe('PUT');
  });
  it('rejects malformed or unbound challenge data rather than presenting it', async () => {
    for (const confirmation of [{ ...pending, challenge: 'AUTHORIZE experiment 0123456789abcdef' },
      { ...pending, request: { purpose: 'recovery' } }, { ...pending, expires_at: null }]) {
      const client = createControlClient(vi.fn().mockResolvedValue(reply({ ...status, job: { ...job, confirmation } })) as typeof fetch);
      await expect(client.status()).rejects.toMatchObject({ code: 'invalid_response' });
    }
  });
  it('keeps network or non-JSON failure unavailable without rendering transport data', async () => {
    const network = createControlClient(vi.fn().mockRejectedValue(new Error('fixture-private-key')) as typeof fetch);
    await expect(network.status()).rejects.toMatchObject({ code: 'unavailable' });
    const bad = createControlClient(vi.fn().mockResolvedValue(new Response('fixture-private-key')) as typeof fetch);
    await expect(bad.status()).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('accepts only measured connection metadata and strips unrelated raw fields', async () => {
    const check = { id: 'fixture', timestamp: '2026-10-27T05:00:00Z', success: true, duration_ms: 100,
      error: null, request_type: 'GET /models', model: 'fixture-model', raw: 'fixture-private-value' };
    const fetcher = vi.fn().mockResolvedValueOnce(reply({ ...status, model: { ...status.model, checks: [check] } }))
      .mockResolvedValueOnce(reply({ ...status, model: { ...status.model, checks: [{ ...check, duration_ms: -1 }] } }));
    const client = createControlClient(fetcher as typeof fetch);
    const value = await client.status();
    expect(value.model.checks?.[0].duration_ms).toBe(100);
    expect(JSON.stringify(value)).not.toContain('fixture-private-value');
    await expect(client.status()).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('saves multiple services without silently selecting or testing and uses explicit per-service endpoints', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply(status)).mockImplementation(() => Promise.resolve(reply({ id: 'new-service' })));
    const client = createControlClient(fetcher as typeof fetch);
    await client.status();
    const fields = { name: 'New', provider: 'New provider', model: 'new-model', endpoint: 'https://example.com/v1', api_key: 'fixture-only-key' };
    await client.saveService(fields);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[1][0]).toBe('/api/v1/researchloop/control/services');
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual(fields);
    await client.saveService({ ...fields, api_key: '' }, 'new-service');
    expect(fetcher.mock.calls[2][1].method).toBe('PUT');
    await client.selectService('new-service'); await client.verifyService('new-service');
    expect(fetcher.mock.calls[3][0]).toContain('/services/new-service/select');
    expect(fetcher.mock.calls[4][0]).toContain('/services/new-service/verify');
  });
  it('strips key fields from nested service status and preserves provider identity', async () => {
    const service = { ...status.model, id: 'service', name: 'New', provider: 'Custom', revision: 'rev', active: true, api_key: 'fixture-only-key' };
    const client = createControlClient(vi.fn().mockResolvedValue(reply({ ...status, model: { ...service, services: [service] } })) as typeof fetch);
    const result = await client.status();
    expect(result.model.services?.[0].provider).toBe('Custom');
    expect(JSON.stringify(result)).not.toContain('fixture-only-key');
  });
});
