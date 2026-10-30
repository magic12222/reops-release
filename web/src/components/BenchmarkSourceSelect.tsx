import { t, useLocale } from '../i18n';
import { benchmarkSources, sourceNames, type BenchmarkSource } from '../data/benchmarkReports';

const descriptions: Record<BenchmarkSource, string> = {
  real: '真实运行来源。导入声明与独立核验分别展示。',
  offline_fixture: '固定响应与人工场景，不代表真实模型效果。',
  simulation: '模拟记录，独立于上方的静态视觉样例。',
};

export function BenchmarkSourceSelect({ source, onChange, kind }: {
  source: BenchmarkSource; onChange: (source: BenchmarkSource) => void; kind: 'reports' | 'evidence';
}) {
  useLocale();
  return <aside className="studio-data-source"><label>{t("数据来源")}<select aria-label={kind === 'reports' ? t('评测数据来源') : t('证据数据来源')} value={source}
      onChange={event => onChange(event.target.value as BenchmarkSource)}>
      {benchmarkSources.map(item => <option key={item} value={item}>{sourceNames[item]}</option>)}
    </select>
  </label><details className="studio-source-note"><summary>{t("来源说明")}</summary>
    <p>{t(descriptions[source])}{t("本区域独立读取，不进入上方图表。")}</p></details></aside>;
}
