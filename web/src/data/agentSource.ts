import { DashboardApiError, readEvents, readRun, readRuns, validEvent, validRun } from './api';
import { agentFixtures } from './agentFixtures';
import type { EventPage, Provenance, RunPage, RunRecord } from '../types/dashboard';

// Agent-only source routing: the general C API client retains its existing contract.
export function agentSource(source: Provenance, fetcher: typeof fetch = fetch) {
  async function local<T>(read: () => T, signal?: AbortSignal): Promise<T> {
    // Match asynchronous readers and allow selection cleanup to cancel a pending local read.
    await Promise.resolve();
    signal?.throwIfAborted();
    return structuredClone(read());
  }
  function fixture(id: string) {
    const record = agentFixtures.find(item => item.run.id === id);
    if (!record) throw new DashboardApiError('not_found');
    if (!validRun(record.run) || record.run.source !== 'offline_fixture'
      || !record.events.every(item => validEvent(item) && item.source === 'offline_fixture')) {
      throw new DashboardApiError('invalid_response');
    }
    return record;
  }
  return {
    readRuns: (signal?: AbortSignal): Promise<RunPage> => source === 'offline_fixture'
      ? local(() => ({ items: agentFixtures.map(item => fixture(item.run.id).run),
        total: agentFixtures.length, limit: 50, offset: 0 }), signal)
      : readRuns(source, signal, fetcher),
    readRun: (id: string, signal?: AbortSignal): Promise<RunRecord> => source === 'offline_fixture'
      ? local(() => fixture(id).run, signal) : readRun(id, signal, fetcher),
    readEvents: (id: string, signal?: AbortSignal): Promise<EventPage> => source === 'offline_fixture'
      ? local(() => { const record = fixture(id); return { run_id: id, items: record.events, total: record.events.length }; }, signal)
      : readEvents(id, signal, fetcher),
  };
}
