import { t, useLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Play, X } from 'lucide-react';
import { createControlClient } from '../data/webControl';
import type { ControlStatus } from '../data/webControl';

export function RunControl({ active }: { active: boolean }) {
  useLocale();
  const client = useRef(createControlClient()).current;
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<ControlStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [strategy, setStrategy] = useState<'model' | 'experience'>('model');
  const [now, setNow] = useState(Date.now());
  const current = useRef(active); current.current = active;
  useEffect(() => {
    if (!active || !open) return;
    const controller = new AbortController();
    let reading = false;
    const refresh = async () => {
      if (reading) return;
      reading = true;
      try { const value = await client.status(controller.signal); if (!controller.signal.aborted) setState(value); }
      catch { if (!controller.signal.aborted) setState(null); }
      finally { reading = false; }
    };
    void refresh();
    const timer = window.setInterval(() => { setNow(Date.now()); void refresh(); }, 1200);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [active, open, client]);
  const action = async (operation: () => Promise<unknown>) => {
    setBusy(true); setError(false);
    try { await operation(); const value = await client.status(); if (current.current) setState(value); }
    catch { if (current.current) setError(true); }
    finally { if (current.current) setBusy(false); }
  };
  const job = state?.job;
  const pending = job?.confirmation;
  const remaining = pending ? Math.max(0, Math.ceil(pending.expires_at - now / 1000)) : 0;
  return <section className="wb-run-control" aria-label={t("ResearchLoop recovery run")}>
    <button className="wb-run-toggle" onClick={() => setOpen(value => !value)} aria-expanded={open}><Play size={14} />{t("Run recovery ")}<span>{t("ResearchLoop demo")}</span><ChevronDown size={14} /></button>
    {open && <div className="wb-run-body">
      <p>{t("Prepare an isolated PostgreSQL recovery run. Review and approve its full scope once; the remaining steps run automatically.")}</p>
      {!state ? <p role="status">{t("Run service unavailable. Use the main dashboard service to connect.")}</p> : <>
        <div className="wb-run-options"><span>{state.model.name ?? t('Model service')} · {state.model.model}</span><a href="/api">{t("API settings")}</a>
          <select aria-label={t("Recovery strategy")} disabled={busy || state.busy} value={strategy} onChange={e => setStrategy(e.target.value as 'model' | 'experience')}><option value="model">{t("Model diagnosis")}</option><option value="experience">{t("Reuse experience")}</option></select>
          <button disabled={busy || !state.enabled || !state.model.verified || state.busy} onClick={() => void action(() => client.startRun(strategy))}>{t("Prepare run")}</button></div>
        {job?.state === 'running' && pending && <div className="wb-run-approval"><h3>{t("Approve this run once")}</h3><ul><li>{t("Target: isolated ResearchLoop PostgreSQL; one stop.")}</li><li>{t("Model: ")}{state.model.model}{t("; at most one request, 512 output tokens.")}</li><li>{t("Recovery: one fixed PostgreSQL restart, followed by fresh business verification and memory recording.")}</li><li>{t("Cleanup: at most one additional fixed restart if needed. Approval expires in ")}{t(remaining)}{t("s.")}</li></ul>
          <button disabled={busy || remaining === 0 || pending.request.authorization_mode !== 'single_run'} onClick={() => void action(() => client.approveRun(job, pending))}>{t("Approve & run automatically")}</button></div>}
        {job && <div className="wb-run-status" role="status"><strong>{job.state === 'finished' ? job.result === 'passed' ? t('Run completed') : job.result === 'rejected' ? t('Run not approved') : t('Run ended · inspect recorded evidence') : job.cancel_requested ? t('Cancelling · completing cleanup') : pending ? t('Awaiting your approval') : t('Running automatically')}</strong><span>{job.trace_id}</span>
          {job.state === 'running' && <button disabled={busy || job.cancel_requested} onClick={() => void action(() => client.cancel(job))}><X size={13} />{t("Cancel run")}</button>}<a href="/agent">{t("View recorded runs")}</a></div>}
      </>}
      {error && <p role="alert">{t("The request was not accepted. Refresh the service status before retrying.")}</p>}
    </div>}
  </section>;
}
