import { t, useLocale, getLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { MonitorControl } from '../workbench/MonitorControl';
import { Activity, ArrowRight, ArrowUpRight, Box, Check, ChevronRight, Circle, Clock3, Cpu, Database, Layers3, Network, RefreshCw, Search, Server, Terminal, Workflow } from 'lucide-react';
import { fixtureSnapshot, readWorkbench } from '../workbench/contract';
import type { Incident, Snapshot } from '../workbench/contract';
import { IncidentOverview, RecordedEventBrowser } from '../workbench/WorkbenchIncidentEvidence';
import { RunControl } from '../workbench/RunControl';
import { researchLoopAvailable } from '../deployment';
import './WorkbenchPage.css';
import './WorkbenchRound2.css';
import { incidentHistory, recordedSpan, recoveryMethod } from '../workbench/incidentPresentation';
import { KnowledgeExplorer } from '../workbench/KnowledgeExplorer';
import { DependencyDiagnosisControl } from '../workbench/DependencyDiagnosisControl';
import { ModelConversation } from '../workbench/ModelConversation';
import { IncidentFlow } from '../workbench/IncidentFlow';
import { useSoftwareCatalog } from '../workbench/useSoftwareCatalog';
import { createMonitorClient } from '../workbench/monitorClient';
import { SoftwareDirectory } from '../workbench/SoftwareDirectory';
import { navigate, useRoute } from '../navigation/router';

type Tab = 'trajectory' | 'api' | 'memory';
type Mode = Snapshot['source'];
const labels: Record<string, string> = {
  healthy: 'Healthy', unhealthy: 'Unhealthy', unknown: 'Unknown', watching: 'Watching', paused: 'Paused', not_connected: 'Not connected', ready: 'Connected',
  process: 'Local process', docker: 'Local container', windows_service: 'Windows service', recovered: 'Recovered', failed: 'Failed',
  observing: 'Observing', diagnosing: 'Diagnosing', waiting_human: 'Awaiting approval', executing: 'Executing', verifying: 'Verifying',
  model: 'Model diagnosis', experience: 'Memory reuse', rule: 'Rule diagnosis', succeeded: 'Completed', running: 'Running',
  skipped: 'Skipped', passed: 'Passed', pending: 'Pending', verified: 'Verified', retired: 'Retired', unverified: 'Unverified',
};
const time = (value: string | null) => value && !Number.isNaN(Date.parse(value))
  ? new Intl.DateTimeFormat(getLocale(), { timeZone: 'Asia/Shanghai', hour12: false, year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value)) : 'No observation';

export function WorkbenchView({ mode, data, loading, error, targetId, incidentId, eventId, tab, onMode, onRefresh, onTarget, onIncident, onEvent, onTab, active = true, monitorControls, initialDirectory = false, integrationReady = true, following = false }: {
  mode: Mode; data: Snapshot | null; loading: boolean; error: boolean; targetId: string | null; incidentId: string | null;
  eventId: string | null; tab: Tab; onMode: (mode: Mode) => void; onRefresh: () => void;
  onTarget: (id: string) => void; onIncident: (id: string) => void; onEvent: (id: string) => void; onTab: (tab: Tab) => void; active?: boolean; monitorControls?: ReactNode; initialDirectory?: boolean; integrationReady?: boolean; following?: boolean;
}) {
  useLocale();
  const route=useRoute();
  const integrationToken=new URLSearchParams(route.href.split('?')[1]??'').get('integration')??'';
  const [directory,setDirectory] = useState(initialDirectory && mode==='real' && (typeof window==='undefined' || !new URLSearchParams(window.location.search).has('knowledge')));
  const [expandedIncident, setExpandedIncident] = useState<string | null>(null);
  const catalog = useSoftwareCatalog(active && mode==='real');
  const businessClient=useRef(createMonitorClient()).current;
  const businessBusy=useRef(false);
  const businessActive=useRef(active&&mode==='real');businessActive.current=active&&mode==='real';
  const [businessPending,setBusinessPending]=useState(false);
  const [businessError,setBusinessError]=useState('');
  async function openBusiness() {
    if(!active||mode!=='real'||businessBusy.current)return;
    businessBusy.current=true;setBusinessPending(true);setBusinessError('');
    try {
      const status=await businessClient.status();
      if(!businessActive.current)return;
      const configured=status.targets.find(item=>item.id==='reops-vikunja-demo');
      if(!configured||!status.enabled)throw new Error('The Vikunja business adapter is not connected.');
      if(configured.monitoring!=='watching')await businessClient.command('start');
      if(!businessActive.current)return;
      onTarget(configured.id);onRefresh();setDirectory(false);
      document.getElementById('business-monitoring')?.scrollIntoView({block:'start',behavior:'smooth'});
    } catch(e) {setBusinessError(e instanceof Error?e.message:'Business monitoring could not start.');}
    finally {businessBusy.current=false;setBusinessPending(false);}
  }
  useEffect(()=>{const params=typeof window==='undefined'?null:new URLSearchParams(window.location.search);setDirectory(initialDirectory && mode==='real' && !params?.has('trace') && !params?.has('knowledge'));},[mode,active,initialDirectory,route.href]);
  const [query, setQuery] = useState('');
  const search = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!active) return;
    const focusSearch = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey
          || (event.target instanceof HTMLElement && (event.target.matches('input,textarea,select') || event.target.isContentEditable))) return;
      event.preventDefault(); if(directory) document.querySelector<HTMLInputElement>('.software-directory input[type="search"]')?.focus(); else search.current?.focus();
    };
    window.addEventListener('keydown', focusSearch);
    return () => window.removeEventListener('keydown', focusSearch);
  }, [active,directory]);
  const [filter, setFilter] = useState<'all' | 'attention'>('all');
  const [historyLimit, setHistoryLimit] = useState(50);
  useEffect(() => { setHistoryLimit(50); setQuery(''); setFilter('all'); }, [targetId, mode]);
  const target = data?.targets.find(item => item.id === targetId);
  const incidents = data?.incidents.filter(item => item.target_id === target?.id) ?? [];
  const incident = incidents.find(item => item.id === incidentId);
  const event = incident?.events.find(item => item.id === eventId) ?? incident?.events.at(-1);
  const experiences = data?.experiences.filter(item => item.target_id === target?.id) ?? [];
  const linked = experiences.filter(item => incident?.experience_ids.includes(item.id));
  const sample = mode === 'offline_fixture';
  const visible = incidentHistory(incidents, query, filter === 'attention');
  const visibleWindow = visible.slice(0, historyLimit);
  if (incident && visible.some(item => item.id === incident.id) && !visibleWindow.some(item => item.id === incident.id)) visibleWindow.splice(0, 1, incident);
  return <section className="wb shell" aria-label={t("Local Operations Workbench")} data-active={active} data-following={active && following && !error}>
    <header className="wb-heading"><div><p className="wb-eyebrow">{t("WORKSPACE / LOCAL OPERATIONS")}</p><h1>{t("Operations ")}<span>{t("Workbench")}</span></h1></div>
      <div className="wb-toolbar"><label><span className="sr-only">{t("Workbench data source")}</span><select value={mode} onChange={e => onMode(e.target.value as Mode)}><option value="offline_fixture">{t("Sample preview")}</option><option value="real">{t("Local connection")}</option></select></label>
        <button onClick={()=>{onRefresh();if(directory)catalog.refresh();}} aria-label={t("Refresh workbench")} title={t("Refresh snapshot")}><RefreshCw size={14} className={loading ? 'wb-refreshing' : ''} /><span>{t("Refresh")}</span></button><a className="wb-knowledge-entry" href={`/knowledge-retrieval?source=${mode}`} onClick={event=>{if(event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();navigate(`/knowledge-retrieval?source=${mode}`);}}><Network size={15} />{t("Global knowledge")}<ArrowUpRight size={13} /></a><a href="/api"><Cpu size={14} />{t("API settings")}<ArrowUpRight size={13} /></a></div>
    </header>
    <div className={`wb-source ${sample ? 'sample' : ''}`} role="status"><span className="wb-dot" /><strong>{sample ? t('SAMPLE DATA · NOT A LIVE RUN') : t('LOCAL CONNECTION')}</strong><span>{sample ? t('Explore a recorded example. No actions are executed.') : t('Live monitoring · recorded incidents')}</span><span className="wb-source-end">{loading ? t('Refreshing…') : data ? t("Updated {0} CST", t(time(data.generated_at))) : t('Awaiting snapshot')}</span></div>
    <div className={`wb-frame ${directory ? 'wb-directory-open' : ''}`}>
      <aside className="wb-sidebar" aria-label={t("Applications and incidents")}>
        <div className="wb-sidebar-label"><span>{sample ? t('SAMPLE APPLICATIONS') : t('BUSINESS TARGETS')}</span><span>{t(data?.targets.length ?? 0)}</span></div>
        <div className="wb-target-list">{data?.targets.map(item => <button key={item.id} className={`wb-target ${!directory && targetId === item.id ? 'selected' : ''}`} onClick={() => {setDirectory(false);onTarget(item.id);}} aria-pressed={!directory && targetId === item.id}>
          <span className="wb-app-icon"><Server size={16} /></span><span><strong>{item.name}</strong><small><span className={`wb-dot ${item.health}`} />{t(labels[item.health])} · {t(labels[item.runtime])}</small></span><ChevronRight size={13} /></button>)}
          {!data?.targets.length && <p className="wb-side-empty">{t("Your connected applications will appear here.")}</p>}</div>
        {!sample && <button className="wb-local-browse" aria-pressed={directory} onClick={()=>setDirectory(value=>!value)}><Server size={14}/><strong>{t("Local software")}</strong><span>{t(catalog.data?.records.length ?? '…')}</span><ChevronRight size={12}/></button>}
        <div className="wb-sidebar-label wb-incident-label"><span>{t("INCIDENT HISTORY")}</span><span>{incidents.length}</span></div>
        <label className="wb-search"><Search size={13} /><input ref={search} aria-label={t("Search incidents")} placeholder={t("Find an incident…")} value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') { setQuery(''); e.currentTarget.blur(); } }} /><kbd>/</kbd></label>
        <div className="wb-filters" aria-label={t("Incident filters")}><button aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>{t("All incidents ")}<span>{incidents.length}</span></button><button aria-pressed={filter === 'attention'} onClick={() => setFilter('attention')}>{t("Needs attention")}</button></div>
        <div className="wb-incident-list">{visibleWindow.map(item => <button key={item.id} className={incident?.id === item.id ? 'selected' : ''} onClick={() => {setDirectory(false);onIncident(item.id);}} aria-pressed={incident?.id === item.id}>
          <span className={`wb-incident-symbol ${item.status}`}>{item.status === 'recovered' ? <Check size={13} /> : <Circle size={12} />}</span><span><strong>{target?.name}</strong><em className={`wb-history-result ${item.status}`}>{t(labels[item.status])}</em><small><time dateTime={item.started_at}>{t(time(item.started_at))}{t(" CST")}</time></small><span className="wb-history-title" title={item.title}>{item.title}</span>{recordedSpan(item) && <span className="wb-history-span">{t(recordedSpan(item))}</span>}</span></button>)}
          {visible.length === 0 && <p className="wb-side-empty">{query || filter !== 'all' ? t('No matching incidents.') : t('No incidents recorded for this target.')}</p>}</div>
        {visible.length > historyLimit && <button className="wb-history-more" onClick={()=>setHistoryLimit(value=>value+50)}>{t("Show more · ")}{visibleWindow.length}{t(" of ")}{visible.length}</button>}
        <div className="wb-sidebar-bottom"><p>{t("EXPLORE REOPS")}</p><a href="/agent"><Layers3 size={15} /><span>{t("Agent explorer")}<small>{t("Inspect full execution evidence")}</small></span><ArrowUpRight size={13} /></a><a href="/recovery"><Workflow size={15} /><span>{t("Recovery Lab")}<small>{t("Interactive simulation")}</small></span><ArrowUpRight size={13} /></a></div>
      </aside>
      <div className="wb-workspace">
        <header className="wb-context"><div><Box size={15} /><span>{directory ? t('This computer') : target?.name ?? t('Local workspace')}</span><ChevronRight size={12} /><span>{directory ? t('Software discovery') : t('Monitoring & incidents')}</span></div><span className="wb-context-mode">{sample ? t('PREVIEW') : t('LOCAL')}</span></header>
        {!sample && !directory && !target?.id.startsWith('history:') && monitorControls}
        {directory && !sample ? <SoftwareDirectory data={catalog.data} error={catalog.error} pending={catalog.pending} onRefresh={catalog.refresh} onWatch={(id,watching)=>void catalog.watch(id,watching)} onBusiness={data?.targets.some(item=>item.id==='reops-vikunja-demo')?()=>void openBusiness():undefined} businessWatching={data?.targets.find(item=>item.id==='reops-vikunja-demo')?.monitoring==='watching'} businessPending={businessPending} businessError={businessError}/> : error ? <div className="wb-empty" role="alert"><Activity size={28} /><h2>{t("Connection unavailable")}</h2><p>{t("The snapshot could not be loaded or failed validation.")}<br />{t("Sample data has not been substituted.")}</p><button onClick={onRefresh}>{t("Retry connection ")}<ArrowRight size={14} /></button></div>
          : !data ? <div className="wb-empty" role="status"><RefreshCw size={24} /><h2>{t("Loading your workspace")}</h2><p>{t("Waiting for a validated snapshot.")}</p></div>
          : !target ? <div className="wb-empty"><span className="wb-empty-icon"><Server size={29} /></span><p className="wb-eyebrow">{t("YOUR WORKSPACE IS READY")}</p><h2>{t("Connect your first application")}</h2><p>{t("Follow an incident from the first signal to verified recovery.")}<br />{t("Applications and agent activity will appear as services connect.")}</p><div className="wb-connection-steps"><span><Server size={15} />{t("Targets ")}<b>{t(labels[data.a_status])}</b></span><ArrowRight size={13} /><span><Cpu size={15} />{t("Agent ")}<b>{t(labels[data.b_status])}</b></span></div><button onClick={() => onMode('offline_fixture')}>{t("Explore the sample ")}<ArrowRight size={14} /></button></div>
          : <>
            {(sample || !monitorControls || target.id.startsWith('history:')) && <div className="wb-target-status"><span>{t("Last target observation")}</span><span className={`wb-state ${target.health}`}><span className={`wb-dot ${target.health}`} />{t(labels[target.health])}</span><span><Activity size={12} />{t(labels[target.monitoring])}</span><span title={t(target.observed_at ?? undefined)}><Clock3 size={12} />{t(time(target.observed_at))}{t(" CST")}</span>{sample || !monitorControls ? <button disabled title={t("Monitoring controls are awaiting integration.")}>{t("Start monitoring · Not connected")}</button> : null}</div>}
            {incident ? <>
              <div className="wb-detail-heading"><div><div className="wb-record-id"><span>{t("RECORDED INCIDENT")}</span><time dateTime={incident.started_at}>{t(time(incident.started_at))}{t(" CST")}</time></div><h2>{incident.title}</h2><p>{target.name} · {t(recoveryMethod(incident))}{recordedSpan(incident) ? t(" · {0}", t(recordedSpan(incident))) : ''}</p></div><span className={`wb-status-pill ${incident.status}`}><span className={`wb-dot ${incident.status === 'recovered' ? 'healthy' : incident.status === 'failed' ? 'unhealthy' : ''}`} />{t(labels[incident.status])}</span></div>
              <p className="wb-history-context">{t("Recorded result only. Business health is shown in the latest target observation above.")}</p>
              <div className="wb-detail-tools"><a className="wb-trace-link" href={`/execution?source=${sample?'offline_fixture':'real'}&trace=${encodeURIComponent(incident.trace_id)}`}>{t("Inspect execution ↗")}</a></div>
              <nav className="wb-tabs" aria-label={t("Incident details")}>{([{ id: 'trajectory', label: 'Evidence', count: incident.events.length, Icon: Workflow }, { id: 'api', label: 'API interactions', count: incident.model_calls.length, Icon: Terminal }, { id: 'memory', label: 'Memory & graph', count: linked.length, Icon: Network }] as const).map(({id,label,count,Icon}) => <button key={id} aria-pressed={tab === id} onClick={() => onTab(id)}><Icon size={14} />{t(label)}<span>{t(count)}</span></button>)}</nav>
              <div className={`wb-investigation ${tab === 'memory' ? 'wb-knowledge-wide' : ''}`}>
                <div className="wb-main-pane">
                  {tab === 'trajectory' ? <>
                    <IncidentOverview incident={incident}/>
                    <RecordedEventBrowser incident={incident} event={event} open={expandedIncident===incident.id} onOpen={open=>setExpandedIncident(current=>open?incident.id:current===incident.id?null:current)} onEvent={onEvent}/>
                    <details className="wb-evidence-chain"><summary>{t("Evidence chain · recorded handoffs")}</summary><IncidentFlow data={data} target={target} incident={incident} onEvent={id=>{setExpandedIncident(incident.id);onEvent(id);}} onKnowledge={() => onTab('memory')} /></details>
                  </> : tab === 'api' ? <div className="wb-api">{!sample&&<DependencyDiagnosisControl key={incident.id} incident={incident} active={active} onChanged={onRefresh}/>}<section className="wb-tool-interactions"><h3>{t("Target HTTP, SQL & fixed tools")}</h3>{incident.events.filter(item=>['recovery_execution','verification','recovery_decision'].includes(item.stage)).map(item=><details key={item.id}><summary>{item.title}<small>{t(time(item.timestamp))}</small></summary><ul>{item.evidence.map((value,index)=><li key={index}>{value}</li>)}</ul><button onClick={()=>{onEvent(item.id);setExpandedIncident(incident.id);onTab('trajectory');}}>{t("Inspect source event")}</button></details>)}</section>{incident.model_calls.length === 0 ? <div className="wb-content-empty"><Database size={26} /><h3>{incident.diagnosis_source === 'experience' ? t('Experience-based recovery') : t('No model calls recorded')}</h3><p>{t("No model request is recorded for this incident. Usage is unknown.")}</p><details className="wb-model-provenance"><summary>{t("Model records & recovery provenance")}</summary><p>{incident.diagnosis_source === 'experience' ? t('No model request is recorded. See Memory for conditions and provenance.') : t('No model request is exposed by this feed. Usage is unknown; absence is not proof of zero calls. Original fixed-policy audit records explicitly state zero model calls; an optional later diagnosis is recorded separately.')}</p></details><button onClick={() => onTab('memory')}>{t("Inspect memory ")}<ArrowRight size={13} /></button></div> : <ModelConversation calls={incident.model_calls} active={active}/>}</div>
                  : <KnowledgeExplorer workbench key={`${mode}:${target.id}:${integrationToken}`} active={active} integrationReady={integrationReady} data={data} targetId={target.id} incidentId={incident.id}
                    onIncident={id => { onIncident(id); onTab('trajectory'); }} onEvent={(id, event) => {setExpandedIncident(id); onIncident(id); onEvent(event); onTab('trajectory'); }} />}
                  <details className="wb-raw"><summary>{t("Full incident record ")}<span>{t("JSON & identifiers")}</span></summary><p>{t("Incident: ")}{incident.id}<br />{t("Trace: ")}{incident.trace_id}</p><pre>{JSON.stringify(incident, null, 2)}</pre></details>
                </div>
                <aside className="wb-inspector" aria-label={t("Incident context")}><details className="wb-inspector-section wb-target-context"><summary>{t("Current target context")}</summary><div className="wb-section-heading"><Box size={14} /><h3>{t("Latest target observation")}</h3></div><dl><dt>{t("Observed")}</dt><dd>{t(time(target.observed_at))}{t(" CST")}</dd><dt>{t("Runtime")}</dt><dd>{t(labels[target.runtime])}</dd><dt>{t("Monitoring")}</dt><dd>{t(labels[target.monitoring])}</dd><dt>{t("Components")}</dt><dd>{target.components.length}</dd></dl><div className="wb-components">{target.components.map(component => <span key={component.id}><span className={`wb-dot ${component.health}`} />{component.name}<em>{t(labels[component.health])}</em></span>)}</div><details className="wb-capabilities"><summary>{t("Allowed actions")}</summary><p>{target.allowed_actions.join(', ') || t('None')}</p><small>{t("Configured capabilities only; no action is executed here.")}</small></details></details><div className="wb-inspector-section"><button className="wb-memory-link" onClick={() => onTab('memory')}><Database size={14}/><span>{t("Memory & graph · ")}{linked.length}{t(" linked")}</span><ChevronRight size={13}/></button></div>{sample ? <p className="wb-crosslink-note">{t("Workbench sample and Agent fixtures have separate traces.")}</p> : <a className="wb-agent-link" href={`/agent?source=real&feed=workbench&trace=${encodeURIComponent(incident.trace_id)}`}>{t("Inspect this trace in Agent ")}<ArrowUpRight size={14} /><small>{t("Same workbench feed · no C import required")}</small></a>}</aside>
              </div>
            </> : <><div className="wb-no-history"><Clock3 size={18}/><div><h2>{t("No incident selected")}</h2><p>{incidents.length ? t('Select a recorded incident to inspect its evidence.') : t('No incidents recorded for this business target.')}</p></div><button aria-pressed={tab==='memory'} onClick={()=>onTab(tab==='memory'?'trajectory':'memory')}>{t("Memory & graph")}</button></div>
              {tab === 'memory' && <KnowledgeExplorer workbench key={`${mode}:${target.id}:${integrationToken}`} active={active} integrationReady={integrationReady} data={data} targetId={target.id} incidentId={null} onIncident={id=>{onIncident(id);}} onEvent={(id, event) => {setExpandedIncident(id); onIncident(id); onEvent(event); onTab('trajectory'); }} />}</>}
          </>}
        <footer className="wb-footer"><span><span className={`wb-dot ${data?.a_status === 'ready' ? 'healthy' : ''}`} />{t("Targets ")}{sample ? t('sample feed') : data?.a_status === 'ready' ? t('connected') : t('not connected')}<span className={`wb-dot ${data?.b_status === 'ready' ? 'healthy' : ''}`} />{t("Agent ")}{sample ? t('sample feed') : data?.b_status === 'ready' ? t('connected') : t('not connected')}</span><span>{sample ? t('Preview workspace') : t('Local snapshot')}</span></footer>
      </div>
    </div>
  </section>;
}

export function WorkbenchPage({ active = true }: { active?: boolean }) {
  useLocale();
  const route=useRoute();
  const params = new URLSearchParams(route.href.split('?')[1] ?? '');
  const mode: Mode = params.get('source') === 'offline_fixture' ? 'offline_fixture' : 'real';
  const requestedTrace = params.get('trace');
  const [browsing, setBrowsing] = useState(false);
  const [data, setData] = useState<Snapshot | null>(() => mode === 'real' ? null : fixtureSnapshot());
  const [targetId, setTarget] = useState<string | null>(() => mode === 'real' ? null : 'fixture-local-api');
  const [incidentId, setIncident] = useState<string | null>(() => mode === 'real' ? null : 'fixture-incident-01');
  const [eventId, setEvent] = useState<string | null>(() => mode === 'real' ? null : 'fixture-event-1-3');
  const [tab, setTab] = useState<Tab>(() => params.has('knowledge') ? 'memory' : 'trajectory');
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [loadedHref,setLoadedHref] = useState<string|null>(null);
  useEffect(() => {
    if (!active) return;
    setData(mode === 'offline_fixture' ? fixtureSnapshot() : null); setError(false);
    setTarget(mode === 'offline_fixture' ? 'fixture-local-api' : null);
    setIncident(mode === 'offline_fixture' ? 'fixture-incident-01' : null);
    setEvent(null); setBrowsing(false);
  }, [active, mode]);
  useEffect(() => {
    if (!active) return;
    setEvent(current => data?.incidents.find(item => requestedTrace ? item.trace_id === requestedTrace : item.id === incidentId)?.events.some(event => event.id === current) ? current : null);
    if (new URLSearchParams(route.href.split('?')[1] ?? '').has('knowledge')) setTab('memory');
  }, [active, route.href]);
  useEffect(() => {
    if (!active) return;
    if (mode === 'offline_fixture') { setData(fixtureSnapshot()); setLoading(false); return; }
    const controller = new AbortController();
    let busy = false;
    const refresh = async () => {
      if (busy || document.hidden) return;
      busy = true;
      try {
        const value = await readWorkbench(controller.signal);
        if (!controller.signal.aborted) { setData(value); setLoadedHref(route.href); setError(false); setTarget(current => requestedTrace ? value.incidents.find(item => item.trace_id === requestedTrace)?.target_id ?? value.targets[0]?.id ?? null : value.targets.some(item => item.id === current) ? current : value.targets[0]?.id ?? null); }
      } catch { if (!controller.signal.aborted) { setData(null); setError(true); } }
      finally { busy = false; if (!controller.signal.aborted) setLoading(false); }
    };
    setLoading(true); void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    document.addEventListener('visibilitychange', refresh);
    return () => { controller.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', refresh); };
  }, [active, mode, revision, requestedTrace,route.href]);
  useEffect(() => { setIncident(current => requestedTrace ? data?.incidents.find(item => item.trace_id === requestedTrace && item.target_id === targetId)?.id ?? null : data?.incidents.some(item => item.id === current && item.target_id === targetId) ? current : incidentHistory(data?.incidents.filter(item => item.target_id === targetId) ?? [], '', false)[0]?.id ?? null); }, [data, targetId, requestedTrace]);
  const visibleData = data?.source === mode ? data : null;
  const requestedIncident = requestedTrace ? visibleData?.incidents.find(item => item.trace_id === requestedTrace) : undefined;
  const selectedTarget = requestedTrace ? requestedIncident?.target_id ?? null : targetId;
  const selectedIncident = requestedTrace ? requestedIncident?.id ?? null : incidentId;
  const selectIncident = (id: Incident['id']) => {
    const incident = visibleData?.incidents.find(item => item.id === id);
    if (!incident) return;
    setBrowsing(true); setTarget(incident.target_id); setIncident(id); setEvent(null);
    navigate(`/workbench?source=${mode}&trace=${encodeURIComponent(incident.trace_id)}`);
  };
  return <>{requestedTrace && visibleData && !requestedIncident && <p className="shell wb-trace-notice" role="status">{t("This recovery record is unavailable. No other incident has been selected.")}</p>}<WorkbenchView initialDirectory={false} integrationReady={loadedHref===route.href} mode={mode} data={visibleData} loading={loading} error={error} targetId={selectedTarget} incidentId={selectedIncident} eventId={eventId} tab={tab} active={active} following={!browsing && !requestedTrace} monitorControls={<MonitorControl targetId={selectedTarget} active={active && mode === 'real'} onChanged={() => setRevision(value => value + 1)} />}
    onMode={value => navigate(`/workbench?source=${value}`)}
    onRefresh={() => { setError(false); setRevision(value => value + 1); }} onTarget={id => { setBrowsing(true); setTarget(id); setEvent(null); navigate(`/workbench?source=${mode}`); }} onIncident={selectIncident} onEvent={id => {setBrowsing(true); setEvent(id);}} onTab={value => {setBrowsing(true); setTab(value);}} />
    {mode === 'real' && researchLoopAvailable && <div className="shell wb-run-shell"><RunControl active={active} /></div>}</>;
}
