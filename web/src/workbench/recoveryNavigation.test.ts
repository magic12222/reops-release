import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {describe,expect,it,vi} from 'vitest';
import {fixtureSnapshot} from './contract';

describe('same recovery navigation',()=>{
  it('preserves the exact trace and reading position across analysis, lookup and execution',async()=>{
    vi.resetModules();const flow=await import('./recoveryNavigation');
    expect(flow.beginRecoveryAnalysis('trace/one')).toBe('/execution?source=real&trace=trace%2Fone');
    flow.markRecoveryLookup('trace/one',{window:240,timeline:120,dialogue:360});flow.markRecoveryLookup('trace/one');
    flow.finishRecoveryLookup('trace/one');
    expect(flow.recoveryNavigation()).toEqual({trace:'trace/one',phase:'execution',position:{window:240,timeline:120,dialogue:360}});
  });
  it('refuses unrelated callbacks and a new incident taking over an active analysis',async()=>{
    vi.resetModules();const flow=await import('./recoveryNavigation');flow.beginRecoveryAnalysis('one');
    expect(flow.beginRecoveryAnalysis('two')).toBeNull();flow.markRecoveryLookup('two');flow.finishRecoveryLookup('two');
    expect(flow.recoveryNavigation()).toEqual({trace:'one',phase:'analysis'});
  });
  it('never reopens the current incident after returning from lookup',async()=>{
    vi.resetModules();const flow=await import('./recoveryNavigation');flow.beginRecoveryAnalysis('one');flow.markRecoveryLookup('one');flow.finishRecoveryLookup('one');
    expect(flow.beginRecoveryAnalysis('one')).toBeNull();expect(flow.beginRecoveryAnalysis('two')).toContain('trace=two');
  });
  it('cancels automatic navigation when the user leaves and starts no flow after a reload',async()=>{
    vi.resetModules();let flow=await import('./recoveryNavigation');flow.beginRecoveryAnalysis('one');flow.cancelRecoveryNavigation();flow.markRecoveryLookup('one');
    expect(flow.recoveryNavigation()).toBeNull();flow.beginRecoveryAnalysis('two');vi.resetModules();flow=await import('./recoveryNavigation');expect(flow.recoveryNavigation()).toBeNull();
  });
  it('requires a diagnosis record rather than treating later verification as initial analysis',async()=>{
    const {initialAnalysisCall}=await import('./recoveryNavigation');const incident=fixtureSnapshot().incidents[0];const call=incident.model_calls[0];
    expect(initialAnalysisCall({...incident,model_calls:[{...call,request:JSON.stringify({phase:'verification',round:3})}]})).toBeUndefined();
    const initial={...call,id:'initial',request:JSON.stringify({phase:'diagnosis',round:1})};
    expect(initialAnalysisCall({...incident,model_calls:[{...call,request:'broken'},initial]})).toBe(initial);
  });
});
