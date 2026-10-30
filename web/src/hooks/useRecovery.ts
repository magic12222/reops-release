import { useEffect, useReducer, useRef } from 'react';
import { createDemoSource } from '../data/source';
import { initialRecoveryPlayback, recoveryPlaybackReducer } from '../data/recoveryPlayback';
import type { RecoveryPlaybackAction } from '../data/recoveryPlayback';

export function useRecovery(active = true) {
  const [state, dispatch] = useReducer(recoveryPlaybackReducer, initialRecoveryPlayback);
  const subscription = useRef<(() => void) | null>(null);
  function update(action: RecoveryPlaybackAction) {
    // Stop synchronously, rather than waiting for the next effect cleanup after a click.
    subscription.current?.(); subscription.current = null;
    dispatch(action);
  }
  useEffect(() => {
    if (!active || !state.running) return;
    const revision = state.revision;
    const stop = createDemoSource(state.offset).subscribe(
      snapshot => dispatch({ type: 'tick', revision, snapshot }),
      failure => dispatch({ type: 'failure', revision, error: failure.message }),
    );
    subscription.current = stop;
    return () => { stop(); if (subscription.current === stop) subscription.current = null; };
  }, [active, state.running, state.offset, state.revision]);
  // Returning to a cached route never restarts its local replay.
  useEffect(() => { if (!active) update({ type: 'pause' }); }, [active]);
  useEffect(() => {
    const pauseWhenHidden = () => { if (document.hidden) update({ type: 'pause' }); };
    document.addEventListener('visibilitychange', pauseWhenHidden);
    return () => document.removeEventListener('visibilitychange', pauseWhenHidden);
  }, []);
  return { snapshot: state.snapshot, running: state.running, error: state.error,
    pause: () => update({ type: 'pause' }),
    seek: (index: number) => update({ type: 'seek', index }),
    navigate: (direction: -1 | 1) => update({ type: 'navigate', direction }),
    moveEvent: (direction: -1 | 1) => update({ type: 'event', direction }),
    start: () => update({ type: 'start' }),
    reset: () => update({ type: 'reset' }),
    toggle: () => update({ type: 'toggle' }),
    step: () => update({ type: 'step' }),
  };
}
