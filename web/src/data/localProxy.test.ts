import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {describe,expect,it} from 'vitest';
import {localProxy} from './localProxy';
describe('local service routing',()=>{
  it('preserves the original single dashboard default and browser Host',()=>expect(localProxy({})).toEqual({'/api/v1/workbench':{target:'http://127.0.0.1:8020',changeOrigin:false},'/api/v1':{target:'http://127.0.0.1:8020',changeOrigin:false}}));
  it('routes only workbench requests to the dedicated monitor',()=>{
    const value=localProxy({REOPS_DASHBOARD_PROXY:'http://127.0.0.1:8020',REOPS_WORKBENCH_PROXY:'http://127.0.0.1:8021'});
    expect(Object.keys(value)).toEqual(['/api/v1/workbench','/api/v1']);
    expect(value['/api/v1/workbench'].target).toContain('8021');expect(value['/api/v1'].target).toContain('8020');
    expect(value['/api/v1/workbench'].changeOrigin).toBe(false);expect(value['/api/v1'].changeOrigin).toBe(false);
  });
});
