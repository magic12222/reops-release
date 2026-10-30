import { describe, expect, it } from 'vitest';
import { parseLiveSnapshot, subscribeRun } from './live';
import type { RunRecord, EventRecord } from '../types/dashboard';

const run: RunRecord = {
  id: 'run-1', incident_id: 'incident-1', trace_id: 'trace-1', case_id: null, fault_id: null,
  source: 'real', status: 'observing', started_at: null, finished_at: null,
  model_calls: null, action_count: null, recovery_latency_ms: null, success: null, metadata: {},
};
const event: EventRecord = {
  event_id: 'event-1', run_id: run.id, incident_id: run.incident_id, trace_id: run.trace_id,
  case_id: null, ordinal: 0, parent_event_id: null, stage: 'observe', status: 'started',
  timestamp: '2026-10-07T09:00:00Z', message: 'observe', source: 'real',
  origin: 'trace_journal', original_event_id: 'event-1', data: {},
};

class FakeSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  listeners = new Map<string, (event: MessageEvent) => void>();
  addEventListener(name: string, callback: EventListenerOrEventListenerObject) {
    this.listeners.set(name, callback as (event: MessageEvent) => void);
  }
  emit(name: string, data: unknown) {
    this.listeners.get(name)?.({ data: JSON.stringify(data) } as MessageEvent);
  }
  close() { this.closed = true; }
}

describe('C SSE live source', () => {
  it('validates each committed snapshot and rejects mixed provenance or gaps', () => {
    expect(parseLiveSnapshot(JSON.stringify({ run, events: [event] }), run.id, 'real').events).toHaveLength(1);
    expect(() => parseLiveSnapshot(JSON.stringify({ run, events: [{ ...event, source: 'simulation' }] }), run.id, 'real'))
      .toThrow('invalid_response');
    expect(() => parseLiveSnapshot(JSON.stringify({ run, events: [{ ...event, ordinal: 2 }] }), run.id, 'real'))
      .toThrow('invalid_response');
    expect(() => parseLiveSnapshot(JSON.stringify({ run: { ...run, source: 'offline_fixture' }, events: [] }), run.id, 'real'))
      .toThrow('invalid_response');
    expect(() => parseLiveSnapshot(JSON.stringify({ run, events: [], feed_state: 'healthy' }), run.id, 'real'))
      .toThrow('invalid_response');
  });

  it('reconnects without credentials and replaces the trace with authoritative snapshots', () => {
    const fake = new FakeSource();
    const urls: string[] = [];
    const states: string[] = [];
    const lengths: number[] = [];
    const stop = subscribeRun(run.id, 'real', snapshot => lengths.push(snapshot.events.length),
      state => states.push(state), url => { urls.push(url); return fake as unknown as EventSource; });
    expect(urls).toEqual(['/api/v1/runs/run-1/stream?source=real']);
    expect(urls[0]).not.toContain('token');
    fake.emit('snapshot', { run, events: [event], feed_state: 'ready' });
    fake.onerror?.();
    const verified = { ...event, event_id: 'event-2', ordinal: 1, parent_event_id: event.event_id,
      stage: 'verification', status: 'success' };
    fake.emit('snapshot', { run: { ...run, status: 'recovered', success: true }, events: [event, verified], feed_state: 'ready' });
    expect(lengths).toEqual([1, 2]);
    expect(states).toEqual(['connecting', 'connected', 'reconnecting', 'connected']);
    fake.emit('snapshot', { run, events: [event], feed_state: 'error' });
    expect(states.at(-1)).toBe('source_error');
    stop();
    expect(fake.closed).toBe(true);
  });

  it('subscribes to the explicitly selected offline fixture source', () => {
    const fake = new FakeSource();
    const fixtureRun = { ...run, source: 'offline_fixture' as const };
    const fixtureEvent = { ...event, source: 'offline_fixture' as const };
    const urls: string[] = [];
    const lengths: number[] = [];
    subscribeRun(run.id, 'offline_fixture', snapshot => lengths.push(snapshot.events.length),
      () => {}, url => { urls.push(url); return fake as unknown as EventSource; });
    fake.emit('snapshot', { run: fixtureRun, events: [fixtureEvent], feed_state: 'ready' });
    fake.onerror?.();
    fake.emit('snapshot', { run: fixtureRun, events: [fixtureEvent,
      { ...fixtureEvent, event_id: 'event-2', parent_event_id: 'event-1', ordinal: 1 }], feed_state: 'ready' });
    expect(urls).toEqual(['/api/v1/runs/run-1/stream?source=offline_fixture']);
    expect(lengths).toEqual([1, 2]);
  });

  it('stops on malformed data or a deleted run', () => {
    const fake = new FakeSource();
    const states: string[] = [];
    subscribeRun(run.id, 'real', () => {}, state => states.push(state), () => fake as unknown as EventSource);
    fake.emit('snapshot', { run, events: [{ ...event, source: 'simulation' }] });
    expect(states.at(-1)).toBe('invalid_response');
    expect(fake.closed).toBe(true);
    const gone = new FakeSource();
    subscribeRun(run.id, 'real', () => {}, state => states.push(state), () => gone as unknown as EventSource);
    gone.emit('gone', {});
    expect(states.at(-1)).toBe('gone');
    expect(gone.closed).toBe(true);
  });
});
