import { t, useLocale } from '../i18n';
import { useWorkspaceMode } from '../hooks/useWorkspaceMode';
import { BenchmarkEvaluation } from './BenchmarkEvaluation';
import { EvaluationEvidence } from './EvaluationEvidence';

const hashes = { reports: '#evaluation', evidence: '#evidence' };

export function EvaluationWorkspace() {
  useLocale();
  const [mode, selectMode] = useWorkspaceMode<keyof typeof hashes>(hashes, 'reports');
  return <section id="evaluation" className="evaluation-workspace" aria-label={t("评测工作区")}>
    <span id="evidence" className="workspace-anchor" aria-hidden="true" />
    <header className="studio-evaluation-heading"><div><h2>{t("报告与证据")}</h2></div>
      <div role="group" aria-label={t("评测工作区视图")}>
        <button type="button" aria-pressed={mode === 'reports'} onClick={() => selectMode('reports')}>{t("评测报告")}</button>
        <button type="button" aria-pressed={mode === 'evidence'} onClick={() => selectMode('evidence')}>{t("证据核对")}</button>
      </div>
    </header>
    {mode === 'reports' ? <BenchmarkEvaluation /> : <EvaluationEvidence />}
  </section>;
}
