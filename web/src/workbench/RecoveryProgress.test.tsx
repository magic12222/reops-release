import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {renderToStaticMarkup} from 'react-dom/server';
import {describe,expect,it} from 'vitest';
import {RecoveryProgress} from './RecoveryProgress';
import type {VikunjaState} from './vikunjaClient';
function automation(names:string[]):VikunjaState['automation'] {return {mode:'automatic',state:'watching',offer_id:null,remaining_actions:3,remaining_seconds:100,inflight:false,policy:{duration_hours:8,max_actions:3,cooldown_seconds:60,action:'start_service(postgres)',model_calls:0,fault_injection:false},events:names.map(event=>({event,timestamp:'2026-10-28T04:42:33Z',trace_id:'trace-exact'}))};}
describe('workbench recovery summary',()=>{
  it('shows a historical result and exact execution link without duplicating the timeline',()=>{
    const a=automation(['fault_confirmed','database_started','verification_passed','recovery_verified']);a.events[3].timestamp='2026-10-28T04:43:35Z';
    const html=renderToStaticMarkup(<RecoveryProgress automation={a}/>);
    expect(html).toContain('Latest recovery');expect(html).toContain('Verified');expect(html).toContain('62.0s recorded span');expect(html).toContain('/execution?source=real&amp;trace=trace-exact');expect(html).not.toContain('<ol');expect(html).not.toContain('Database started');expect(html).not.toContain('Live recovery process');
  });
  it('requires an explicit in-flight state and never equates a command with success',()=>{
    const a=automation(['fault_confirmed','database_started']);
    expect(renderToStaticMarkup(<RecoveryProgress automation={a}/>)).toContain('Awaiting update');
    a.inflight=true;const html=renderToStaticMarkup(<RecoveryProgress automation={a}/>);
    expect(html).toContain('Recovery in progress');expect(html).toContain('Track execution');expect(html).not.toContain('>Verified<');
  });
  it('keeps the most recent completed run visible after a new policy approval',()=>{
    const html=renderToStaticMarkup(<RecoveryProgress automation={automation(['fault_confirmed','recovery_verified','policy_approved'])}/>);
    expect(html).toContain('Latest recovery');expect(html).toContain('Verified');
    const next=renderToStaticMarkup(<RecoveryProgress automation={automation(['fault_confirmed','recovery_verified','fault_confirmed'])}/>);
    expect(next).not.toContain('>Verified<');expect(next).toContain('Awaiting update');
  });
  it('retains failure and current health blockers without inventing a run',()=>{
    const a=automation(['fault_confirmed','recovery_requires_attention']);a.events[1].reason='dependency_business_timeout';
    const failed=renderToStaticMarkup(<RecoveryProgress automation={a}/>);expect(failed).toContain('Needs attention');expect(failed).toContain('dependency_business_timeout');
    const empty=renderToStaticMarkup(<RecoveryProgress automation={automation(['policy_approved'])} blockedReason="Application unavailable"/>);
    expect(empty).toContain('Recovery blocked: Application unavailable');expect(empty).not.toContain('/execution?');expect(empty).not.toContain('Latest recovery');
  });
  it.each(['zh-CN','en'] as const)('keeps the original failure reason when it matches a translation key in %s',locale=>{
    setLocale(locale);
    const a=automation(['fault_confirmed','recovery_requires_attention']);a.events[1].reason='Unknown';
    const html=renderToStaticMarkup(<RecoveryProgress automation={a}/>);
    expect(html).toContain('role="alert">Unknown</p>');
    expect(html).toContain(locale==='en'?'Needs attention':'需要关注');
  });
});
