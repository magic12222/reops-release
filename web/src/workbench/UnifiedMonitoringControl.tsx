import { t, useLocale } from '../i18n';
import {useEffect,useRef,useState} from 'react';
import {Activity,Pause,Play} from 'lucide-react';
import {createVikunjaClient} from './vikunjaClient';
import type {VikunjaState} from './vikunjaClient';
import {createMonitorClient} from './monitorClient';
import type {MonitorStatus} from './monitorClient';
import {VikunjaRecoveryControl} from './VikunjaRecoveryControl';
import './UnifiedMonitoringControl.css';

export function UnifiedMonitoringControl({active,status,onChanged}:{active:boolean;status:MonitorStatus;onChanged:()=>void}) {
  useLocale();
  const client=useRef(createVikunjaClient()).current,monitor=useRef(createMonitorClient()).current;
  const [state,setState]=useState<VikunjaState|null>(null),[pending,setPending]=useState(false),[error,setError]=useState('');
  const mutation=useRef(false),version=useRef(0),alive=useRef(false);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{
    if(!active)return;const abort=new AbortController();let busy=false;
    const read=async()=>{if(busy||mutation.current||document.hidden)return;const requestVersion=version.current;busy=true;try{const next=await client.status(abort.signal);if(!abort.signal.aborted&&requestVersion===version.current)setState(next);}catch{if(!abort.signal.aborted&&requestVersion===version.current)setState(null);}finally{busy=false;}};
    void read();const timer=window.setInterval(()=>void read(),2000);document.addEventListener('visibilitychange',read);return()=>{abort.abort();window.clearInterval(timer);document.removeEventListener('visibilitychange',read);};
  },[active,client]);
  const target=status.targets[0],enabled=state?.automation.mode==='automatic';
  const seconds=Math.max(0,Math.floor(state?.automation.remaining_seconds??0));
  const remaining=seconds>=3600?`${Math.floor(seconds/3600)}h ${Math.floor(seconds%3600/60)}m`:seconds>=60?`${Math.floor(seconds/60)}m ${seconds%60}s`:`${seconds}s`;
  async function start(){
    if(!active||mutation.current||!status.unified_monitoring||!state?.monitor_offer_id)return;
    mutation.current=true;version.current++;
    setPending(true);setError('');
    try{const next=await client.startAutomatic(state.monitor_offer_id);if(alive.current){setState(next);onChanged();}}
    catch{if(alive.current)setError('Automatic handling was not enabled. Check target readiness and refresh the connection; no recovery permission is assumed.');}
    finally{mutation.current=false;if(alive.current)setPending(false);}
  }
  async function pause(){
    if(!active||mutation.current)return;
    mutation.current=true;version.current++;
    setPending(true);setError('');
    try{await monitor.status();await monitor.command('pause');const next=await client.disable();if(alive.current){setState(next);onChanged();}}
    catch{if(alive.current)setError('Pause could not be confirmed. Check the current monitoring and policy state.');}
    finally{mutation.current=false;if(alive.current)setPending(false);}
  }
  return <div className="wb-operations"><section className="unified-monitor" aria-label={t("Monitoring and automatic handling")} aria-busy={pending}>
    <div className="unified-monitor-top"><div><Activity size={16}/><strong>{target?.name ?? t('Business monitoring')}</strong><span>{enabled ? t('Monitoring enabled') : target?.monitoring==='watching' ? t('Monitoring only') : t('Monitoring paused')}</span><span className={`unified-health ${target?.health??'unknown'}`}>{t("Current health · ")}{t(target?.health??'unknown')}</span><span>{state ? enabled ? t('Authorized') : t('Not authorized') : t('Authorization pending')}</span></div>{enabled?<button disabled={!active||pending} onClick={()=>void pause()}><Pause size={13}/>{t("Pause monitoring & handling")}</button>:<button disabled={!active||pending||!status.unified_monitoring||!state?.monitor_offer_id||!!state.demo_busy} onClick={()=>void start()}><Play size={13}/>{pending ? t('Checking readiness…') : t('Start monitoring & automatic handling')}</button>}</div>
    <div className="unified-monitor-scope"><span>{enabled ? t("{0} recoveries left · {1} remaining", t(state.automation.remaining_actions), t(remaining)) : t('Up to 3 recoveries · 8h limit')}{t(" · 60s apart")}</span><span>{enabled&&state?.automation.plan_id!=='vikunja_dependency_v1' ? t('Database only · application start not authorized') : t('Database → SQL → app only after confirmed exit')}</span><span>{t("One attempt / incident · no fault injection · model only with verified API (≤3 × 512 tokens)")}</span></div>
    <p className="unified-consequence">{t("Continues after this page closes. Pause revokes approval; submitted actions finish verification.")}</p><details className="unified-policy"><summary>{t("Authorization scope & consequences")}</summary><p>{t("This approval enables monitoring and fixed recovery for this Vikunja target for 8 hours, up to 3 incidents, at least 60 seconds apart. Start the database once per incident, wait for SQL, and start the same application only with confirmed dependent exit evidence. A running application is never restarted.")}</p><p>{t("Current identity, Safety and action checks remain required. No fault injection or arbitrary commands. Pause to revoke approval. An already submitted action finishes verification.")}</p><p>{t("Model analysis requires a separately verified API: up to 3 rounds × 512 output tokens per incident. Configuration does not establish that a model participated in this run.")}</p></details>
    {!status.unified_monitoring&&<p role="status">{t("Load the updated monitoring service to enable the single approval entry.")}</p>}
    {enabled&&state?.automation.plan_id!=='vikunja_dependency_v1'&&<p role="status">{t("The previous database-only scope remains in force. Pause it before approving the combined dependency plan.")}</p>}
    {!state?.monitor_offer_id&&!enabled&&<p role="status">{t("A selected, running application and database are required before approval. Refresh the connection after checking the target.")}</p>}
    {error&&<p role="alert">{t(error)}</p>}
  </section><VikunjaRecoveryControl active={active} singleApproval compact businessWatching={target?.monitoring==='watching'} applicationStopped={target?.components.find(x=>x.id==='api')?.health==='unhealthy'} databaseStopped={target?.components.find(x=>x.id==='postgres')?.health==='unhealthy'}/></div>;
}
