/** Same-origin SSE over C's committed read model. No A endpoint or token here. */
import { toReadTrace } from './adapter';
import { DashboardApiError, validEvent, validRun } from './api';
import type { Provenance, RunRecord, EventRecord } from '../types/dashboard';

export type FeedState = 'ready' | 'waiting_for_journal' | 'error' | 'unconfigured';
export interface LiveSnapshot { run: RunRecord; events: EventRecord[]; feed_state?: FeedState }
export type LiveConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'waiting_for_journal'
  | 'unconfigured' | 'source_error' | 'gone' | 'invalid_response';

export function parseLiveSnapshot(payload: string, runId: string, source: Provenance): LiveSnapshot {
  let value: unknown;
  try { value = JSON.parse(payload); }
  catch { throw new DashboardApiError('invalid_response'); }
  if (typeof value !== 'object' || value === null || Array.isArray(value)
      || !('run' in value) || !validRun(value.run) || value.run.id !== runId || value.run.source !== source
      || !('events' in value) || !Array.isArray(value.events) || !value.events.every(validEvent)) {
    throw new DashboardApiError('invalid_response');
  }
  try {
    const trace = toReadTrace(value.run, value.events);
    if (trace.some((step, index) => step.event.ordinal !== index)) throw new Error('trajectory_gap');
  } catch { throw new DashboardApiError('invalid_response'); }
  if ('feed_state' in value && !['ready', 'waiting_for_journal', 'error', 'unconfigured'].includes(String(value.feed_state))) {
    throw new DashboardApiError('invalid_response');
  }
  return { run: value.run, events: value.events,
    feed_state: 'feed_state' in value ? value.feed_state as FeedState : undefined };
}

export function subscribeRun(runId: string, source: Provenance,
  onSnapshot: (snapshot: LiveSnapshot) => void,
  onState: (state: LiveConnectionState) => void,
  makeSource: (url: string) => EventSource = url => new EventSource(url, { withCredentials: false }),
): () => void {
  const url = `/api/v1/runs/${encodeURIComponent(runId)}/stream?source=${source}`;
  const stream = makeSource(url);
  let closed = false;
  onState('connecting');
  stream.onopen = () => { if (!closed) onState('connecting'); };
  stream.onerror = () => { if (!closed) onState('reconnecting'); };
  stream.addEventListener('snapshot', event => {
    if (closed) return;
    try {
      const snapshot = parseLiveSnapshot((event as MessageEvent).data, runId, source);
      onSnapshot(snapshot);
      onState(snapshot.feed_state === 'error' ? 'source_error'
        : snapshot.feed_state === 'ready' || !snapshot.feed_state ? 'connected' : snapshot.feed_state);
    } catch {
      onState('invalid_response');
      stream.close();
      closed = true;
    }
  });
  stream.addEventListener('gone', () => {
    if (closed) return;
    onState('gone');
    stream.close();
    closed = true;
  });
  return () => { closed = true; stream.close(); };
}
