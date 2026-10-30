import { demoSteps } from './demoData';
import { snapshotAt } from './source';
import type { RecoverySnapshot } from '../types/agent';

// Keep verification pending (6) separate from verified (7), including in manual navigation.
export const recoveryStageStops = [-1, 0, 3, 5, 6, 7] as const;
export function recoveryStageTarget(index: number, direction: -1 | 1): number {
  return direction === 1
    ? recoveryStageStops.find(stop => stop > index) ?? 7
    : recoveryStageStops.findLast(stop => stop < index) ?? -1;
}

export interface RecoveryPlaybackState {
  snapshot: RecoverySnapshot | null;
  running: boolean;
  offset: number;
  error: string | null;
  revision: number;
}
export const initialRecoveryPlayback: RecoveryPlaybackState = {
  snapshot: null, running: false, offset: 0, error: null, revision: 0,
};
export type RecoveryPlaybackAction =
  | { type: 'start' | 'reset' | 'pause' | 'toggle' | 'step' }
  | { type: 'seek'; index: number }
  | { type: 'navigate'; direction: -1 | 1 }
  | { type: 'event'; direction: -1 | 1 }
  | { type: 'tick'; revision: number; snapshot: RecoverySnapshot }
  | { type: 'failure'; revision: number; error: string };

function atIndex(index: number): RecoverySnapshot | null {
  return index < 0 ? null : snapshotAt(demoSteps[Math.min(index, demoSteps.length - 1)].at);
}

/** Atomic local replay updates. A callback from an older subscription cannot overwrite a new action. */
export function recoveryPlaybackReducer(state: RecoveryPlaybackState, action: RecoveryPlaybackAction): RecoveryPlaybackState {
  if (action.type === 'tick' || action.type === 'failure') {
    if (!state.running || state.revision !== action.revision) return state;
    return action.type === 'failure'
      ? { ...state, running: false, error: action.error }
      : { ...state, snapshot: action.snapshot, running: !action.snapshot.complete };
  }
  if (action.type === 'pause' && !state.running) return state;
  if (action.type === 'event' && state.snapshot === null) return state;
  const revision = state.revision + 1;
  if (action.type === 'reset') return { ...initialRecoveryPlayback, revision };
  if (action.type === 'start') return { snapshot: snapshotAt(0), offset: 0, running: true, error: null, revision };
  if (action.type === 'pause') return { ...state, running: false, revision };
  if (action.type === 'toggle') {
    if (state.snapshot === null || state.snapshot.complete) return state;
    return { ...state, running: !state.running, offset: state.snapshot.elapsed, revision };
  }
  const currentIndex = state.snapshot?.index ?? -1;
  const index = action.type === 'seek' ? action.index
    : action.type === 'event' ? Math.max(0, Math.min(currentIndex + action.direction, demoSteps.length - 1))
    : action.type === 'navigate' ? recoveryStageTarget(currentIndex, action.direction)
      : Math.min(currentIndex + 1, demoSteps.length - 1);
  const snapshot = atIndex(index);
  return { snapshot, offset: snapshot?.elapsed ?? 0, running: false, error: null, revision };
}
