import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { SoftwareDirectory } from './SoftwareDirectory';
import { createSoftwareCatalogClient, parseSoftwareCatalog } from './softwareCatalog';

const payload = () => ({source:'real',state:'ready',generated_at:'2026-10-28T01:00:00Z',interval_seconds:10,
  records:[{id:'process:editor',name:'Editor',kind:'process',pids:[1,2],ports:[8080],instances:2,memory_bytes:1024,windowed:true,image:null,project:null,service:null}],
  sources:{process:'ready',service:'ready',container:'ready',ports:'ready'},watches:[],omitted:0,
  capabilities:['liveness','listener_ports','working_set'],recovery_available:false});

describe('local software directory',()=>{
  it('validates real inventory and refuses fabricated permissions, duplicates and unbounded data',()=>{
    expect(parseSoftwareCatalog(payload()).records[0].name).toBe('Editor');
    for(const extra of [{source:'offline_fixture'},{recovery_available:true},{records:[payload().records[0],payload().records[0]]},
      {sources:{process:'invented'}},{interval_seconds:0},{records:[{...payload().records[0],ports:[65536]}]}]) {
      expect(()=>parseSoftwareCatalog({...payload(),...extra})).toThrow('invalid record');
    }
  });
  it('keeps basic watch requests separate from recovery and keeps the session private',async()=>{
    const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>payload()})
      .mockResolvedValueOnce({ok:true,json:async()=>({csrf:'private-session'})})
      .mockResolvedValue({ok:true,json:async()=>payload()});
    const client=createSoftwareCatalogClient(fetcher);
    expect(JSON.stringify(await client.read())).not.toContain('private-session');
    await client.watch('process:editor',true);
    await client.watch('process:editor',false);
    expect(fetcher.mock.calls.map(call=>call[0])).toEqual(['/api/v1/workbench/control/catalog','/api/v1/workbench/control/status','/api/v1/workbench/control/catalog/watch','/api/v1/workbench/control/catalog/watch']);
    expect(fetcher.mock.calls[2][1]).toMatchObject({method:'POST',credentials:'same-origin',body:'{"software_id":"process:editor","watching":true}'});
  });
  it('does not replace failed discovery with samples or backend error text',async()=>{
    const client=createSoftwareCatalogClient(vi.fn().mockResolvedValue({ok:false,json:async()=>({detail:'private'})}));
    await expect(client.read()).rejects.toThrow('not available');
  });
  it('renders running observations with a visible business-health boundary',()=>{
    const html=renderToStaticMarkup(<SoftwareDirectory data={parseSoftwareCatalog(payload())} error="" pending={false} onRefresh={()=>{}} onWatch={()=>{}}/>);
    for(const text of ['Editor','2 instances','Windows','Containers','Business health','dedicated adapter','Monitor Editor','TCP 8080'])expect(html).toContain(text);
    expect(html).not.toContain('Healthy');
  });
  it('shows partial and stale collection truthfully',()=>{
    const render=(extra:object)=>renderToStaticMarkup(<SoftwareDirectory data={parseSoftwareCatalog({...payload(),...extra})} error="" pending={false} onRefresh={()=>{}} onWatch={()=>{}}/>);
    expect(render({state:'partial',sources:{...payload().sources,service:'unavailable'}})).toContain('Missing sources are not treated as stopped');
    expect(render({state:'stale'})).toContain('Current running state is unknown');
  });
  it('offers business monitoring only for the configured Vikunja application container',()=>{
    const value=payload();
    const render=(project:string,service:string)=>renderToStaticMarkup(<SoftwareDirectory data={parseSoftwareCatalog({...value,records:[{...value.records[0],kind:'container',project,service}]})} error="" pending={false} onRefresh={()=>{}} onWatch={()=>{}} onBusiness={()=>{}}/>);
    expect(render('reops-vikunja-demo','app')).toContain('Enable business monitoring');
    expect(render('reops-vikunja-demo','postgres')).not.toContain('Enable business monitoring');
    expect(render('another-project','app')).not.toContain('Enable business monitoring');
  });
  it('does not present a stale negative watch as a current absence',()=>{
    const value=payload();
    const data=parseSoftwareCatalog({...value,state:'stale',watches:[{record:value.records[0],alive:false,last_seen_at:value.generated_at,history:[]}]});
    const html=renderToStaticMarkup(<SoftwareDirectory data={data} error="" pending={false} onRefresh={()=>{}} onWatch={()=>{}}/>);
    expect(html).toContain('software-liveness unknown');
    expect(html).not.toContain('software-liveness absent');
    expect(html).toContain('Stop basic monitor for Editor');
  });
});
