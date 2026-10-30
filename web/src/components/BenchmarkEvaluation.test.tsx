import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { BenchmarkEvaluation } from './BenchmarkEvaluation';

describe('C5 evaluation initial state', () => {
  it('starts with a source-scoped loading state and no illustrative result', () => {
    const html = renderToStaticMarkup(<BenchmarkEvaluation />);
    expect(html).toContain('OFFLINE FIXTURE');
    expect(html).toContain('REAL');
    expect(html).toContain('SIMULATION');
    expect(html).toContain('读取评测报告中');
    expect(html).not.toContain('60.0%');
  });
});
