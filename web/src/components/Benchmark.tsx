import { t, useLocale } from '../i18n';
import { useState, useSyncExternalStore } from 'react';
import { motion } from 'motion/react';
import { benchmarkData } from '../data/demoData';
import { benchmarkMetrics, comparisonRows, metricValue, sampleDifference, type ComparisonOrder } from '../data/benchmarkStudio';
import { SectionLabel } from './Primitives';
import { EvaluationWorkspace } from './EvaluationWorkspace';
import './BenchmarkStudio.css';

// The installed Motion hook snapshots the preference only at mount. Subscribe locally
// so switching the system preference also stops Benchmark's active transitions.
const reducedMotionSnapshot = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const subscribeReducedMotion = (notify: () => void) => {
  const query = window.matchMedia('(prefers-reduced-motion: reduce)');
  query.addEventListener('change', notify);
  return () => query.removeEventListener('change', notify);
};

export function Benchmark() {
  useLocale();
  const [selected, setSelected] = useState('reops');
  const [metricKey, setMetricKey] = useState('successRate');
  const [order, setOrder] = useState<ComparisonOrder>('method');
  const reduced = useSyncExternalStore(subscribeReducedMotion, reducedMotionSnapshot, () => true);
  const metric = benchmarkMetrics.find(item => item.key === metricKey)!;
  const data = benchmarkData.find(item => item.id === selected)!;
  const value = metricValue(data, metric);
  const rows = comparisonRows(benchmarkData, metric, order);
  const references = benchmarkData.filter(item => item.id !== selected);
  const transition = { duration: reduced ? 0 : .52, ease: [.22, 1, .36, 1] as const };

  return <section id="benchmark" className="benchmark light benchmark-studio">
    <header className="studio-intro"><div className="studio-hero shell">
      <div><SectionLabel>{t("BENCHMARK")}</SectionLabel><h1>{t("Comparative ")}<span>{t("Studio.")}</span></h1><p className="studio-subtitle">{t("恢复方案，放在同一尺度上。")}</p></div>
      <div className="studio-provenance"><span>{t("SIMULATION ")}<i aria-hidden="true">/</i> {t(" DEMO")}</span><p>{t("静态视觉样例 · 非评测成绩")}</p></div>
    </div></header>
    <div className="section shell studio-content">
    <section className="studio" aria-label={t("模拟方案比较")}>
      <div className="studio-metric-switch" role="group" aria-label={t("比较指标")}>
        {benchmarkMetrics.map(item => <button type="button" key={item.key} aria-pressed={metric.key === item.key}
          onClick={() => setMetricKey(item.key)}><span aria-hidden="true">{item.index}</span>{t(item.shortLabel)}</button>)}
      </div>
      <header className="studio-metric-heading"><div><h2>{t(metric.label)}</h2><p>{t(metric.direction)}</p></div>
        <span>{t("SIMULATION · 非实测")}</span></header>
      <div className="studio-body">
        <div className="studio-insight">
          <div className={`studio-number${value === null ? ' studio-number-missing' : metric.format(value).length > 3 ? ' studio-number-compact' : ''}`} aria-live="polite" aria-atomic="true">
            <motion.strong key={`${selected}:${metric.key}`} initial={{ y: reduced ? 0 : 5 }}
              animate={{ y: 0 }} transition={{ duration: reduced ? 0 : .24 }}>{t(metric.format(value))}{value !== null && <small>{t(metric.unit)}</small>}</motion.strong>
            <span>{t(data.name)} {t(" · 当前方案")}</span>
          </div>
          <div className="studio-differences" aria-label={t("样例差值，当前方案减参照方案")}>
            {references.map(item => <div key={item.id}><strong>{t(sampleDifference(data, item, metric))}</strong>
              <span>{t("相较 ")}{t(item.name)}</span></div>)}
          </div>
        </div>
        <div className="studio-visual">
          <div className="studio-chart-heading"><p>{t("点击方案查看")}</p>
            <label>{t("排列 ")}<select aria-label={t("比较排列")} value={order} onChange={event => setOrder(event.target.value as ComparisonOrder)}>
              <option value="method">{t("方案顺序")}</option><option value="descending">{t("数值从高到低")}</option><option value="ascending">{t("数值从低到高")}</option>
            </select></label>
          </div>
          <div className="studio-chart" data-unit={metric.unit} aria-label={t("{0}，统一刻度 0 至 {1}{2}", t(metric.label), metric.max, t(metric.unit))}>
            <div className="studio-axis" aria-hidden="true">{Array.from({ length: 5 }, (_, index) => <span key={index} style={{ left: `${index * 25}%` }}>{t(metric.format(metric.max * index / 4))}</span>)}</div>
            <div className="studio-plot-reference" aria-hidden="true">
              {Array.from({ length: 5 }, (_, index) => <i key={index} style={{ left: `${index * 25}%` }} />)}
            </div>
            <div className="studio-rows">{rows.map((item, index) => {
              const itemValue = metricValue(item, metric);
              return <motion.button type="button" key={item.id} className="studio-row" data-method={item.id}
                data-value={itemValue ?? 'missing'} data-position={index} aria-pressed={selected === item.id}
                aria-label={t("{0}，{1}{2}，模拟数据", t(item.name), t(metric.format(itemValue)), itemValue === null ? '' : t(" {0}", t(metric.unit)))}
                initial={false} animate={{ y: index * 91 }} transition={transition} onClick={() => setSelected(item.id)}>
                <span className="studio-row-name">{t(item.name)}{selected === item.id && <small>{t("已选")}</small>}</span>
                <span className="studio-rail" aria-hidden="true">{itemValue !== null && <>
                  <span className="studio-measure" style={{ width: `${itemValue / metric.max * 100}%` }} />
                  <span className="studio-marker" style={{ left: `${itemValue / metric.max * 100}%` }}>
                    <svg viewBox="0 0 24 24"><path d="M12 3 21 12 12 21 3 12Z" /></svg>
                  </span></>}</span>
                <span className="studio-row-value">{t(metric.format(itemValue))}<small>{itemValue === null ? '' : t(metric.unit)}</small></span>
              </motion.button>;
            })}</div>
          </div>
          <div className="studio-chart-caption"><span>{t("零起点 · 同一尺度")}</span><span>{t("单位 / ")}{t(metric.unit)}</span></div>
        </div>
      </div>
      <footer className="studio-foot"><details><summary>{t("样例口径与限制")}</summary><p>{t(metric.caveat)}</p><p>{t("样本分母、场景范围与测量条件未提供；差值仅描述静态样例。")}</p></details>
      </footer>
    </section>
    <EvaluationWorkspace />
    </div>
  </section>;
}
