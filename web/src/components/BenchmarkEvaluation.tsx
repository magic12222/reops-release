import { t, useLocale } from '../i18n';
import { useEffect, useState } from 'react';
import { sourceNames as names, reportPage, reportDetail, readBenchmarkJson, reportReadFailure,
  type BenchmarkSource as Source, type BenchmarkReport as Report, type ReportSummary as Summary } from '../data/benchmarkReports';
import { BenchmarkSourceSelect } from './BenchmarkSourceSelect';
const metricNames: Record<string, string> = {
  detection_accuracy: 'Detection accuracy', fixture_rca_accuracy: 'Fixture RCA accuracy',
  plan_accuracy: 'Plan accuracy', safety_decision_accuracy: 'Safety decision accuracy',
  recovery_success_rate: 'Recovery success / executor called',
  verify_success_rate: 'Verify success / confirmed execution',
  fixture_recovery_rate: 'Fixture recovery / initial detected fault',
  expected_behavior_accuracy: 'Expected behavior / cases',
  strategy_selection_accuracy: 'Selected strategy / labeled cases',
  false_recovery_rate: 'False recovery / expected unverified',
  no_action_accuracy: 'No action / expected no action',
  unsafe_action_rejection_rate: 'Unsafe rejection / unsafe cases',
};

export function BenchmarkEvaluation() {
  useLocale();
  const [source, setSource] = useState<Source>('offline_fixture');
  const [reports, setReports] = useState<Summary[]>([]);
  const [selected, setSelected] = useState('');
  const [report, setReport] = useState<Report | null>(null);
  const [state, setState] = useState('读取评测报告中…');
  const [importError, setImportError] = useState(false);
  const [failure, setFailure] = useState<{ error: unknown; kind: 'list' | 'detail' } | null>(null);
  const [listRetry, setListRetry] = useState(0);
  const [detailRetry, setDetailRetry] = useState(0);
  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    setReports([]); setSelected(''); setReport(null); setImportError(false); setFailure(null); setState('读取评测报告中…');
    readBenchmarkJson(`/api/v1/benchmarks?source=${source}`, controller.signal).then(value => {
      if (!alive) return;
      const page = reportPage(value, source);
      setReports(page.items);
      setImportError(page.importError);
      if (page.items.length) setSelected(page.items[0].id);
      else setState(page.importError ? '最近一次导入失败（报告无效或无法读取）' :
        '无已导入报告');
    }).catch(error => { if (alive) { setState('报告列表读取失败'); setFailure({ error, kind: 'list' }); } });
    return () => { alive = false; controller.abort(); };
  }, [source, listRetry]);
  useEffect(() => {
    if (!selected || !reports.some(item => item.id === selected && item.source === source)) return;
    let alive = true;
    const controller = new AbortController();
    setReport(null); setFailure(null); setState('读取指标中…');
    readBenchmarkJson(`/api/v1/benchmarks/${encodeURIComponent(selected)}?source=${source}`, controller.signal).then(value => {
      if (!alive) return;
      const item = reportDetail(value, source, selected);
      setReport(item); setState('');
    }).catch(error => { if (alive) { setState('报告导入结果读取失败或格式无效'); setFailure({ error, kind: 'detail' }); } });
    return () => { alive = false; controller.abort(); };
  }, [selected, source, reports, detailRetry]);
  const visible = report?.source === source && report.id === selected ? report : null;
  return <div className="benchmark-evaluation" aria-label={t("C 评测结果")}>
    <div className="studio-evaluation-content">
    {reports.length > 0 && reports[0].source === source && <div className="studio-report-list" role="group" aria-label={t("报告列表")}>
      {reports.map(item => <button type="button" key={item.id} aria-pressed={selected === item.id} onClick={() => { if (selected !== item.id) { setSelected(item.id); setReport(null); setFailure(null); setState('读取指标中…'); } }}>
        <span><strong>{item.mode === 'offline-fixture-comparison' ? t('策略比较报告') : item.mode === 'offline-fixture' ? t('离线闭环报告') : t(item.mode)}</strong><small>{names[item.source]} · {item.id.slice(0, 16)}</small></span>
        <span>{item.sample_count} {t(" cases")}</span><span>{t("已导入")}</span>
      </button>)}
    </div>}
    {state && <div className="studio-status"><div role={failure ? 'alert' : 'status'}><strong>{names[source]} · {t(state)}</strong>
      {failure && <p>{reportReadFailure(failure.error)}</p>}</div>{failure && <button type="button" onClick={() => failure.kind === 'list' ? setListRetry(value => value + 1) : setDetailRetry(value => value + 1)}>{t("重试读取")}</button>}</div>}
    {importError && reports.length > 0 && <p role="alert">{t("最近一次导入失败；以下仍是此前成功导入的报告。")}</p>}
    {visible && <div className="studio-report-detail">
      <p>{t("评测范围：")}{[...new Set(visible.groups.map(group => group.suite))].join(' / ') || t('未提供')} {t(" · 各策略与 suite 单独统计。")}</p>
      <details><summary>{t("来源与报告指纹")}</summary><p>{t("报告 ID / SHA256：")}{visible.id}</p><pre>{JSON.stringify(visible.provenance, null, 2)}</pre></details>
      {visible.groups.length === 0 && <p>{t("此报告未提供分组指标。")}</p>}
      {visible.groups.map(group => <details className="benchmark-evaluation-group" key={`${visible.id}:${group.suite}:${group.strategy}`}>
        <summary><strong>{group.strategy}</strong><span>{group.suite} · {group.sample_count} {t(" cases")}</span><span>{t("查看指标与证据")}</span></summary>
        <div className="benchmark-evaluation-rates">{Object.entries(group.metrics).map(([key, metric]) =>
        <div key={key}><span>{t(metricNames[key] ?? key)}</span><strong>{metric.numerator}/{metric.denominator} · {metric.rate === null ? t('未提供') : t("{0}%", (metric.rate * 100).toFixed(1))}</strong>
            {metric.status !== 'available' && <small>{metric.status === 'empty_denominator' ? t('空分母') : t("缺失/未知 {0} 项", metric.missing)}</small>}</div>)}</div>
        <p>{t("未执行 ")}{group.outcomes.not_executed} {t(" · 拒绝 ")}{group.outcomes.rejected} {t(" · 结果未知 ")}{group.outcomes.result_unknown}</p>
        <details><summary>{t("场景与计量字段")}</summary><p>{t('场景 ID（{0}）：{1}', group.sample_count, group.case_ids.join(' · ') || t('未提供'))}</p>
          <p>{t("Fixture model calls: ")}{t(group.fixture_model_calls ?? '未提供')}{t("（替身计数） · Real model calls: ")}{t(group.real_model_calls ?? '未提供')} {t(" · Recovery latency: ")}{group.recovery_latency_ms == null ? t('未提供') : t("{0} ms", t(group.recovery_latency_ms))}</p>
          <p>{t("Token / 费用：未提供；不从调用量推算。")}</p></details>
      </details>)}</div>}
    </div><BenchmarkSourceSelect kind="reports" source={source} onChange={next => {
      if (next === source) return;
      setSource(next); setReports([]); setSelected(''); setReport(null); setImportError(false); setFailure(null); setState('读取评测报告中…');
    }} />
  </div>;
}
