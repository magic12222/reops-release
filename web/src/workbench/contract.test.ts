import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { describe, expect, it, vi } from 'vitest';
import { fixtureSnapshot, parseSnapshot, readWorkbench } from './contract';

describe('workbench contract and source boundary', () => {
  it('reads an independent, explicitly offline snapshot', () => {
    const data = fixtureSnapshot(); data.targets[0].name = 'changed';
    expect(fixtureSnapshot().targets[0].name).not.toBe('changed');
    expect(data.incidents[1].model_calls).toEqual([]);
    expect(() => parseSnapshot(data, 'real')).toThrow('correlation');
  });
  it.each([
    (data: ReturnType<typeof fixtureSnapshot>) => { data.incidents[0].target_id = 'missing'; },
    (data: ReturnType<typeof fixtureSnapshot>) => { data.incidents[0].events[0].sequence = 12; },
    (data: ReturnType<typeof fixtureSnapshot>) => { data.incidents[0].verification.status = 'pending'; },
    (data: ReturnType<typeof fixtureSnapshot>) => { data.incidents[1].experience_ids = []; },
    (data: ReturnType<typeof fixtureSnapshot>) => { data.experiences[0].incident_id = 'other'; },
    (data: ReturnType<typeof fixtureSnapshot>) => { data.incidents.push(data.incidents[0]); },
    (data: ReturnType<typeof fixtureSnapshot>) => { data.a_status = 'not_connected'; },
  ])('rejects record conflicts', change => {
    const data = fixtureSnapshot(); change(data);
    expect(() => parseSnapshot(data, 'offline_fixture')).toThrow();
  });
  it('rejects extra fields and malformed nested fields; retains unknown token counts', () => {
    const data = fixtureSnapshot();
    expect(() => parseSnapshot({ ...data, private_key: 'placeholder' }, 'offline_fixture')).toThrow();
    data.incidents[0].model_calls[0].input_tokens = null;
    expect(parseSnapshot(data, 'offline_fixture').incidents[0].model_calls[0].input_tokens).toBeNull();
    data.incidents[0].model_calls[0].output_tokens = -1;
    expect(() => parseSnapshot(data, 'offline_fixture')).toThrow();
  });
  it('uses only a same-origin GET and never falls back after an error', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false });
    await expect(readWorkbench(undefined, fetcher)).rejects.toThrow('unavailable');
    expect(fetcher).toHaveBeenCalledWith('/api/v1/workbench/snapshot', expect.objectContaining({ method: 'GET', credentials: 'omit', redirect: 'error' }));
    fetcher.mockResolvedValue({ ok: true, json: async () => fixtureSnapshot() });
    await expect(readWorkbench(undefined, fetcher)).rejects.toThrow('correlation');
  });
});
