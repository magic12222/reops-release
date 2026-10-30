import { t, useLocale } from '../i18n';
import { useEffect, useState } from 'react';
import { sourceNames, readBenchmarkJson, reportReadFailure } from '../data/benchmarkReports';
import { BenchmarkSourceSelect } from './BenchmarkSourceSelect';

type Source = 'real' | 'offline_fixture' | 'simulation';
export type Evidence = {
  run_id: string; source: Source; incident_id: string; trace_id: string; case_id: string | null;
  experiment_id: string | null; scenario: string | null; strategy: string | null;
  action: string | null; target: string | null; event_count: number;
  execution_outcome_reported: string | null; verification_status_reported: string | null;
  verify_samples: { event_id: string; observation_id: string | null; timestamp: string | null }[];
  gaps: string[]; conflicts: string[];
  provenance: { normalized_evidence_sha256: string; authenticated: false };
};
type Page = { source: Source; items: Evidence[]; total: number; offset: number; limit: number;
  evaluation_sample_count: number; recovery_success_rate: null };

export function EvidenceCard({ item }: { item: Evidence }) {
  useLocale();
  return <details className="benchmark-evaluation-group">
    <summary><strong>{item.scenario ?? t('运行轨迹')}</strong><span>{sourceNames[item.source]} · {item.trace_id}</span>
      <span>{item.conflicts.length ? t('证据冲突') : item.gaps.length ? t('存在缺口') : t('已导入 · 未认证')}</span></summary>
    <p>{t("场景: ")}{item.scenario ?? t('未提供')} {t(" · 策略标签: ")}{item.strategy ?? t('未提供')} {t(" · 动作: ")}{item.action ?? t('未提供')} / {item.target ?? t('未提供')}</p>
    <p>{t("事件 ")}{item.event_count} {t(" · 执行报告: ")}{item.execution_outcome_reported ?? t('未知')} {t(" · Verify 报告: ")}{item.verification_status_reported ?? t('未知')}</p>
    <p>{t("独立双 Verify: 未核实 · 真实模型调用 / Token / 费用 / 恢复时延: 未提供")}</p>
    <details><summary>{t("关联与来源原件")}</summary><p>{t("Incident: ")}{item.incident_id} {t(" · Case: ")}{item.case_id ?? t('未提供')} {t(" · 实验: ")}{item.experiment_id ?? t('未关联')}</p>
      <p>{t("来源为导入声明，未认证。规范化证据 SHA256: ")}<code>{item.provenance.normalized_evidence_sha256}</code></p></details>
    {item.conflicts.length > 0 && <p role="alert">{t("证据冲突：")}{item.conflicts.join(' · ')}</p>}
    <details><summary>{t('Verify 样本引用（{0}，不代表健康或独立性）', item.verify_samples.length)}</summary>
      {item.verify_samples.map((sample, index) => <p key={`${sample.event_id}:${index}`}>{sample.observation_id ?? t('缺 ID')} · {sample.timestamp ?? t('缺时间')} · {sample.event_id}</p>)}
    </details>
    <details><summary>{t('缺口（{0}）', item.gaps.length)}</summary><p>{item.gaps.join(' · ')}</p></details>
  </details>;
}

export function EvaluationEvidence() {
  useLocale();
  const [source, setSource] = useState<Source>('real');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<{ cause: unknown } | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setPage(null); setError(null);
    readBenchmarkJson(`/api/v1/evaluation-evidence?source=${source}&offset=${offset}&limit=20`, controller.signal)
      .then(response => {
        const value = response as Page;
        if (!value || value.source !== source || value.offset !== offset || !Array.isArray(value.items)
          || !Number.isInteger(value.total) || value.total < 0 || value.evaluation_sample_count !== 0
          || value.recovery_success_rate !== null || !value.items.every(item => item.source === source
            && typeof item.run_id === 'string' && Array.isArray(item.verify_samples)
            && Array.isArray(item.gaps) && Array.isArray(item.conflicts)
            && item.provenance?.authenticated === false)) throw new Error('invalid_response');
        if (active) setPage(value);
      }).catch(error => { if (active) setError({ cause: error }); });
    return () => { active = false; controller.abort(); };
  }, [source, offset, retry]);
  const visible = page?.source === source && page.offset === offset ? page : null;
  return <div className="benchmark-evaluation" aria-label={t("运行证据核对")}>
    <div className="studio-evaluation-content">
    {error ? <div className="studio-status"><div role="alert"><strong>{sourceNames[source]}{t("：证据读取失败")}</strong>
      <p>{reportReadFailure(error.cause)}</p></div><button type="button" onClick={() => setRetry(value => value + 1)}>{t("重试读取")}</button></div> : !visible ? <div className="studio-status" role="status"><strong>{t("读取证据中…")}</strong></div> : <>
      {visible.total === 0 ? <div className="studio-status" role="status"><div><strong>{sourceNames[source]}{t("：无已导入证据")}</strong><p>{t("轨迹数不等于评测样本数；恢复率未提供，不进入上方图表。")}</p></div></div>
        : <p role="status">{sourceNames[source]} {t(" · 轨迹 ")}{t(visible.total)} {t(" · 评测样本 0 · 恢复率：未提供")}</p>}
      {visible.items.map(item => <EvidenceCard key={item.run_id} item={item} />)}
      {visible.total > 0 && <div className="studio-pagination"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>{t("上一页")}</button>
      <button disabled={offset + 20 >= visible.total} onClick={() => setOffset(offset + 20)}>{t("下一页")}</button></div>}
    </>}
    </div><BenchmarkSourceSelect kind="evidence" source={source} onChange={next => {
      if (next !== source) { setSource(next); setOffset(0); setPage(null); setError(null); }
    }} />
  </div>;
}
