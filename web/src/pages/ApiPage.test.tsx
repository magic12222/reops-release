import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { setLocale } from '../i18n';
import { ApiManagementView, connectionSummary } from './ApiPage';
import type { ControlStatus, ModelCheck } from '../data/webControl';

const callbacks = { onKey: () => {}, onSave: () => {}, onTest: () => {}, onRefresh: () => {}, onEdit: () => {}, onCancel: () => {}, onFilter: () => {} };
const check: ModelCheck = { id: 'fixture', timestamp: '2026-10-27T05:00:00Z', success: true, duration_ms: 123, error: null, request_type: 'GET /models', model: 'DeepSeek-V3.1-W8A8' };
const state: ControlStatus = { enabled: true, busy: false, job: null, model: { configured: true, verified: true,
  source: 'existing_local', model: check.model, endpoint: 'http://aigw.dlut.edu.cn/v1', storage: 'server_process_memory', checks: [check] } };
const render = (value: ControlStatus | null, extra = {}) => renderToStaticMarkup(<ApiManagementView state={value} busy={false}
  apiKey="" error="" notice="" errorsOnly={false} {...callbacks} {...extra} />);

describe('separate API management page', () => {
  it('distinguishes durable restored configuration from connection verification and keeps the key blank',()=>{
    const html=render({...state,model:{...state.model,model:'Qwen3-8B',storage:'windows_credential_manager',storage_state:'saved',source:'persisted_local',verified:false,checks:[]}});
    expect(html).toContain('已持久保存');expect(html).toContain('Windows 用户的凭据管理器');
    expect(html).toContain('重启后需重新测试连接');expect(html).toContain('等待测试');
    expect(html).toContain('type="password"');expect(html).toContain('value=""');
    expect(html).not.toContain('重启后新增配置需重填');
  });
  it('does not claim a legacy in-memory configuration has already been permanently saved',()=>{
    const html=render({...state,model:{...state.model,storage:'windows_credential_manager',storage_state:'not_saved'}});
    expect(html).toContain('尚未持久保存');
  });
  it('shows a restore error without treating the default model as ready',()=>{
    const html=render({...state,model:{...state.model,configured:false,verified:false,storage:'windows_credential_manager',storage_state:'restore_failed',storage_error:'model_storage_restore_failed',checks:[]}});
    expect(html).toContain('本机配置或凭据未能恢复');expect(html).toContain('role="alert"');
    expect(html).not.toContain('模型列表验证通过');
  });
  it('renders actual configured service, editable metadata, blank password and measured connection results', () => {
    const html = render(state);
    expect(html).toContain('API 管理'); expect(html).toContain('type="password"');
    expect(html).toContain('value=""'); expect(html).toContain('123ms'); expect(html).toContain('GET /models');
    expect(html).not.toContain('>128<');
    expect(html).not.toMatch(/readonly=""/i); expect(html).toContain('新增 API');
    expect(html).toContain('选择或填写新提供商'); expect(html).toContain('实验推理仍需当次授权');
    expect(html).toContain('模型列表验证通过'); expect(html).toContain('读取模型列表成功不等于工作流通过');
    expect(html).toContain('需单独授权与验证');
  });
  it('keeps unknown state unavailable with no pretend success or inferred counts', () => {
    const html = render(null);
    expect(html).toContain('当前状态未知'); expect(html).not.toContain('<strong>连接成功</strong>');
    expect(html).toMatch(/disabled="">开始测试/); expect(html).toContain('暂无测试记录');
    expect(html).toContain('尚未读取到配置');expect(html).not.toContain('正在读取实际配置');
    expect(connectionSummary([])).toEqual({ count: 0, averageMs: null });
  });
  it('filters errors and locks configuration/test while a real job is busy', () => {
    const html = render({ ...state, busy: true, model: { ...state.model, verified: false, checks: [check,
      { ...check, id: 'failed', success: false, duration_ms: 200, error: 'model_authentication_rejected' }] } }, { errorsOnly: true });
    expect(html).toContain('连接测试失败'); expect(html).toContain('网关未接受 Key');
    expect(html).not.toContain('123ms'); expect(html).toMatch(/disabled="">开始测试/);
    expect(html).toContain('实验运行中');
  });
  it('does not reuse a previous key connection success after configuration changed', () => {
    const html = render({ ...state, model: { ...state.model, verified: false } });
    expect(html).toContain('请重新测试当前连接');
    expect(html).not.toContain('<strong>连接成功</strong>');
    expect(html).not.toContain('模型列表返回正常');
  });
  it('renders added providers separately and permits explicit selection without inventing availability', () => {
    const first = { ...state.model, id: 'first', name: 'DeepSeek', provider: '网关一', revision: 'a', active: true };
    const second = { ...state.model, id: 'second', name: '新增科研模型', provider: '自定义供应商', model: 'custom-model',
      endpoint: 'https://models.example.com/v1', revision: 'b', active: false, verified: false, checks: [] };
    const html = render({ ...state, model: { ...first, services: [first, second] } });
    expect(html).toContain('新增科研模型'); expect(html).toContain('自定义供应商');
    expect(html).toContain('设为当前'); expect(html).toContain('当前 ResearchLoop 服务');
    expect(html).toContain('待测试');
  });
  it('requires metadata and key for new services and blocks network tests with unsaved changes', () => {
    const html = render(state, { editingId: null, dirty: true, draft: { name: '', provider: '', model: '', endpoint: '' } });
    expect(html).toContain('新增 API 服务'); expect(html).toMatch(/disabled="">保存配置/);
    expect(html).toMatch(/disabled="">开始测试/); expect(html).toContain('未保存内容不会用于网络请求');
  });
});

// A translation conflict must not revert secure storage to a session-only claim.
describe('integrated persistent API presentation', () => {
  it('keeps saved state, revalidation and blank keys in both languages', () => {
    const restored = {...state, model: {...state.model, model:'Unknown', storage:'windows_credential_manager', storage_state:'saved' as const, source:'persisted_local', verified:false, checks:[]}};
    try {
      for (const language of ['zh-CN', 'en'] as const) {
        setLocale(language);
        const html = render(restored);
        expect(html).toContain(language==='en'?'Saved persistently':'已持久保存');
        expect(html).toContain(language==='en'?'Windows user credential manager':'Windows 用户的凭据管理器');
        expect(html).toContain(language==='en'?'Test the connection again after restarting':'重启后需重新测试连接');
        expect(html).toContain('Unknown');
        expect(html).toContain('type="password"');expect(html).toContain('value=""');
      }
    } finally { setLocale('zh-CN'); }
  });
  it('translates a restore failure and never presents it as a successful connection', () => {
    try {
      setLocale('en');
      const html=render({...state, model:{...state.model, configured:false, verified:false, checks:[], storage:'windows_credential_manager', storage_state:'restore_failed', storage_error:'model_storage_restore_failed'}});
      expect(html).toContain('Local configuration or credentials could not be restored');
      expect(html).toContain('role="alert"');
      expect(html).not.toContain('Model list verified');
    } finally { setLocale('zh-CN'); }
  });
});
