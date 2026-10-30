/** C4 queues intent only. There is no browser authorization or control-plane credential. */
export interface Experiment {
  id: string; scenario: 'phase8_stopped_api'; source: 'real';
  state: 'waiting_operator' | 'waiting_authorization' | 'finished';
  requested_at: string; started_at: string | null; finished_at: string | null;
  incident_id: string | null; trace_id: string | null;
  ground_truth: { component: string; root_cause: string; injection: string; expected_recovery: string };
  authorization: string; injection: string; recovery: string; verify: string;
  cleanup: string; result: string; error: string | null;
  review_required?: boolean;
  manual_review?: { reviewer: string; reviewed_at: string } | null;
  report?: Record<string, unknown>;
}

export interface Capabilities { entry: string; scenarios: string[]; request_enabled: boolean; request_blocked: boolean; execution: string }

async function json(path: string, init: RequestInit = {}): Promise<unknown> {
  const response = await fetch(`/api/v1/experiments${path}`, {
    ...init, cache: 'no-store', credentials: 'omit', redirect: 'error', mode: 'same-origin',
  });
  if (!response.ok) throw new Error(`C4 API ${response.status}`);
  return response.json();
}

export async function readExperimentControl(signal?: AbortSignal): Promise<{ capabilities: Capabilities; items: Experiment[] }> {
  const [capabilities, page] = await Promise.all([
    json('/capabilities', { signal }) as Promise<Capabilities>, json('', { signal }) as Promise<{ items: Experiment[] }>,
  ]);
  if (!Array.isArray(page.items) || !Array.isArray(capabilities.scenarios)
      || typeof capabilities.request_enabled !== 'boolean'
      || typeof capabilities.request_blocked !== 'boolean') throw new Error('invalid C4 response');
  return { capabilities, items: page.items };
}

export async function requestExperiment(): Promise<Experiment> {
  return json('', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario: 'phase8_stopped_api' }) }) as Promise<Experiment>;
}
