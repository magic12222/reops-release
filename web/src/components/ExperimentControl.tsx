import { t, useLocale } from '../i18n';
import { useEffect, useState } from 'react';
import { readExperimentControl, requestExperiment } from '../data/experiments';
import type { Capabilities, Experiment } from '../data/experiments';

const labels: Record<string, string> = {
  waiting_operator: '等待服务端操作员', waiting_authorization: '等待 B 原终端授权或运行中',
  finished: '已结束', passed: '验收通过', failed: '未通过',
  rejected: '已拒绝', expired: '授权已过期', inconclusive: '结果不确定', unknown: '结果未知',
  not_requested: '尚未请求', pending: '待开始', consumed: '授权已使用', not_consumed: '授权未使用',
  not_attempted: '尚未尝试', attempted: '已尝试', confirmed: '已确认',
  attempted_unconfirmed: '已尝试 · 尚未确认', not_run: '未运行', succeeded: '成功',
  recovered: '已验证恢复', not_recovered: '未恢复',
};
const statusLabel = (value: string) => t(Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : value);

export function ExperimentControl({ visible = true }: { visible?: boolean }) {
  useLocale();
  const [state, setState] = useState<{ capabilities: Capabilities; items: Experiment[] } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!visible) return;
    let active = true;
    const controller = new AbortController();
    const refresh = () => readExperimentControl(controller.signal).then(value => {
      if (active) { setState(value); setError(''); }
    }).catch(() => { if (active) setError('实验记录不可达或格式无效。'); });
    void refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => { active = false; controller.abort(); window.clearInterval(timer); };
  }, [visible]);
  const queue = async () => {
    setBusy(true);
    try {
      await requestExperiment();
      setState(await readExperimentControl());
      setError('');
    } catch { setError('请求未登记。请检查服务端开关与同源代理。'); }
    finally { setBusy(false); }
  };
  return <section className="live-panel experiment-control" aria-label={t("实验控制")}>
    <h3>{t("实验控制 ")}<small>{t("C4 · B Phase 8 授权入口")}</small></h3>
    <p>{t("已核实场景：停止 reops-lab API，依赖保持健康；B 决策后仅允许 start_service(web)。提交只登记请求。B 负责人确认接手后，须在服务端终端逐项完成 B 原授权挑战。结果将分列注入、恢复、Verify 与 cleanup。")}</p>
    <button className="button" disabled={!state?.capabilities.request_enabled || state?.capabilities.request_blocked || busy} onClick={queue}>{t("请求一次受控实验")}</button>
    <p role="status">{state?.capabilities.request_blocked ? t('实验已被人工核查锁定；需核对 B 审计并独立复核环境后，由服务端操作员解除。') : state?.capabilities.request_enabled ? t('请求入口已开启；请求本身不注入故障。') : t('请求入口关闭；历史记录仍可查看。')}</p>
    {error && <p role="alert">{t(error)}</p>}
    <h4>{t("实验记录与最终结果")}</h4>
    {state?.items.length === 0 && <p>{t("暂无实验记录。")}</p>}
    {state?.items.map(item => <article className="experiment-record" key={item.id}>
      <h4>{item.id} · {statusLabel(item.state)}</h4>
      {item.state === 'waiting_operator' && <p>{t("请将此请求 ID 交给 B 负责人；请求本身尚未注入故障。")}</p>}
      <dl>
        <div><dt>{t("来源 / Ground truth")}</dt><dd>{t("REAL 请求 · ")}{item.ground_truth.injection} → {item.ground_truth.root_cause}</dd></div>
        <div><dt>{t("关联")}</dt><dd>{item.incident_id || t('待创建')} / {item.trace_id || t('待创建')}</dd></div>
        <div><dt>{t("授权")}</dt><dd>{statusLabel(item.authorization)}</dd></div>
        <div><dt>{t("故障注入")}</dt><dd>{statusLabel(item.injection)}</dd></div>
        <div><dt>{t("B 恢复")}</dt><dd>{statusLabel(item.recovery)}</dd></div>
        <div><dt>{t("Verify")}</dt><dd>{statusLabel(item.verify)}</dd></div>
        <div><dt>{t("Cleanup")}</dt><dd>{statusLabel(item.cleanup)}</dd></div>
        <div><dt>{t("最终结果")}</dt><dd>{statusLabel(item.result)}</dd></div>
        {item.review_required && <div><dt>{t("人工核查")}</dt><dd>{t("阻断新实验；核对 B 审计及独立环境状态")}</dd></div>}
        {item.manual_review && <div><dt>{t("人工核查")}</dt><dd>{t("已登记 · ")}{item.manual_review.reviewer} · {item.manual_review.reviewed_at}</dd></div>}
        {item.error && <div><dt>{t("错误")}</dt><dd>{item.error}</dd></div>}
      </dl>
      <p>{t("Cleanup 只表示环境善后，不能证明 B 恢复成功。")}</p>
    </article>)}
  </section>;
}
