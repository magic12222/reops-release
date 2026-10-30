import type { RecoverySnapshot, RecoverySource } from '../types/agent';
import { demoMeta, demoSteps } from './demoData';

export function snapshotAt(elapsed: number): RecoverySnapshot {
  const clamped = Math.min(Math.max(0, elapsed), demoMeta.duration);
  const index = demoSteps.findLastIndex(step => step.at <= clamped);
  return { mode: 'simulation', elapsed: clamped, index, phase: demoSteps[index].phase,
    complete: clamped === demoMeta.duration, incidentId: demoMeta.incidentId, traceId: demoMeta.traceId };
}

/** Simulation-only timer. The C API read source lives in api.ts and never synthesizes snapshots. */
export function createDemoSource(offset = 0): RecoverySource {
  return { mode: 'simulation', subscribe(onSnapshot, onError) {
    const start = performance.now();
    const interval = window.setInterval(() => {
      try {
        const snapshot = snapshotAt(offset + performance.now() - start);
        onSnapshot(snapshot);
        if (snapshot.complete) window.clearInterval(interval);
      } catch (error) { window.clearInterval(interval); onError(error instanceof Error ? error : new Error(String(error))); }
    }, 80);
    return () => window.clearInterval(interval);
  } };
}
