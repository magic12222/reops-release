import { describe, expect, it } from 'vitest';
import { linkedRun } from './traceLink';
import { agentFixtures } from './agentFixtures';

describe('exact trace navigation', () => {
  it('never substitutes an unrelated or sample run for the requested real trace', () => {
    const run = agentFixtures[0].run;
    const page = { items: [run], total: 1, limit: 50, offset: 0 };
    expect(linkedRun(page, run.trace_id)).toBeNull();
    page.items = [{ ...run, source: 'real' }];
    expect(linkedRun(page, run.trace_id)).toBe(run.id);
    expect(linkedRun(page, 'other-trace')).toBeNull();
  });
});
