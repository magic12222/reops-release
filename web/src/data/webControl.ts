/** 会话令牌只在此闭包内；Key/挑战回复不写浏览器持久存储。 */
export type ObjectValue = Record<string, unknown>;
export interface ModelCheck { id: string; timestamp: string; success: boolean; duration_ms: number; error: string | null; request_type: string; model: string }
export interface ModelStatus { configured: boolean; verified: boolean; source: string; model: string; endpoint: string; storage: string; storage_state?: string; storage_error?: string|null; checks?: ModelCheck[]; id?: string; name?: string; provider?: string; revision?: string; services?: ModelService[] }
export type ModelService = Omit<ModelStatus, 'services'> & { id: string; name: string; provider: string; revision: string; active: boolean };
export interface ServiceFields { name: string; provider: string; model: string; endpoint: string; api_key: string }
export interface PendingConfirmation { id: string; challenge: string; expires_at: number; request: { purpose: 'experiment' | 'model' | 'recovery'; binding: ObjectValue; authorization_mode?: 'single_run'; policy?: ObjectValue } }
export interface WebJob { id: string; strategy: 'model' | 'experience'; state: 'running' | 'finished'; incident_id: string; trace_id: string; experiment_id: string | null; result: string | null; error: string | null; cancel_requested: boolean; confirmation: PendingConfirmation | null }
export interface ControlStatus { enabled: boolean; busy: boolean; model: ModelStatus; job: WebJob | null }
const obj = (v: unknown): v is ObjectValue => typeof v === 'object' && v !== null && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && v.length > 0;

export const controlErrors: Record<string, string> = {
  model_endpoint_invalid: '请输入公共 HTTPS Base URL（大工既有 HTTP 地址例外），不含凭据、查询参数或内网地址。',
  model_service_invalid: '请填写名称、提供商和模型，每项最多128个字符。', model_service_limit: '当前会话最多配置16个服务。',
  model_service_not_found: '该服务不存在，请刷新列表。', model_endpoint_requires_key: '更换 Base URL 时请重新填写 Key，避免把原凭据发送到新地址。',
  model_service_revision_conflict: '这条配置已被其他页面修改，请重新读取配置后再编辑，当前连接没有被覆盖。',
  model_storage_unavailable: 'Windows 凭据管理器暂不可用，配置未保存，当前连接未改变。',
  model_storage_write_failed: '本机配置写入失败，配置未保存，当前连接未改变。',
  model_storage_invalid: '已保存的配置格式无效，未覆盖原文件或切换模型。',
  model_storage_conflict: '其他配置服务已更新本机配置，请重新加载配置服务后再编辑，未覆盖其修改。',
  model_storage_busy: '本机配置正在保存，请稍后重试。',
  model_storage_restore_failed: '本机配置或凭据未能恢复。已停止使用默认连接，请检查当前 Windows 账户及已保存配置。',
  unavailable: '操作服务不可达，请刷新确认服务状态。', invalid_response: '操作服务返回格式无效，未继续执行。',
  local_same_origin_required: '操作只允许从本机原页面发起。', browser_session_invalid: '页面会话已失效，请刷新后重试。',
  web_operations_disabled: '本机网页操作入口尚未启用。', experiment_busy: '已有实验运行，请等待验证与善后结束。',
  model_key_invalid_format: '请输入完整单行 Key，不含空格或换行。', model_key_missing: '请先填写 Key。',
  model_connection_not_verified: '请先验证模型连接。', model_authentication_rejected: '网关未接受 Key，请核对令牌及权限。',
  model_gateway_rejected: '网关拒绝读取模型列表，请稍后核对。', model_gateway_unavailable: '模型列表暂时不可达，未发送推理请求。',
  model_not_available: '此 Key 的模型列表中没有当前演示所需模型。', experiment_start_rate_limited: '启动过于频繁，请稍后再试。',
  confirmation_text_mismatch: '输入与本次挑战不一致，请按原文填写。', confirmation_expired_or_consumed: '本次挑战已过期或已消费，请等待流程结束。',
  web_job_not_found: '此实验不属于当前浏览器会话。', web_job_already_finished: '此实验已经结束，原确认不能重复使用。',
  web_worker_unavailable: '无法启动本机实验，尚未获得操作授权。', web_control_rejected: '操作未被接受，请核对当前状态。',
};
export class ControlError extends Error {
  constructor(public readonly code: string) { super(controlErrors[code] ?? controlErrors.web_control_rejected); }
}

function validJob(job: unknown): job is WebJob | null {
  if (job === null) return true;
  if (!obj(job) || !text(job.id) || !text(job.incident_id) || !text(job.trace_id)
      || !['model', 'experience'].includes(String(job.strategy)) || !['running', 'finished'].includes(String(job.state))
      || typeof job.cancel_requested !== 'boolean') return false;
  const p = job.confirmation;
  return p === null || obj(p) && text(p.id) && text(p.challenge)
    && typeof p.expires_at === 'number' && Number.isFinite(p.expires_at)
    && obj(p.request) && obj(p.request.binding) && ['experiment', 'model', 'recovery'].includes(String(p.request.purpose))
    && new RegExp(`^AUTHORIZE ${p.request.purpose} [a-f0-9]{16}$`).test(p.challenge);
}

function parseModel(model: ObjectValue): ModelStatus {
  if (typeof model.configured !== 'boolean' || typeof model.verified !== 'boolean' || !text(model.model) || !text(model.endpoint)) throw new ControlError('invalid_response');
      const checks: ModelCheck[] = [];
      if (model.checks !== undefined) {
        if (!Array.isArray(model.checks) || model.checks.length > 20) throw new ControlError('invalid_response');
        for (const row of model.checks) {
          if (!obj(row) || !text(row.id) || !text(row.timestamp) || !Number.isFinite(Date.parse(row.timestamp))
              || typeof row.success !== 'boolean' || typeof row.duration_ms !== 'number'
              || !Number.isFinite(row.duration_ms) || row.duration_ms < 0 || row.request_type !== 'GET /models'
              || !text(row.model) || !(row.error === null || typeof row.error === 'string' && Object.hasOwn(controlErrors, row.error))) {
            throw new ControlError('invalid_response');
          }
          checks.push({ id: row.id, timestamp: row.timestamp, success: row.success, duration_ms: row.duration_ms,
            error: row.error as string | null, request_type: row.request_type, model: row.model });
        }
      }

  return { configured: model.configured, verified: model.verified, source: String(model.source ?? ''),
    model: model.model, endpoint: model.endpoint, storage: String(model.storage ?? ''), checks,
    ...(text(model.storage_state)?{storage_state:model.storage_state}:{}),
    storage_error:text(model.storage_error)&&Object.hasOwn(controlErrors,model.storage_error)?model.storage_error:null,
    ...(text(model.id) ? { id: model.id } : {}), ...(text(model.name) ? { name: model.name } : {}),
    ...(text(model.provider) ? { provider: model.provider } : {}), ...(text(model.revision) ? { revision: model.revision } : {}) };
}

export function createControlClient(fetcher: typeof fetch = (...args) => fetch(...args)) {
  let csrf = '';
  async function call(path: string, method = 'GET', body?: ObjectValue, signal?: AbortSignal): Promise<unknown> {
    let response: Response;
    try {
      response = await fetcher('/api/v1/researchloop/control' + path, {
        method, signal, credentials: 'same-origin', cache: 'no-store', redirect: 'error', mode: 'same-origin',
        ...(method !== 'GET' ? { headers: { 'Content-Type': 'application/json', 'X-ReOps-UI-Token': csrf }, body: JSON.stringify(body ?? {}) } : {}),
      });
    } catch { throw new ControlError('unavailable'); }
    let value: unknown;
    try { value = await response.json(); } catch { throw new ControlError('invalid_response'); }
    if (!response.ok) throw new ControlError(obj(value) && typeof value.detail === 'string'
      && Object.hasOwn(controlErrors, value.detail) ? value.detail : 'web_control_rejected');
    return value;
  }
  return {
    async status(signal?: AbortSignal): Promise<ControlStatus> {
      const value = await call('/status', 'GET', undefined, signal);
      if (!obj(value) || !text(value.csrf) || typeof value.enabled !== 'boolean' || typeof value.busy !== 'boolean'
          || !obj(value.model) || typeof value.model.configured !== 'boolean' || typeof value.model.verified !== 'boolean'
          || !text(value.model.model) || !text(value.model.endpoint) || !validJob(value.job)) throw new ControlError('invalid_response');
      csrf = value.csrf;
      // 不将csrf带入React渲染状态、错误信息或原始证据展示。
      const model = parseModel(value.model);
      if (value.model.services !== undefined) {
        if (!Array.isArray(value.model.services) || value.model.services.length > 16) throw new ControlError('invalid_response');
        model.services = value.model.services.map((item: unknown) => {
          if (!obj(item) || !text(item.id) || !text(item.name) || !text(item.provider) || !text(item.revision) || typeof item.active !== 'boolean') throw new ControlError('invalid_response');
          return { ...parseModel(item), id: item.id, name: item.name, provider: item.provider, revision: item.revision, active: item.active };
        });
      }
      return { enabled: value.enabled, busy: value.busy, model, job: value.job as WebJob | null };
    },
    saveService: (fields: ServiceFields, id?: string, revision?:string) => call(id ? `/services/${encodeURIComponent(id)}` : '/services', id ? 'PUT' : 'POST', { ...fields,...(id?{as_candidate:true}:{}),...(id&&revision?{expected_revision:revision}:{}) }),
    verifyService: (id: string) => call(`/services/${encodeURIComponent(id)}/verify`, 'POST'),
    selectService: (id: string) => call(`/services/${encodeURIComponent(id)}/select`, 'POST'),
    setKey: (apiKey: string) => call('/model', 'PUT', { api_key: apiKey }),
    verify: () => call('/model/verify', 'POST'),
    start: (strategy: 'model' | 'experience') => call('/jobs', 'POST', { strategy }),
    startRun: (strategy: 'model' | 'experience') => call('/runs', 'POST', { strategy }),
    approveRun: (job: WebJob, confirmation: PendingConfirmation) =>
      call(`/runs/${encodeURIComponent(job.id)}/approve`, 'POST', { confirmation_id: confirmation.id, approved: true }),
    confirm: (job: WebJob, confirmation: PendingConfirmation, answer: string) =>
      call(`/jobs/${encodeURIComponent(job.id)}/confirmation`, 'POST', { confirmation_id: confirmation.id, answer }),
    cancel: (job: WebJob) => call(`/jobs/${encodeURIComponent(job.id)}/cancel`, 'POST'),
  };
}
