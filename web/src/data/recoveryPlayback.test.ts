import { afterEach, describe, expect, it, vi } from 'vitest';
import { initialRecoveryPlayback, recoveryPlaybackReducer as reduce, recoveryStageTarget } from './recoveryPlayback';
import { createDemoSource, snapshotAt } from './source';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
describe('Recovery stage replay', () => {
  it('steps one event at a time within the script, stops autoplay and rejects old ticks', () => {
    expect(reduce(initialRecoveryPlayback, { type: 'event', direction: 1 })).toBe(initialRecoveryPlayback);
    let state = reduce(initialRecoveryPlayback, { type: 'start' });
    const revision = state.revision;
    for (const index of [1, 2, 3, 4, 5, 6, 7, 7]) {
      state = reduce(state, { type: 'event', direction: 1 });
      expect(state.snapshot?.index).toBe(index);
      expect(state.running).toBe(false);
      expect(reduce(state, { type: 'tick', revision, snapshot: snapshotAt(8400) })).toBe(state);
    }
    for (const index of [6, 5, 4, 3, 2, 1, 0, 0]) {
      state = reduce(state, { type: 'event', direction: -1 });
      expect(state.snapshot?.index).toBe(index);
    }
  });
  it('visits pending verification separately from completion, and reverses each stop', () => {
    let state = initialRecoveryPlayback;
    for (const index of [0, 3, 5, 6, 7]) {
      state = reduce(state, { type: 'navigate', direction: 1 });
      expect(state.snapshot?.index).toBe(index);
      expect(state.running).toBe(false);
      expect(state.snapshot?.complete).toBe(index === 7);
    }
    for (const index of [6, 5, 3, 0, -1]) {
      state = reduce(state, { type: 'navigate', direction: -1 });
      expect(state.snapshot?.index ?? -1).toBe(index);
    }
    expect(recoveryStageTarget(1, 1)).toBe(3);
    expect(recoveryStageTarget(2, -1)).toBe(0);
    expect(recoveryStageTarget(4, 1)).toBe(5);
  });
  it('rejects delayed snapshots and failures after reset, rewind or replay', () => {
    const playing = reduce(initialRecoveryPlayback, { type: 'start' });
    for (const state of [reduce(playing, { type: 'reset' }), reduce(playing, { type: 'seek', index: 3 }), reduce(playing, { type: 'start' })]) {
      expect(reduce(state, { type: 'tick', revision: playing.revision, snapshot: snapshotAt(8400) })).toBe(state);
      expect(reduce(state, { type: 'failure', revision: playing.revision, error: 'late failure' })).toBe(state);
    }
  });
  it('resumes at the latest observed elapsed time and invalidates paused clock callbacks', () => {
    let state = reduce(initialRecoveryPlayback, { type: 'start' });
    const oldRevision = state.revision;
    state = reduce(state, { type: 'tick', revision: oldRevision, snapshot: snapshotAt(2100) });
    state = reduce(state, { type: 'pause' });
    state = reduce(state, { type: 'toggle' });
    expect(state).toMatchObject({ running: true, offset: 2100 });
    expect(reduce(state, { type: 'tick', revision: oldRevision, snapshot: snapshotAt(8400) })).toBe(state);
  });
  it('makes rapid toggles and moves use the latest state rather than a captured snapshot', () => {
    let state = reduce(initialRecoveryPlayback, { type: 'start' });
    for (let i = 0; i < 40; i++) state = reduce(state, { type: 'toggle' });
    expect(state.running).toBe(true);
    state = reduce(state, { type: 'navigate', direction: 1 });
    state = reduce(state, { type: 'navigate', direction: 1 });
    expect(state).toMatchObject({ running: false, snapshot: { index: 5, complete: false } });
  });
  it('preserves eight-event stepping and resets to baseline without starting replay', () => {
    let state = initialRecoveryPlayback;
    for (let index = 0; index < 8; index++) {
      state = reduce(state, { type: 'step' }); expect(state.snapshot?.index).toBe(index);
    }
    expect(state.snapshot?.complete).toBe(true);
    expect(reduce(state, { type: 'reset' })).toMatchObject({ snapshot: null, running: false, error: null });
    expect(reduce(state, { type: 'start' })).toMatchObject({ snapshot: { index: 0, complete: false }, running: true, offset: 0 });
  });
  it('cleans up the existing simulation timer on unsubscribe and on completion', () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] });
    vi.stubGlobal('window', { setInterval, clearInterval });
    const snapshots = vi.fn(); const failure = vi.fn();
    const stop = createDemoSource(0).subscribe(snapshots, failure);
    vi.advanceTimersByTime(800);
    expect(snapshots.mock.lastCall?.[0].index).toBe(1);
    stop(); expect(vi.getTimerCount()).toBe(0);
    const count = snapshots.mock.calls.length;
    vi.advanceTimersByTime(9000); expect(snapshots.mock.calls).toHaveLength(count);
    createDemoSource(7000).subscribe(snapshots, failure);
    vi.advanceTimersByTime(1500);
    expect(snapshots.mock.lastCall?.[0].complete).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(failure).not.toHaveBeenCalled();
  });
});
