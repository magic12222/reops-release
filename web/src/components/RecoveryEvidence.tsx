import { t, useLocale } from '../i18n';
import { demoSteps } from '../data/demoData';
import { recoveryEvidence } from '../data/recoveryEvidence';

const eventNames = ['观察故障', '检测异常', '定位依赖', '确认根因', '选择动作', '执行恢复', '验证业务', '完成回放'];

export function RecoveryEvidence({ selected, onSelect, index }: { selected: number; onSelect: (index: number) => void; index: number }) {
  useLocale();
  const items = recoveryEvidence(demoSteps, index);
  const trace = demoSteps[selected];
  return <details className="lab-evidence">
    <summary>{t("查看模拟恢复证据")}</summary>
    {items.length ? <dl className="lab-key-evidence">{items.map(item => <div key={item.kind} data-evidence-kind={item.kind}>
      <dt>{t(item.title)}</dt><dd>{item.content}{item.detail && <small>{item.detail}</small>}</dd>
    </div>)}</dl> : <p className="lab-evidence-empty">{t("演示尚未开始，没有已发生的恢复证据。")}</p>}
    <details className="lab-event-details" key={`details-${index}`}>
      <summary>{t("技术详情 · 模拟脚本")}</summary>
      <p className="lab-script-note">{t("完整预设脚本。只有回放至当前位置的事件用于上方恢复证据。")}</p>
      <div className="lab-evidence-body">
        <div className="lab-evidence-events" role="group" aria-label={t("模拟事件")}>{demoSteps.map((step, i) => <button key={step.event.event_id} aria-pressed={selected === i} onClick={() => onSelect(i)}>
          <span>{String(i + 1).padStart(2, '0')} {t(eventNames[i])}</span><small>{i > index ? t('预设') : t('已回放')}</small>
        </button>)}</div>
        <div key={trace.event.event_id}><span className="lab-evidence-preview">{selected > index ? t('预设模拟事件 · 尚未回放') : t('已回放的模拟事件')}</span><h3>{trace.event.message}</h3>
          <dl>{[['工具', trace.event.data.tool], ['输出', trace.event.data.result]].map(([label, value]) => <div key={String(label)}><dt>{t(String(label))}</dt><dd>{typeof value === 'string' ? value : t('未提供')}</dd></div>)}</dl>
          <details><summary>{t("原始模拟事件 JSON")}</summary><pre>{JSON.stringify(trace.event, null, 2)}</pre></details>
        </div>
      </div>
    </details>
  </details>;
}
