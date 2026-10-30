import type { EventRecord } from '../types/dashboard';
import { t } from '../i18n';
import { evidenceFactText, evidencePresentation, stageFact } from './evidencePresentation';
import { evidenceFields, traceName } from './traceExplorer';

export interface ChamberSignal { key: string; label: string; text: string; value: unknown; display: string }
const stageNames: Record<EventRecord['stage'], string> = {
  observe: '观测', failure_detection: '故障检测', localization: '故障定位', root_cause_analysis: '根因分析',
  recovery_decision: '恢复决策', recovery_execution: '执行恢复', verification: '业务验证', experience_update: '经验更新',
};
export function chamberStageName(event: EventRecord) {
  return t(event.origin === 'decision_trace' ? traceName(event) : stageNames[event.stage]);
}
/** Exact substitutions only; unfamiliar or negated evidence keeps its recorded wording. */
function signalDisplay(text: string) {
  const http = text.match(/^(?:GET|POST|PUT|PATCH|DELETE|HEAD)\s+\S+\s+(?:returned\s+|:\s*)(HTTP [1-5]\d{2})[.!]?$/i);
  if (http) return http[1];
  if (/^(?:API log contains )?connection refused:\s*\S+$/i.test(text)) return t('连接被拒绝');
  const health = text.match(/^\S+ service health is (healthy|unhealthy)$/i);
  return health ? t(health[1]) : text;
}
export function chamberPresentation(event: EventRecord) {
  const preview = evidencePresentation(event), recorded = stageFact(event);
  const fields = Object.fromEntries(evidenceFields(event));
  let primary = recorded?.text ?? chamberStageName(event);
  let secondary = recorded ? chamberStageName(event) : preview.summary;
  const diagnoses: Record<string, [string, string]> = {
    postgres_service_down: ['PostgreSQL', '服务不可用'], api_service_down: ['API', '服务不可用'], web_service_down: ['Web', '服务不可用'],
  };
  if (event.stage === 'root_cause_analysis' && typeof fields.root_cause === 'string'
    && Object.prototype.hasOwnProperty.call(diagnoses, fields.root_cause)) {
    const diagnosis = diagnoses[fields.root_cause];
    [primary, secondary] = [diagnosis[0], t(diagnosis[1])];
  }
  const signals: ChamberSignal[] = [];
  const add = (key: string, label: string, value: unknown, text: string) => {
    if (signals.length < 3 && text.trim() && !signals.some(signal => signal.key === key
      || (typeof value === 'string' && signal.text === text)))
      signals.push({ key, label, value, text, display: signalDisplay(text) });
  };
  for (const fact of preview.facts) {
    if (Array.isArray(fact.value) && fact.value.every(value => typeof value === 'string')) {
      fact.value.forEach((value, index) => add(`${fact.key}.${index}`, fact.label, value, value));
    } else add(fact.key, fact.label, fact.value, evidenceFactText(fact));
  }
  return { primary, secondary, signals };
}
