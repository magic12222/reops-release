import { t, useLocale, getLocale } from '../i18n';
import { useState } from 'react';
import { Activity, Box, Check, Cpu, Monitor, RefreshCw, Search, Server, ShieldCheck } from 'lucide-react';
import type { LocalSoftware, SoftwareCatalog } from './softwareCatalog';
import './SoftwareDirectory.css';

const kinds = {process:'Process group',service:'Windows service',container:'Container'};
const icons = {process:Cpu,service:Server,container:Box};
const memory = (bytes: number | null) => bytes === null ? 'Not exposed' : `${(bytes / 1024 / 1024).toLocaleString(getLocale(),{maximumFractionDigits:0})} MB`;
const time = (value: string | null) => value ? new Date(value).toLocaleTimeString(getLocale(),{timeZone:'Asia/Shanghai',hour12:false}) : 'Awaiting discovery';
type Filter = 'all'|'apps'|'process'|'service'|'container'|'watching';
export function SoftwareDirectory({ data,error,pending,onRefresh,onWatch,onBusiness,businessWatching=false,businessPending=false,businessError='' }: {
  data: SoftwareCatalog | null; error: string; pending: boolean; onRefresh:()=>void; onWatch:(id:string,watching:boolean)=>void;
  onBusiness?:()=>void; businessWatching?:boolean; businessPending?:boolean; businessError?:string;
}) {
  useLocale();
  const [query,setQuery] = useState('');
  const [filter,setFilter] = useState<Filter>('all');
  const [limit,setLimit] = useState(50);
  const [selected,setSelected] = useState<string | null>(null);
  const [order,setOrder] = useState<'priority'|'name'>('priority');
  const watches = new Map(data?.watches.map(item=>[item.record.id,item]));
  const records = filter === 'watching' ? data?.watches.map(item=>item.record) ?? [] : data?.records ?? [];
  const priority = (item: LocalSoftware) => watches.has(item.id) ? 0 : onBusiness && item.project==='reops-vikunja-demo' ? 1 : item.kind==='container' ? 2 : item.windowed ? 3 : item.kind==='service' ? 4 : 5;
  const matching = records.filter(item => (filter === 'all' || filter === 'watching' || filter === 'apps' && item.windowed || filter === item.kind)
    && [item.name,item.kind,item.project,item.service,item.image,...item.pids,...item.ports].join(' ').toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a,b)=>(order==='priority'?priority(a)-priority(b):0)||a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
  const counts = {all:data?.records.length??0,apps:data?.records.filter(item=>item.windowed).length??0,
    process:data?.records.filter(item=>item.kind==='process').length??0,service:data?.records.filter(item=>item.kind==='service').length??0,
    container:data?.records.filter(item=>item.kind==='container').length??0,watching:data?.watches.length??0};
  const current = data?.records.find(item=>item.id===selected) ?? watches.get(selected ?? '')?.record;
  const watched = current ? watches.get(current.id) : undefined;
  const ready = !!data && ['ready','partial'].includes(data.state);
  const select = (record: LocalSoftware) => setSelected(record.id);
  return <section className="software-directory" aria-label={t("Local software directory")}>
    <header className="software-heading"><div><span className="software-kicker">{t("DISCOVERY / THIS COMPUTER")}</span><h2>{t("Local software")}</h2><p>{t("Processes, Windows services and containers.")}</p></div><button onClick={onRefresh} aria-label={t("Refresh local software")}><RefreshCw size={14}/>{t("Refresh")}</button></header>
    <details className="software-scope"><summary><ShieldCheck size={14}/>{t("Basic monitors · running state only")}</summary><p>{t("Basic monitoring observes running state, ports and memory. Business health and recovery require a dedicated adapter.")}</p></details>
    {businessError&&<p role="alert" className="software-error">{t(businessError)}</p>}
    <div className="software-summary"><span><strong>{t(data?.records.length ?? '–')}</strong>{t(" detected entries")}</span><span><strong>{t(data?.watches.length ?? 0)}</strong>{t(" basic monitors")}</span><span><Activity size={12}/>{data ? t("{0} · {1}", t(data.state), t(time(data.generated_at))) : t('Connecting to discovery')}</span></div>
    {error && <p className="software-error" role="alert">{t(error)}{t(" Connected business targets remain available in the sidebar.")}</p>}
    {!data && !error && <div className="software-empty" role="status"><RefreshCw size={20}/><h3>{t("Loading local software")}</h3><p>{t("Waiting for the discovery snapshot.")}</p></div>}
    {data && ['disabled','starting','unavailable'].includes(data.state) && <div className="software-empty" role="status"><Monitor size={26}/><h3>{data.state === 'starting' ? t('Discovering local software') : data.state === 'disabled' ? t('Local discovery is not enabled on this service') : t('Discovery sources are unavailable')}</h3><p>{data.state === 'starting' ? t('The first system snapshot is being collected.') : t('The monitoring service needs to load local discovery. Existing business monitoring is separate.')}</p></div>}
    {data?.state === 'partial' && <p className="software-notice">{t("Some sources are unavailable: ")}{t(Object.entries(data.sources).filter(([,state])=>state!=='ready').map(([source])=>source==='ports'?'listener ports':kinds[source as keyof typeof kinds]).map(value=>t(value)).join(', '))}{t(". Missing sources are not treated as stopped software.")}</p>}
    {data?.state === 'stale' && <p className="software-error" role="status">{t("This snapshot is stale. Current running state is unknown until discovery updates.")}</p>}
    {(ready || data?.state==='stale') && <>
      <label className="software-search"><Search size={15}/><input type="search" aria-label={t("Search local software")} placeholder={t("Search names, ports, services or images…")} value={query} onChange={e=>{setQuery(e.target.value);setLimit(50);}} onKeyDown={e=>{if(e.key==='Escape'){setQuery('');e.currentTarget.blur();}}}/><kbd>/</kbd></label>
      <nav className="software-filters" aria-label={t("Software categories")}>{(['all','watching','container','apps','service','process'] as const).map(value=><button key={value} aria-pressed={filter===value} onClick={()=>{setFilter(value);setLimit(50);}}>{t(({all:'All software',apps:'Desktop apps',process:'Processes',service:'Services',container:'Containers',watching:'Monitoring'})[value])} <span>{t(counts[value])}</span></button>)}</nav>
      <div className="software-list-tools"><span>{matching.length}{t(" matches")}</span><label>{t("Sort ")}<select aria-label={t("Sort local software")} value={order} onChange={e=>{setOrder(e.target.value as typeof order);setLimit(50);}}><option value="priority">{t("Monitored & services first")}</option><option value="name">{t("Name A–Z")}</option></select></label>{(query||filter!=='all')&&<button onClick={()=>{setQuery('');setFilter('all');setLimit(50);}}>{t("Clear filters")}</button>}</div>
      <div className={`software-content ${current?'with-detail':''}`}>
        <div className="software-results"><div className="software-table-scroll"><table><thead><tr><th>{t("Software")}</th><th>{t("Signals")}</th><th>{t("Memory")}</th><th><span className="sr-only">{t("Basic monitor")}</span></th></tr></thead><tbody>{matching.slice(0,limit).map(item=>{
          const Icon=icons[item.kind]; const watch=watches.get(item.id);
          const business=!!onBusiness&&item.kind==='container'&&item.project==='reops-vikunja-demo'&&item.service==='app';
          const vikunja=item.kind==='container'&&item.project==='reops-vikunja-demo';
          const displayName=vikunja?(item.service==='app'?'Vikunja':item.service==='postgres'?t('Vikunja database'):item.name):item.name;
          return <tr key={item.id} data-selected={current?.id===item.id}><td><button className="software-name" aria-pressed={current?.id===item.id} onClick={()=>select(item)}><Icon size={17}/><span><strong>{displayName}</strong><small title={item.name}>{vikunja ? item.name : t(kinds[item.kind])}{item.instances>1 ? t(" · {0} instances", t(item.instances)) : ''}</small></span></button></td><td><span className={`software-liveness ${data.state==='stale'||watch?.alive===null?'unknown':watch?.alive===false?'absent':''}`}>{data.state==='stale'||watch?.alive===null ? t('Unknown') : watch?.alive===false ? t('Not detected') : t('Running')}</span>{(item.ports.length>0||data.sources.ports!=='ready')&&<small>{item.ports.length ? t("{0} {1}", item.kind==='container' ? t('Published TCP') : t('TCP'), item.ports.join(', ')) : t('Ports unavailable')}</small>}</td><td className="software-memory">{item.memory_bytes===null?<span className="software-unavailable" title={t("Working set is unavailable for this discovery source")} aria-label={t("Memory unavailable")}>—</span>:memory(item.memory_bytes)}</td><td><div className="software-actions">{business&&<button className="software-business" disabled={businessPending||!ready} onClick={onBusiness}>{businessWatching ? t('View business monitoring') : t('Enable business monitoring')}</button>}<button className={`software-watch ${business?'software-watch-compact':''}`} title={t("{0}: running state only", watch ? t('Stop basic monitoring') : t('Start basic monitoring'))} disabled={pending || !ready && !watch || watches.size>=64 && !watch} aria-label={t("{0} {1}", watch ? t('Stop basic monitor for') : t('Monitor'), item.name)} onClick={()=>{setSelected(item.id);onWatch(item.id,!watch);}}>{watch?<Check size={13}/>:<Activity size={13}/>}<span>{watch ? t('Basic monitoring') : t('Basic monitor')}</span></button></div></td></tr>;
        })}</tbody></table></div>
          {matching.length===0 && <div className="software-empty" role="status"><h3>{filter==='watching' ? t('No matching basic monitors') : t('No matching software')}</h3><p>{filter==='watching' ? t('Choose Monitor on a discovered item.') : t('Try another name or category.')}</p></div>}
          <footer><span>{t("Showing ")}{Math.min(limit,matching.length)}{t(" of ")}{matching.length}{t(" matches")}{data.omitted ? t(" · {0} additional records outside the collector limit", t(data.omitted)) : ''}</span>{matching.length>limit && <button onClick={()=>setLimit(value=>value+50)}>{t("Show 50 more")}</button>}</footer>
        </div>
        {current && <aside className="software-detail" aria-label={t("Selected software")}><header><span>{t(kinds[current.kind])}</span><button onClick={()=>setSelected(null)} aria-label={t("Close software details")}>{t("Close")}</button></header><h3>{current.name}</h3><p>{t("Basic observation only. No business health check or recovery permission is attached to this discovery.")}</p><dl><dt>{t("Observed at")}</dt><dd>{t(time(data.generated_at))}</dd><dt>{t("Instances")}</dt><dd>{t(current.instances)}</dd><dt>{t("Process IDs")}</dt><dd>{current.pids.join(', ') || t('Not exposed by container discovery')}</dd><dt>{t("Host listener ports")}</dt><dd>{current.ports.join(', ') || t('None exposed')}</dd><dt>{t("Working set")}</dt><dd>{t(memory(current.memory_bytes))}</dd>{current.image && <><dt>{t("Image")}</dt><dd>{current.image}</dd></>}{current.project && <><dt>{t("Compose project")}</dt><dd>{current.project}</dd></>}{current.service && <><dt>{t("Service")}</dt><dd>{current.service}</dd></>}</dl>
          {current.kind==='process' && <p>{t("Instances are grouped by process name. A name does not establish application ownership. Working set is summed across instances and can include shared pages.")}</p>}
          {watched && <div className="software-history"><h4>{t("Recent observations")}</h4><div aria-label={t("Basic availability history")}>{watched.history.map((sample,index)=><span key={index} className={sample.alive===true?'present':sample.alive===false?'absent':'unknown'} title={t("{0} · {1}", t(time(sample.timestamp)), sample.alive===true ? t('Running') : sample.alive===false ? t('Not detected') : t('Unknown'))} />)}</div><p>{t("Running · Not detected · Unknown")}</p><small>{t("Last seen ")}{t(time(watched.last_seen_at))}</small></div>}
          <p>{t("Basic monitors continue while the monitoring service runs. Selections reset after a service restart.")}</p></aside>}
      </div>
    </>}
  </section>;
}
