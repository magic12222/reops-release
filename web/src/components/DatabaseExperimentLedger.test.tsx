import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { DatabaseExperimentLedger, DatabaseExperimentRecord } from './DatabaseExperimentLedger';
import type { DatabaseExperiment } from '../data/databaseExperiments';

const item: DatabaseExperiment = { id: 'fixture', scenario: 'researchloop_stopped_postgres', source: 'real',
  incident_id: 'incident', trace_id: 'trace', state: 'finished', result: 'passed', review_required: false,
  created_at: '2026-10-26T14:00:00Z' };

describe('database ledger display boundaries', () => {
  it('does not render a browser experiment action', () => {
    const html = renderToStaticMarkup(<DatabaseExperimentLedger />);
    expect(html).toContain('API 与 PostgreSQL');
    expect(html).toContain('记录区只读');
    expect(html).not.toContain('<button');
  });
  it('keeps missing measurements unknown', () => {
    const html = renderToStaticMarkup(<DatabaseExperimentRecord item={{ ...item, report: { model_calls: 1 } }} />);
    expect(html).toContain('暂无完整实测');
    expect(html).not.toContain('未调用模型');
  });
  it('labels verified zero usage separately from server usage and generated research', () => {
    const html = renderToStaticMarkup(<DatabaseExperimentRecord item={{ ...item, report: {
      model_calls: 0, diagnosis_source: 'memory/rule-supported',
      repair_usage: { input_tokens: 0, output_tokens: 0, source: 'no_model_calls' },
      measurements: { provider_attempts: 0, requests: [] }, generation_measurements: { enabled: false },
    } }} />);
    expect(html).toContain('未调用模型');
    expect(html).toContain('本实验未启用，与修复消耗分开统计');
    expect(html).not.toContain('当次服务端原始 usage');
  });
  it('accepts successful reports with no error field and preserves an actual readback error', () => {
    const report = { memory_written: true };
    expect(renderToStaticMarkup(<DatabaseExperimentRecord item={{ ...item, report }} />)).toContain('已写入并严格读回');
    expect(renderToStaticMarkup(<DatabaseExperimentRecord item={{ ...item, report: {
      ...report, error: 'database_memory_readback_failed',
    } }} />)).toContain('完整核验未确认');
  });
});
