import { describe, expect, it, vi } from 'vitest';
import { createMonitorClient } from './monitorClient';
import { fixtureSnapshot } from './contract';
const payload = () => ({ enabled:true, busy:false, csrf:'fixture-monitor-token', feed:{ status:'ready', targets:fixtureSnapshot().targets } });
describe('monitoring control boundary',() => {
  it('exposes a validated single-approval capability without granting it from status reads',async()=>{
    const value={...payload(),unified_monitoring:true};const fetcher=vi.fn().mockResolvedValue({ok:true,json:async()=>value});
    expect((await createMonitorClient(fetcher).status()).unified_monitoring).toBe(true);
    expect(fetcher.mock.calls).toHaveLength(1);expect(fetcher.mock.calls[0][1].method).toBe('GET');
    fetcher.mockResolvedValue({ok:true,json:async()=>({...value,unified_monitoring:'true'})});
    await expect(createMonitorClient(fetcher).status()).rejects.toMatchObject({code:'invalid_response'});
  });
  it('keeps the session token inside the client and sends only fixed empty commands',async () => {
    const fetcher = vi.fn().mockResolvedValue({ok:true,json:async () => payload()});
    const client = createMonitorClient(fetcher);
    const state = await client.status();
    expect(JSON.stringify(state)).not.toContain('fixture-monitor-token');
    await client.command('start');
    expect(fetcher.mock.calls[1]).toEqual(['/api/v1/workbench/control/start',expect.objectContaining({method:'POST',body:'{}',credentials:'same-origin',headers:{'Content-Type':'application/json','X-ReOps-Monitor-Token':'fixture-monitor-token'}})]);
  });
  it('rejects invalid target data and transport failures without substituting fixtures',async () => {
    const value = payload(); value.feed.targets[0].health = 'invalid' as never;
    const fetcher = vi.fn().mockResolvedValue({ok:true,json:async () => value});
    await expect(createMonitorClient(fetcher).status()).rejects.toMatchObject({code:'invalid_response'});
    fetcher.mockRejectedValue(new Error('network'));
    await expect(createMonitorClient(fetcher).status()).rejects.toMatchObject({code:'unavailable'});
  });
  it('does not expose raw backend errors',async () => {
    const client = createMonitorClient(vi.fn().mockResolvedValue({ok:false,json:async () => ({detail:'private-diagnostics'})}));
    await expect(client.status()).rejects.toThrow('request was rejected');
  });
  it('reports B diagnosis separately from recovery and model permission',async () => {
    const value = {...payload(),agent:{enabled:true,state:'ready',execution_enabled:false,model_enabled:false}};
    const fetcher = vi.fn().mockResolvedValue({ok:true,json:async () => value});
    expect((await createMonitorClient(fetcher).status()).agent).toEqual(value.agent);
    for (const extra of [{execution_enabled:true},{model_enabled:true},{state:'invented'}]) {
      fetcher.mockResolvedValue({ok:true,json:async () => ({...value,agent:{...value.agent,...extra}})});
      await expect(createMonitorClient(fetcher).status()).rejects.toMatchObject({code:'invalid_response'});
    }
  });
});
