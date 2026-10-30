import { t } from '../i18n';
import type { TraceStep } from '../types/agent';

export interface RecoveryEvidenceItem {
  kind: 'failure' | 'action' | 'verification';
  title: string;
  content: string;
  detail: string | null;
}
function field(step: TraceStep | undefined, key: 'input' | 'tool' | 'result'): string | null {
  const value = step?.event.data[key];
  return typeof value === 'string' && value.trim() ? value : null;
}

/** Only already-reached local events. Display labels describe records; they never supply evidence. */
export function recoveryEvidence(steps: readonly TraceStep[], index: number): RecoveryEvidenceItem[] {
  if (index < 0) return [];
  const reached = steps.slice(0, index + 1);
  const items: RecoveryEvidenceItem[] = [];
  const fault = reached.findLast(step => step.event.stage === 'localization')
    ?? reached.findLast(step => step.event.stage === 'failure_detection')
    ?? reached.find(step => step.event.stage === 'observe');
  const faultContent = fault?.event.stage === 'observe' ? field(fault, 'input') : field(fault, 'result');
  if (fault) items.push({ kind: 'failure', title: t("故障依据"), content: faultContent ?? t("此事件未提供故障依据。"),
    detail: field(fault, fault.event.stage === 'observe' ? 'result' : 'input') });

  const action = reached.findLast(step => step.event.stage === 'recovery_execution');
  if (action) {
    const statuses = { started: t("执行中"), success: t("成功"), failed: t("失败"), skipped: t("已跳过"), waiting_human: t("等待确认") };
    items.push({ kind: 'action', title: t("恢复动作"), content: field(action, 'tool') ?? t("此执行事件未提供动作内容。"),
      detail: field(action, 'result') ?? t('执行事件状态：{0}', statuses[action.event.status]) });
  }
  const verification = reached.findLast(step => step.event.stage === 'verification');
  if (verification) {
    const final = reached.findLast(step => step.phase === 'recovered');
    const confirmed = verification.event.status === 'success' && final?.event.status === 'success'
      && final.event.incident_id === verification.event.incident_id && final.event.trace_id === verification.event.trace_id;
    const content = verification.event.status === 'failed'
      ? [t("验证失败"), field(verification, 'result')].filter(Boolean).join(' · ')
      : confirmed ? field(verification, 'result') ?? t("验证记录未提供具体结果。")
        : t("尚未确认通过");
    items.push({ kind: 'verification', title: t("业务验证"), content, detail: field(verification, 'tool') });
  }
  return items;
}
