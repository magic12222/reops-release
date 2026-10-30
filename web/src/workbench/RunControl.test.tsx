import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { createControlClient } from '../data/webControl';
import type { PendingConfirmation, WebJob } from '../data/webControl';
import { RunControl } from './RunControl';

describe('single run control', () => {
  it('starts collapsed without the old experiment panel or ledger', () => {
    const html = renderToStaticMarkup(<RunControl active />);
    expect(html).toContain('Run recovery'); expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain('Prepare run'); expect(html).not.toMatch(/[\u4e00-\u9fff]/);
  });
  it('uses explicit run approval rather than answering individual challenges', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ accepted: true }) });
    const client = createControlClient(fetcher);
    await client.startRun('model');
    const pending = { id: 'consent-1' } as PendingConfirmation;
    const job = { id: 'run-1' } as WebJob;
    await client.approveRun(job, pending);
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/researchloop/control/runs');
    expect(fetcher.mock.calls[1][0]).toBe('/api/v1/researchloop/control/runs/run-1/approve');
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ confirmation_id: 'consent-1', approved: true });
    expect(fetcher.mock.calls[1][1].body).not.toContain('AUTHORIZE');
  });
});
