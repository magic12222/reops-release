import { t, useLocale, getLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import { Activity, Box, Check, Clock3, KeyRound, Pencil, Plus, RefreshCw, Server, X } from 'lucide-react';
import { ControlError, controlErrors, createControlClient } from '../data/webControl';
import type { ControlStatus, ModelCheck, ModelService, ServiceFields } from '../data/webControl';
import './ApiPage.css';

type Draft = Omit<ServiceFields, 'api_key'>;
const blank = (): Draft => ({ name: '', provider: '', model: '', endpoint: '' });
export function connectionSummary(checks: ModelCheck[]) {
  return { count: checks.length, averageMs: checks.length ? checks.reduce((sum, row) => sum + row.duration_ms, 0) / checks.length : null };
}
const elapsed = (ms: number | null) => ms === null ? '—' : ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
export function servicesFor(state: ControlStatus | null): ModelService[] {
  if (!state) return [];
  return state.model.services ?? [{ ...state.model, id: state.model.id ?? 'builtin-dlut', name: state.model.name ?? 'DeepSeek',
    provider: state.model.provider ?? '大工模型网关', revision: state.model.revision ?? 'legacy', active: true }];
}

export function ApiManagementView({ state, busy, apiKey, error, notice, errorsOnly, onKey, onSave, onTest, onRefresh, onEdit, onCancel, onFilter,
  draft: draftValue, editingId, testedId, dirty = false, onNew, onField, onServiceEdit, onSelect }: {
  state: ControlStatus | null; busy: boolean; apiKey: string; error: string; notice: string; errorsOnly: boolean;
  onKey: (value: string) => void; onSave: () => void; onTest: (id?: string) => void; onRefresh: () => void;
  onEdit: () => void; onCancel: () => void; onFilter: () => void;
  draft?: Draft; editingId?: string | null; testedId?: string | null; dirty?: boolean; onNew?: () => void;
  onField?: (field: keyof Draft, value: string) => void; onServiceEdit?: (service: ModelService) => void; onSelect?: (id: string) => void;
}) {
  useLocale();
  const services = servicesFor(state);
  const selected = services.find(item => item.id === (testedId ?? editingId)) ?? services.find(item => item.active);
  const draft = draftValue ?? { name: selected?.name ?? '', provider: selected?.provider ?? '', model: selected?.model ?? '', endpoint: selected?.endpoint ?? '' };
  const rows = services.flatMap(service => (service.checks ?? []).map(check => ({ ...check, serviceName: service.name })))
    .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));
  const checks = selected?.checks ?? [];
  const summary = connectionSummary(rows);
  const latest = checks.at(-1);
  const staleSuccess = !!latest?.success && !selected?.verified;
  const disabled = busy || !state?.enabled || state.busy;
  const persistent=state?.model.storage==='windows_credential_manager';
  const persisted=persistent&&state?.model.storage_state==='saved';
  const metrics = [
    { icon: Box, label: '已配置服务', value: state ? String(services.filter(item => item.configured).length) : '—', detail: persistent?'最多 16 条本机配置':'最多 16 条会话配置' },
    { icon: Server, label: '已验证连接', value: state ? String(services.filter(item => item.verified).length) : '—', detail: '模型列表鉴权通过' },
    { icon: Activity, label: '连接测试次数', value: state ? String(summary.count) : '—', detail: '每个服务保留最近 20 条' },
    { icon: Clock3, label: '平均测试耗时', value: elapsed(summary.averageMs), detail: 'GET /models · 非推理耗时' },
  ];
  const filtered = rows.filter(row => !errorsOnly || !row.success);
  return <section className="api-management shell" aria-label={t("API 管理")}>
    <header className="api-page-heading"><div><h1>{t("API Management")}</h1><p>{t("管理模型服务、提供商与 Key，逐条测试并选择当前连接。")}</p></div>
      <div className="api-toolbar"><span className="api-source"><i />{t("REAL · 实际配置")}</span>
        <button className="api-button" onClick={onNew ?? onEdit} disabled={disabled}><Plus size={16} />{t("新增 API")}</button>
        <button className="api-button" onClick={onRefresh} disabled={busy}><RefreshCw size={15} className={busy ? 'api-spinning' : ''} />{t("刷新")}</button></div>
    </header>
    {!state && <p className="api-message" role="status">{t("配置服务尚未连接，当前状态未知。请确认8020配置服务已启动，前端普通API代理指向8020、工作台代理单独指向8021；这不代表模型供应商连接测试失败。")}</p>}
    {state && !state.enabled && <p className="api-message" role="status">{t("本机网页配置入口尚未启用。")}</p>}
    {state?.busy && <p className="api-message" role="status">{t("实验运行中，连接配置与测试暂时锁定。")}</p>}
    {state?.model.storage_error&&<p className="api-message is-error" role="alert">{t(controlErrors[state.model.storage_error]??controlErrors.model_storage_restore_failed)}</p>}
    <section className="api-lifecycle" aria-label={t("API连接阶段")}><div><span>{t("01 · 配置服务")}</span><strong>{state?t('已连接'):t('尚未连接')}</strong></div><div><span>{t("02 · 选中配置")}</span><strong>{dirty||apiKey?t('存在未保存修改'):selected?.configured?persistent?(persisted?t('已持久保存'):t('尚未持久保存')):t('会话已保存'):t('尚未配置')}</strong></div><div><span>{t("03 · 模型列表")}</span><strong>{selected?.verified?t('已验证'):t('待验证')}</strong></div><div><span>{t("04 · 实际任务")}</span><strong>{t("需单独授权与验证")}</strong></div><p>{t("保存配置不会自动请求模型；读取模型列表成功不等于工作流通过。修改地址、模型或Key后需重新验证，实际运行使用当次绑定的配置。")}</p></section>
    <section className="api-panel api-overview"><h2>{t("API 概览")}</h2><div className="api-metrics">{metrics.map(({ icon: Icon, label, value, detail }) =>
      <div className="api-metric" key={label}><span className="api-metric-icon"><Icon size={27} strokeWidth={1.7} /></span><div><p>{t(label)}</p><strong>{value}</strong><small>{t(detail)}</small></div></div>)}</div></section>
    <section className="api-panel"><div className="api-panel-heading"><h2>{t("API 服务列表")}</h2><span>{t("OpenAI 兼容协议 · 当前服务单独标记")}</span></div>
      <div className="api-table-scroll"><table><thead><tr><th>{t("名称")}</th><th>{t("提供商 / 网关")}</th><th>{t("模型")}</th><th>{t("Base URL")}</th><th>{t("状态")}</th><th>{t("推理调用数")}</th><th>{t("操作")}</th></tr></thead>
        <tbody>{services.map(service => <tr key={service.id}><td className="api-service-name">{service.name}{service.active ? <small className="api-active-badge">{t("当前")}</small>:<small className="api-candidate-badge">{t("候选")}</small>}</td>
          <td><span className="api-provider">{service.provider}</span></td><td>{service.model}</td><td className="api-endpoint">{service.endpoint}</td>
          <td><span className={`api-connection ${service.verified ? 'is-connected' : ''}`}><i />{service.verified ? t('模型列表已验证') : service.configured ? t('待测试') : t('未配置')}</span></td><td><span title={t("尚未接入当日推理统计")}>{t("—")}</span></td>
          <td><div className="api-row-actions"><button className="api-button api-small" onClick={() => onTest(service.id)} disabled={disabled || !service.configured || dirty || !!apiKey}>{t("测试")}</button>
            <button className="api-button api-small" onClick={() => onServiceEdit ? onServiceEdit(service) : onEdit()} disabled={disabled} aria-label={t("编辑 {0} API", service.name)}><Pencil size={15} /></button>
            {!service.active && <button className="api-button api-small" onClick={() => onSelect?.(service.id)} disabled={disabled || !service.configured || dirty || !!apiKey}>{t("设为当前")}</button>}</div></td></tr>)}
          {!services.length && <tr><td colSpan={7} className="api-empty">{state ? t('暂无服务，可新增API配置。') : t('尚未读取到配置，请先确认配置服务连接。')}</td></tr>}</tbody></table></div>
    </section>
    <div className="api-bottom-grid">
      <section className="api-panel api-editor" id="api-editor"><div className="api-panel-heading"><h2>{editingId === null ? t('新增 API 服务') : t('编辑 API 服务')}</h2><span><KeyRound size={15} />{persistent?t('本机安全保存'):t('会话配置')}</span></div>
        <form onSubmit={event => { event.preventDefault(); onSave(); }}><div className="api-form-grid">
          <label>{t("名称")}<input value={draft.name} onChange={event => onField?.('name', event.target.value)} maxLength={128} placeholder={t("例如：科研推理服务")} disabled={disabled} required /></label>
          <label>{t("提供商")}<input value={draft.provider} onChange={event => onField?.('provider', event.target.value)} maxLength={128} list="api-providers" placeholder={t("选择或填写新提供商")} disabled={disabled} required />
            <datalist id="api-providers">{['DeepSeek', 'Qwen', 'MiniMax', 'GLM', '大工模型网关', '自定义兼容网关'].map(name => <option value={name} key={name} />)}</datalist></label>
          <label>{t("模型")}<input value={draft.model} onChange={event => onField?.('model', event.target.value)} maxLength={128} placeholder={t("填写服务端模型 ID")} disabled={disabled} required /></label>
          <label>{t("Base URL")}<input type="url" value={draft.endpoint} onChange={event => onField?.('endpoint', event.target.value)} maxLength={512} placeholder={t("https://gateway.example.com/v1")} disabled={disabled} required /></label>
          <label className="api-key-field">{t("API Key")}<input id="api-key" aria-label={t("API Key")} type="password" value={apiKey} onChange={event => onKey(event.target.value)} disabled={disabled}
            autoComplete="off" spellCheck={false} maxLength={2048} placeholder={editingId ? t('留空保留原 Key；更换地址须重新填写') : t('粘贴新服务的完整 API Key')} /></label>
        </div><p className="api-form-note">{t("支持 OpenAI 兼容接口；自定义地址使用公共 HTTPS，大工既有 HTTP 网关例外。")}{persistent?t('点击保存后，配置列表与当前选择会在重启后恢复；Key 仅存入当前 Windows 用户的凭据管理器。重启后需重新测试连接。'):t('配置和 Key 仅保留在当前服务内存；加载新版配置服务后可启用本机安全保存。')}</p>
        <div className="api-form-actions"><button className="api-button" type="button" onClick={onCancel}>{t("取消")}</button><button className="api-button api-primary" type="submit"
          disabled={disabled || !draft.name.trim() || !draft.provider.trim() || !draft.model.trim() || !draft.endpoint.trim() || editingId === null && !apiKey}>{t("保存配置")}</button></div></form>
        {error && <p className="api-message is-error" role="alert">{t(error)}</p>}{notice && <p className="api-message" role="status">{t(notice)}</p>}
      </section>
      <div className="api-test-column"><section className="api-panel"><div className="api-panel-heading"><h2>{t("连通性测试")}</h2><button className="api-button api-test" disabled={disabled || !selected?.configured || dirty || !!apiKey} onClick={() => onTest(selected?.id)}>{busy ? t('处理中…') : t('开始测试')}</button></div>
        <p className="api-test-target">{t("测试对象：")}{selected?.name ?? t('尚未选择服务')}</p>
        <div className={`api-test-result ${latest?.success && selected?.verified ? 'is-connected' : ''}`}><span className="api-result-icon">{latest && !staleSuccess ? latest.success && selected?.verified ? <Check size={23} /> : <X size={23} /> : <Activity size={23} />}</span>
          <div><strong>{dirty || apiKey ? t('请先保存或取消修改') : selected?.verified ? t('模型列表验证通过') : latest && !latest.success ? t('连接测试失败') : t('等待测试')}</strong>
            <p>{dirty || apiKey ? t('未保存内容不会用于网络请求。') : staleSuccess ? t('配置或当前服务已更新，请重新测试当前连接。') : latest ? latest.success ? t("模型列表返回正常，耗时 {0}", t(elapsed(latest.duration_ms))) : t(controlErrors[latest.error ?? ''] ?? '连接暂不可用。') : t('测试将读取模型列表，不发送推理请求。')}</p>
          </div></div><p className="api-test-note">{t("设为当前后须重新测试连接；实验推理仍需当次授权。")}</p>
      </section>
      <section className="api-panel api-log-panel"><div className="api-panel-heading"><h2>{t("最近连接测试")}</h2><button className="api-text-button" onClick={onFilter} aria-pressed={errorsOnly}>{errorsOnly ? t('查看全部') : t('只看错误')}</button></div>
        <div className="api-table-scroll"><table><thead><tr><th>{t("时间")}</th><th>{t("服务")}</th><th>{t("请求类型")}</th><th>{t("状态")}</th><th>{t("耗时")}</th></tr></thead><tbody>
          {filtered.map(row => <tr key={row.id}><td>{t(new Date(row.timestamp).toLocaleTimeString(getLocale(), { hour12: false }))}</td><td><span className="api-provider">{row.serviceName}</span></td><td>{row.request_type}</td><td className={row.success ? 'api-success' : 'api-failure'}>{row.success ? t('成功') : t('失败')}</td><td>{t(elapsed(row.duration_ms))}</td></tr>)}
          {!filtered.length && <tr><td colSpan={5} className="api-empty">{errorsOnly ? t('暂无失败的连接测试') : t('暂无测试记录，点击「开始测试」获取实际结果')}</td></tr>}
        </tbody></table></div><p className="api-test-note">{t("仅记录本次服务中的连接测试，不包含实验推理日志。")}</p>
      </section></div>
    </div><div className="api-page-footer"><span>{t("当前 ResearchLoop 服务：")}{services.find(item => item.active)?.name ?? t('未知')}</span><a href="/agent#researchloop-controls">{t("前往 Agent 演示 →")}</a></div>
  </section>;
}

export function ApiPage() {
  useLocale();
  const client = useRef(createControlClient()).current;
  const [state, setState] = useState<ControlStatus | null>(null);
  const [apiKey, setKey] = useState('');
  const [draft, setDraft] = useState<Draft>(blank);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingRevision,setEditingRevision]=useState<string|undefined>();
  const [testedId, setTestedId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [errorsOnly, setErrorsOnly] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true; let reading = false; const abort = new AbortController();
    const refresh = async () => { if (reading) return; reading = true;
      try { const value = await client.status(abort.signal); if (alive.current) setState(value); }
      catch { if (alive.current) setState(null); } finally { reading = false; }
    };
    void refresh(); const timer = window.setInterval(refresh, 2500);
    return () => { alive.current = false; abort.abort(); window.clearInterval(timer); };
  }, [client]);
  const action = async (operation: () => Promise<unknown>, success = '') => {
    setBusy(true); setError(''); setNotice('');
    try { await operation(); const value = await client.status(); if (alive.current) { setState(value); setNotice(success); } }
    catch (err) { if (alive.current) { setError(err instanceof ControlError ? err.message : '操作未完成，请核对连接状态。');
      try { const value = await client.status(); if (alive.current) setState(value); } catch { if (alive.current) setState(null); } } }
    finally { if (alive.current) setBusy(false); }
  };
  const focus = () => document.getElementById('api-editor')?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  const edit = (service: ModelService) => { setEditingId(service.id);setEditingRevision(service.revision); setDraft({ name: service.name, provider: service.provider, model: service.model, endpoint: service.endpoint }); setKey(''); setDirty(false); setError(''); setNotice(''); setTestedId(service.id); focus(); };
  const clear = () => { setDraft(blank()); setEditingId(null);setEditingRevision(undefined); setKey(''); setDirty(false); setError(''); setNotice(''); };
  return <ApiManagementView state={state} busy={busy} apiKey={apiKey} draft={draft} editingId={editingId} testedId={testedId} dirty={dirty}
    error={error} notice={notice} errorsOnly={errorsOnly} onField={(field, value) => { setDraft(old => ({ ...old, [field]: value })); setDirty(true); }}
    onKey={value => { setKey(value); setDirty(true); }} onSave={() => { const key = apiKey; setKey(''); void action(async () => {
      const saved = await client.saveService({ ...draft, api_key: key }, editingId ?? undefined,editingRevision);
      if (alive.current && saved && typeof saved === 'object' && 'id' in saved && typeof saved.id === 'string') { setEditingId(saved.id);setEditingRevision('revision' in saved&&typeof saved.revision==='string'?saved.revision:undefined); setTestedId(saved.id); setDirty(false); }
    }, state?.model.storage==='windows_credential_manager'?'候选配置与 Key 已安全保存在本机，重启后仍会保留；选择「设为当前」后重新测试，才会用于后续实验。':'候选配置已保存到本次会话；选择「设为当前」后重新测试，才会用于后续实验。'); }}
    onTest={id => { const target = id ?? testedId ?? state?.model.id; if (!target) return; setTestedId(target); void action(() => client.verifyService(target), '模型列表验证通过，尚未发送推理请求。'); }}
    onSelect={id => { setTestedId(id); void action(() => client.selectService(id), state?.model.storage==='windows_credential_manager'?'当前服务已切换并保存，重启后仍会选中；请重新测试连接后开始实验。':'当前服务已切换，请重新测试连接后开始实验。'); }}
    onNew={() => { clear(); focus(); }} onServiceEdit={edit} onRefresh={() => void action(() => client.status())} onEdit={focus} onCancel={clear} onFilter={() => setErrorsOnly(value => !value)} />;
}
