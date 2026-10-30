import type { RunPage } from '../types/dashboard';

// An absent exact match must not silently open another incident.
export function linkedRun(page: RunPage, trace: string): string | null {
  return page.items.find(item => item.source === 'real' && item.trace_id === trace)?.id ?? null;
}
