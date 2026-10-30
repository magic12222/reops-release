import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { renderToStaticMarkup } from 'react-dom/server';
import { describe,expect,it,vi } from 'vitest';
import { createVikunjaClient,parseVikunjaState } from './vikunjaClient';
import { VikunjaRecoveryControl } from './VikunjaRecoveryControl';

const payload = () => ({available:true,demo_busy:false,demo:null,automation:{mode:'observe',state:'observe',offer_id:'bound-offer',
  remaining_actions:3,remaining_seconds:0,inflight:false,events:[],
  policy:{duration_hours:8,max_actions:3,cooldown_seconds:60,action:'start_service(postgres)',model_calls:0,fault_injection:false}}});

describe('Vikunja browser approval',() => {
  it('sends an explicit bound click and never a typed or echoed challenge',async () => {
    const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async () => ({csrf:'fixture-private'})})
      .mockResolvedValue({ok:true,json:async () => payload()});
    const client=createVikunjaClient(fetcher);
    expect(JSON.stringify(await client.status())).not.toContain('fixture-private');
    await client.enable('bound-offer');
    await client.approve('job','confirmation');
    expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual({approved:true,offer_id:'bound-offer'});
    expect(JSON.parse(fetcher.mock.calls[3][1].body)).toEqual({approved:true,job_id:'job',confirmation_id:'confirmation'});
    expect(fetcher.mock.calls[3][1]).toMatchObject({credentials:'same-origin',redirect:'error',mode:'same-origin'});
    expect(fetcher.mock.calls[3][1].body).not.toContain('challenge');
  });
  it('rejects policies that silently widen the approved scope',() => {
    for (const change of [{max_actions:100},{action:'restart_service(web)'},{model_calls:1},{fault_injection:true}]) {
      const state=payload();Object.assign(state.automation.policy,change);
      expect(() => parseVikunjaState(state)).toThrow();
    }
  });
  it('does not repeat a failed approval request or show raw server diagnostics',async () => {
    const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async () => ({csrf:'fixture-private'})})
      .mockResolvedValue({ok:false,status:409,json:async () => ({detail:'private-error'})});
    await expect(createVikunjaClient(fetcher).enable('offer')).rejects.toThrow('target state changed');
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it('keeps monitoring and recovery controls distinct in the confirmed English interface',() => {
    const html=renderToStaticMarkup(<VikunjaRecoveryControl active={false} />);
    expect(html).toContain('Monitoring continues');
    expect(html).toContain('Enable database-only recovery');
    expect(html).toContain('Prepare a demonstration');
    expect(html).not.toContain('AUTHORIZE');
    expect(html).not.toMatch(/[\u4e00-\u9fff]/);
  });
  it('uses a separate endpoint and explicit plan identifier for dependency approval',async()=>{
    const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({csrf:'fixture-private'})})
      .mockResolvedValue({ok:true,json:async()=>payload()});
    await createVikunjaClient(fetcher).enableDependency('new-dependency-offer');
    expect(fetcher.mock.calls[1][0]).toContain('/enable-dependency');
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({approved:true,offer_id:'new-dependency-offer',plan_id:'vikunja_dependency_v1'});
  });
  it('validates every fixed step and rejects widening or missing dependency scope',()=>{
    const plan={id:'vikunja_dependency_v1',max_database_starts_per_incident:1,max_application_starts_per_incident:1,
      sql_timeout_seconds:45,business_timeout_seconds:45,order:['start_postgres','wait_sql','start_exited_app_if_confirmed','two_fresh_business_checks']};
    const state={...payload(),automation:{...payload().automation,plan_id:'vikunja_dependency_v1',dependency_offer_id:'new-offer',dependency_plan:plan,
      policy:{...payload().automation.policy,action:'postgres_sql_then_conditional_app_start'}}};
    expect(parseVikunjaState(state).automation.plan_id).toBe('vikunja_dependency_v1');
    for(const change of [{max_application_starts_per_incident:2},{sql_timeout_seconds:120},{order:['start_postgres','start_exited_app_if_confirmed']}]){
      expect(()=>parseVikunjaState({...state,automation:{...state.automation,dependency_plan:{...plan,...change}}})).toThrow();
    }
    expect(()=>parseVikunjaState({...state,automation:{...state.automation,dependency_plan:undefined}})).toThrow();
    expect(()=>parseVikunjaState({...state,automation:{...state.automation,plan_id:'unknown'}})).toThrow();
  });
});
