import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { EvaluationEvidence, EvidenceCard, type Evidence } from './EvaluationEvidence';

describe('C6 evidence boundary', () => {
  it('shows source choices and no invented evaluation result', () => {
    const html = renderToStaticMarkup(<EvaluationEvidence />);
    expect(html).toContain('REAL');
    expect(html).toContain('OFFLINE FIXTURE');
    expect(html).toContain('SIMULATION');
    expect(html).toContain('读取证据中');
    expect(html).toContain('不进入上方图表');
  });
  it('keeps missing values and reported success separate from independent Verify', () => {
    const item: Evidence = { run_id: 'run', source: 'offline_fixture', incident_id: 'incident', trace_id: 'trace',
      case_id: null, experiment_id: null, scenario: null, strategy: null, action: null, target: null,
      event_count: 2, execution_outcome_reported: 'unknown', verification_status_reported: 'recovered',
      verify_samples: [{ event_id: 'event', observation_id: null, timestamp: null }],
      provenance: { normalized_evidence_sha256: 'abc', authenticated: false },
      conflicts: ['reported_recovery_conflict'], gaps: ['original_report_unavailable'] };
    const html = renderToStaticMarkup(<EvidenceCard item={item} />);
    expect(html).toContain('独立双 Verify: 未核实');
    expect(html).toContain('reported_recovery_conflict');
    expect(html).toContain('缺 ID');
    expect(html).toContain('未认证');
    expect(html).not.toContain('100%');
  });
});
