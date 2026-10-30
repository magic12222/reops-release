import type { EventRecord } from '../types/dashboard';
import { evidenceFields, evidencePreview, stageSummary, traceName } from './traceExplorer';
import { agentDuration, agentNumber, agentSentence, agentValueName } from './agentDisplay';
import { t } from '../i18n';

export interface EvidenceFact { key: string; label: string; value: unknown }
const priorities: Record<EventRecord['stage'], string[]> = {
  observe: ['request.status_code', 'request.latency_ms', 'request.endpoint', 'services', 'metrics'],
  failure_detection: ['evidence', 'failed_component', 'confidence'],
  localization: ['failed_component', 'failed_step', 'evidence', 'confidence'],
  root_cause_analysis: ['evidence', 'failed_component', 'confidence', 'root_cause', 'failed_step'],
  recovery_decision: ['action', 'target', 'requires_approval', 'allowed', 'safety_allowed', 'risk'],
  recovery_execution: ['execution_status', 'executor_called', 'target', 'exit_code', 'duration_ms', 'action'],
  verification: ['evidence', 'health_check_passed', 'business_request_passed', 'fault_cleared', 'status', 'verification_status'],
  experience_update: ['final_status', 'success', 'memory_updated', 'evidence'],
};
const labels: Record<string, string> = {
  'request.status_code': 'HTTP 响应', 'request.latency_ms': '请求耗时', 'request.endpoint': '请求路径',
  services: '服务观测', metrics: '指标', failure_detected: '检测到故障', failed_component: '影响组件',
  failed_step: '故障位置', root_cause: '记录根因', evidence: '诊断依据', confidence: '置信度',
  action: '动作', target: '目标', requires_approval: '需要审批', allowed: '允许执行', safety_allowed: '安全检查',
  risk: '风险', execution_status: '执行结果', executor_called: '执行器调用', exit_code: '退出码',
  duration_ms: '执行耗时', status: '记录结果', verification_status: '验证结果', failure_type: '异常类型',
  health_check_passed: '健康检查', business_request_passed: '业务验证', fault_cleared: '故障清除',
  final_status: '最终状态', success: '成功确认', memory_updated: '经验更新',
};
const secondary = (key: string) => /(^|\.)(schema_version|timestamp|source|origin|ordinal|stdout|stderr|logs|summary|reason|message)$/.test(key)
  || key.endsWith('_id');
const present = (value: unknown) => value !== null && value !== undefined && value !== ''
  && !(Array.isArray(value) && value.length === 0)
  && !(typeof value === 'object' && value !== null && Object.keys(value).length === 0);

function fieldValue(fields: Record<string, unknown>, key: string): unknown {
  return key.split('.').reduce<unknown>((object, part) => typeof object === 'object' && object !== null
    && Object.prototype.hasOwnProperty.call(object, part) ? (object as Record<string, unknown>)[part] : undefined, fields);
}

function readableText(value: unknown) {
  if (typeof value !== 'string') return undefined;
  const text = value.trim().replace(/\s+/g, ' ');
  return text && text.length <= 160 && !/^[{[]/.test(text) ? text : undefined;
}

/** A single recorded fact for the stage; missing evidence leaves the surface quiet. */
export function stageFact(event: EventRecord): { text: string; keys: string[]; excerpts?: string[] } | undefined {
  const fields = Object.fromEntries(evidenceFields(event));
  const text = (key: string) => {
    return readableText(fieldValue(fields, key));
  };
  if (event.stage === 'recovery_execution' || event.stage === 'recovery_decision') {
    const action = text('action'), target = text('target');
    if (action && target) return { text: `${action} → ${target}`, keys: ['action', 'target'] };
  }
  if (event.stage === 'observe') {
    const endpoint = text('request.endpoint'), status = fieldValue(fields, 'request.status_code');
    if (endpoint && typeof status === 'number') return { text: `${endpoint} · HTTP ${status}`, keys: ['request.endpoint', 'request.status_code'] };
    if (endpoint) return { text: endpoint, keys: ['request.endpoint'] };
  }
  if (event.stage === 'failure_detection') {
    const evidence = fieldValue(fields, 'evidence');
    if (Array.isArray(evidence)) {
      const excerpts = evidence.filter((value): value is string => !!readableText(value)).slice(0, 2);
      if (excerpts.length) return {
        text: excerpts.map(value => value.trim()
          // Strip only literal reporting prefixes; preserve the signal and any negation.
          .replace(/^(?:GET|POST|PUT|PATCH|DELETE|HEAD)\s+\S+\s+(?:returned\s+|:\s*)(HTTP [1-5]\d{2})[.!]?$/i, '$1')
          .replace(/^API log contains\s+/i, '')).join(' · '), keys: [], excerpts,
      };
    }
  }
  const key = event.stage === 'failure_detection' ? 'failure_type' : event.stage === 'localization' ? 'failed_component'
    : event.stage === 'root_cause_analysis' ? 'root_cause'
    : event.stage === 'verification' ? (text('verification_status') ? 'verification_status' : 'status')
    : event.stage === 'experience_update' ? 'final_status' : undefined;
  if (key) { const value = text(key); if (value) return { text: agentValueName(key, value), keys: [key] }; }
  // Explicit recorded summaries are safe fallbacks; empty/null evidence never creates a sentence.
  for (const summaryKey of ['summary', 'reason', 'message']) {
    const value = text(summaryKey);
    if (value && value.toLowerCase() !== traceName(event).toLowerCase()
      && stageSummary({ ...event, data: {}, message: value })) return { text: agentSentence(value), keys: [summaryKey] };
  }
  return undefined;
}

/** Select existing evidence only. Stage/status never produce a diagnostic conclusion. */
export function evidencePresentation(event: EventRecord) {
  const fields = Object.fromEntries(evidenceFields(event));
  const recorded = ['summary', 'reason', 'message'].map(key => fields[key])
    .find(value => typeof value === 'string' && value.trim());
  const detection = event.stage === 'failure_detection' && typeof fields.failure_detected === 'boolean';
  const recordedSummary = typeof recorded === 'string' ? recorded
    : stageSummary({ ...event, data: {} }) || stageSummary(event);
  const stage = stageFact(event);
  // Remove only exact restatements backed by the corresponding recorded fields.
  // Additional failure context and unfamiliar sentences are never guessed away.
  const repeatsStage = recordedSummary === stage?.text || (!!stage && stage.keys.some(key => fieldValue(fields, key) === recordedSummary))
    || (stage?.keys.includes('root_cause') && recordedSummary === `Root cause identified as ${fields.root_cause}.`);
  const repeatsResult = event.stage === 'recovery_execution' && fields.execution_status === 'succeeded'
    && recordedSummary === 'Restricted executor completed the service restart.';
  const repeatsLocation = event.stage === 'localization' && fields.failed_component === 'postgres' && fields.failed_step === 'database_query'
    && recordedSummary === 'Failure localized to the PostgreSQL access step.';
  const repeatsVerification = event.stage === 'verification' && (fields.verification_status ?? fields.status) === 'recovered'
    && fields.health_check_passed === true && fields.business_request_passed === true
    && recordedSummary === 'Health check and business request confirm recovery.';
  // Translate the recorded boolean, never the event's generic success status.
  const failureType = readableText(fields.failure_type);
  const summary = detection ? `${t(fields.failure_detected ? '检测到故障' : '未检测到故障')}${failureType ? ` · ${agentValueName('failure_type', failureType)}` : ''}`
    : repeatsStage || repeatsResult || repeatsLocation || repeatsVerification ? '' : agentSentence(recordedSummary);
  const facts: EvidenceFact[] = [];
  const stageKeys = [...(stage?.keys ?? []), ...(detection ? ['failure_detected', 'failure_type'] : [])];
  const strings = new Set<string>(stageKeys.map(key => fieldValue(fields, key)).filter((value): value is string => typeof value === 'string'));
  function add(key: string) {
    if (facts.length === 3 || secondary(key) || stageKeys.some(stageKey => stageKey === key || stageKey.startsWith(`${key}.`))
      || facts.some(fact => fact.key === key || fact.key.startsWith(`${key}.`))) return;
    const original = fieldValue(fields, key);
    const excerpts = stage?.excerpts;
    const value = key === 'evidence' && Array.isArray(original) && excerpts
      ? original.filter(item => !excerpts.includes(item)) : original;
    if (!present(value)) return;
    // Deduplicate repeated text, not boolean outcomes of different checks.
    if (typeof value === 'string') {
      const index = summary.indexOf(value);
      const inSummary = value.length >= 4 && index >= 0
        && !/[\p{L}\p{N}_]/u.test(summary[index - 1] ?? '')
        && !/[\p{L}\p{N}_]/u.test(summary[index + value.length] ?? '');
      if (strings.has(value) || inSummary) return;
      strings.add(value);
    }
    const label = key === 'evidence' && event.stage === 'failure_detection' ? '检测依据'
      : key === 'evidence' && event.stage === 'verification' ? '验证记录'
      : Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] : key.replaceAll('_', ' ');
    facts.push({ key, label, value });
  }
  // A failed recorded check outranks supplementary evidence, even when other checks passed.
  if (event.stage === 'verification') priorities.verification
    .filter(key => ['health_check_passed', 'business_request_passed', 'fault_cleared'].includes(key)
      && fieldValue(fields, key) === false).forEach(add);
  priorities[event.stage].forEach(add);
  // Do not fill spare space with unrelated metadata. Unknown record shapes still have a preview.
  if (facts.length === 0) Object.keys(fields).forEach(add);
  return { summary, facts, status: event.status && event.status !== 'success' ? event.status : null };
}

/** Human-readable rendering only; the fact value and complete record remain untouched. */
export function evidenceFactText(fact: EvidenceFact) {
  if (typeof fact.value === 'boolean') {
    if (fact.key === 'health_check_passed' || fact.key === 'business_request_passed') return t(fact.value ? '通过' : '未通过');
    if (fact.key === 'fault_cleared') return t(fact.value ? '已清除' : '未清除');
    if (fact.key === 'failure_detected') return t(fact.value ? '已检测到' : '未检测到');
    return t(fact.value ? '是' : '否');
  }
  if (fact.key === 'services' && typeof fact.value === 'object' && fact.value !== null && !Array.isArray(fact.value)) {
    const display = Object.fromEntries(Object.entries(fact.value).map(([key, value]) => [key,
      typeof value === 'object' && value !== null && 'status' in value && typeof value.status === 'string'
        ? { ...value, status: agentValueName('service_status', value.status) } : value]));
    return compactEvidence(display);
  }
  if (typeof fact.value === 'number' && Number.isFinite(fact.value)) {
    if (fact.key === 'duration_ms' || fact.key === 'request.latency_ms') return agentDuration(fact.value);
    if ((fact.key === 'confidence' || fact.key === 'risk') && fact.value >= 0 && fact.value <= 1) return `${agentNumber(fact.value * 100)}%`;
    return agentNumber(fact.value);
  }
  if (typeof fact.value === 'string') return compactEvidence(agentValueName(fact.key, fact.value));
  return compactEvidence(fact.value);
}

export function compactEvidence(value: unknown) {
  const preview = Array.isArray(value) && value.every(item => typeof item === 'string')
    ? `${value.slice(0, 2).join('；')}${value.length > 2 ? ` ${t('· 共 {0} 条', value.length)}` : ''}`
    : typeof value === 'object' && value !== null && !Array.isArray(value)
      ? Object.entries(value).slice(0, 4).map(([key, item]) => `${key}: ${typeof item === 'object' && item !== null
        && 'status' in item ? String(item.status) : evidencePreview(item)}`).join(' · ')
      : evidencePreview(value);
  const text = preview.replace(/\s+/g, ' ');
  return text.length > 180 ? `${text.slice(0, 179)}…` : text;
}
