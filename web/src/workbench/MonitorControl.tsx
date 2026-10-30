import { t, useLocale, getLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import { Activity, Link2, Pause, Play, RefreshCw } from 'lucide-react';
import { createMonitorClient, MonitorError } from './monitorClient';
import type { MonitorStatus } from './monitorClient';
import { VikunjaRecoveryControl } from './VikunjaRecoveryControl';
import {UnifiedMonitoringControl} from './UnifiedMonitoringControl';

export function MonitorControl({ active, onChanged, targetId = null }: { active: boolean; onChanged: () => void; targetId?: string | null }) {
  useLocale();
  const client = useRef(createMonitorClient()).current;
  const [status,setStatus] = useState<MonitorStatus | null>(null);
  const [pending,setPending] = useState(false);
  const [error,setError] = useState('');
  const mounted = useRef(false);
  const mutation = useRef(false);
  const version = useRef(0);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  },[]);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController();
    let reading = false;
    const read = async () => {
      if (reading || mutation.current || document.hidden) return;
      const requestVersion = version.current;
      reading = true;
      try { const value = await client.status(abort.signal); if (!abort.signal.aborted && requestVersion === version.current) { setStatus(value); } }
      catch { if (!abort.signal.aborted && requestVersion === version.current) setStatus(null); }
      finally { reading = false; }
    };
    void read();
    const timer = window.setInterval(() => void read(),2000);
    document.addEventListener('visibilitychange', read);
    return () => { abort.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', read); };
  },[active,client]);
  const act = async (operation?: 'select' | 'start' | 'pause') => {
    if (!active || mutation.current) return;
    mutation.current = true; version.current++;
    setPending(true); setError('');
    try {
      const value = operation ? await client.command(operation) : await client.status();
      if (mounted.current) { setStatus(value); onChanged(); }
    } catch (e) { if (mounted.current) setError(e instanceof MonitorError ? e.message : 'The monitoring request failed.'); }
    finally { mutation.current = false; if (mounted.current) setPending(false); }
  };
  const target = targetId ? status?.targets.find(item => item.id === targetId) : status?.targets[0];
  const watching = target?.monitoring === 'watching';
  const disabled = !active || pending || !status?.enabled || status.busy;
  if(status?.recovery_available && target?.id==='reops-vikunja-demo')return <UnifiedMonitoringControl active={active} status={{...status,targets:[target]}} onChanged={onChanged}/>;
  return <div className="wb-operations"><section id="business-monitoring" className="wb-monitor-controls" aria-label={t("Business monitoring")} aria-busy={pending}>
    <div><Activity size={17} /><span><small>{t("BUSINESS MONITORING")}</small><strong>{target?.name ?? t('Business target')}</strong></span></div>
    <div className="wb-monitor-facts"><span className={`wb-state ${watching?'healthy':'unknown'}`}>{!status ? t('Connection unavailable') : target ? watching ? t('Monitoring running') : target.monitoring==='paused' ? t('Monitoring paused') : t('Not connected') : t('Not connected')}</span>{target&&<span className={`wb-state ${target.health}`}><span className={`wb-dot ${target.health}`}/>{target.health === 'healthy' ? t('Healthy') : target.health === 'unhealthy' ? t('Unhealthy') : t('Health unknown')}</span>}</div>
    <div className="wb-monitor-buttons"><button disabled={!active || pending} onClick={() => void act()} aria-label={t("Refresh monitoring connection")}><RefreshCw size={13} /></button>
      {!watching && <button disabled={disabled || !!targetId && !target} onClick={() => void act('select')}><Link2 size={13} />{target ? t('Reconnect target') : t('Connect target')}</button>}
      <button disabled={disabled || !target} onClick={() => void act(watching ? 'pause' : 'start')}>{watching ? <Pause size={13} /> : <Play size={13} />}{watching ? t('Pause business monitoring') : t('Enable business monitoring')}</button></div>
    {target&&<p className="wb-business-observation">{watching ? t('Last business check') : target.monitoring==='paused' ? t('Last observation · monitoring paused') : t('Last observation · not connected')} · {target.observed_at ? t(new Date(target.observed_at).toLocaleString(getLocale(),{timeZone:'Asia/Shanghai',hour12:false})) : t('No observation')}{t(" CST")}</p>}
    {status && !status.enabled && <p role="status">{t("Monitoring controls are disabled on this service.")}</p>}
    {status && targetId && !target && <p role="status">{t("The selected target has no monitoring controls on this connection.")}</p>}
    {status?.agent?.enabled && <details className="wb-monitor-integration"><summary>{t("Agent connection · ")}{t(status.agent.state)}</summary><p>{t("Fixed recovery requires separate authorization. Model diagnosis is managed in Execution.")}</p></details>}
    {status?.agent?.state === 'error' && <p role="alert">{t("B worker unavailable · persisted records retained")}</p>}
    {error && <p role="alert">{t(error)}</p>}
    {status?.dependency_records==='conflict_or_unavailable'&&<p role="alert">{t("Recovery records could not be synchronized. Saved records are retained; the knowledge feed may be incomplete. Inspect the source audit before continuing.")}</p>}
  </section>{status?.recovery_available && target?.id === 'reops-vikunja-demo' ? <VikunjaRecoveryControl active={active} businessWatching={watching} applicationStopped={target.components.find(item=>item.id==='api')?.health==='unhealthy'} databaseStopped={target.components.find(item=>item.id==='postgres')?.health==='unhealthy'} /> : status && <p className="wb-recovery-unavailable">{t("Automatic recovery · unavailable for this target on this connection")}</p>}</div>;
}
