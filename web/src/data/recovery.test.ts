import { describe, expect, it } from 'vitest';
import { demoMeta, demoSteps } from './demoData';
import { snapshotAt } from './source';
import { eventToTrace } from './adapter';

describe('simulation lifecycle', () => {
  it('keeps the database failed until execution and withholds recovery until verification completes', () => {
    expect(snapshotAt(-50)).toMatchObject({ elapsed: 0, phase: 'failed', complete: false });
    expect(snapshotAt(4999)).toMatchObject({ phase: 'decide', complete: false });
    expect(snapshotAt(5000)).toMatchObject({ phase: 'execute', complete: false });
    expect(snapshotAt(7000)).toMatchObject({ phase: 'verify', complete: false });
    expect(snapshotAt(8399).complete).toBe(false);
    expect(snapshotAt(8400)).toMatchObject({ phase: 'recovered', complete: true });
    expect(snapshotAt(999999).elapsed).toBe(demoMeta.duration);
  });
  it('preserves shared event correlation and never labels failed verification as recovered', () => {
    demoSteps.forEach((step, i) => {
      expect(step.event.incident_id).toBe(demoMeta.incidentId);
      expect(step.event.trace_id).toBe(demoMeta.traceId);
      expect(step.event.parent_event_id).toBe(i ? demoSteps[i - 1].event.event_id : null);
    });
    const verification = { ...demoSteps[6].event, status: 'failed' as const };
    expect(eventToTrace(verification, demoSteps[0].event.timestamp).phase).toBe('verify');
    expect(eventToTrace(verification, demoSteps[0].event.timestamp).event.status).toBe('failed');
  });
});
