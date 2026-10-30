import { t, useLocale } from '../i18n';
import { useEffect, useState } from 'react';
import { ExecutionExplorer } from '../components/ExecutionExplorer';
import type { LoadState, RunDetail } from '../components/LiveRecovery';
import { readWorkbench } from './contract';
import { workbenchTrace } from './traceProjection';

export function WorkbenchAgentTrace({ active, traceId }: { active: boolean; traceId: string }) {
  useLocale();
  const [detail, setDetail] = useState<LoadState<RunDetail>>({ kind: 'loading' });
  const [eventId, setEventId] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => { setEventId(null); setDetail({kind:'loading'}); }, [traceId]);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController(); let busy = false;
    const read = async () => {
      if (busy || document.hidden) return;
      busy = true;
      try { const data = await readWorkbench(abort.signal); const projected = workbenchTrace(data, traceId);
        if (!abort.signal.aborted) setDetail({ kind:'ready', data: projected });
      } catch { if (!abort.signal.aborted) setDetail({kind:'error',code:'workbench_trace_unavailable'}); }
      finally { busy = false; }
    };
    void read(); const timer = window.setInterval(() => void read(), 2000);
    return () => { abort.abort(); window.clearInterval(timer); };
  }, [active, traceId, refresh]);
  return <section className="recovery-section section shell live-recovery agent-intelligence" aria-label={t("Workbench trace in Agent")}>
    <header className="agent-page-header"><div><h1>{t("Agent · Workbench trace")}</h1><p>{t("Inspect the same recorded incident and events.")}</p></div>
      <a className="trace-button" href={`/workbench?source=real&trace=${encodeURIComponent(traceId)}`}>{t("Return to this incident")}</a></header>
    <p className="agent-read-status" role="status">{t("WORKBENCH PROJECTION · Read only · This view reads B through the workbench API. It does not claim that C imported these records.")}</p>
    <p className="wb-trace-notice">{t("Trace: ")}{traceId}</p>
    <ExecutionExplorer detail={detail} selectedEventId={eventId} onSelectEvent={setEventId} active={active}
      scope={`workbench:${traceId}`} error={() => 'The exact workbench trace is unavailable, ambiguous, or invalid. No other run or sample has been substituted.'}
      onRetry={() => setRefresh(value => value + 1)} />
  </section>;
}
