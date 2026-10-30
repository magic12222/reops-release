import { t, useLocale, getLocale } from '../i18n';
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, Network, Pause, Play, RotateCcw, Search, SkipForward } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import type { Snapshot } from './contract';
import { evidencePath, kindLabels, knowledgeGraph, neighborhood } from './knowledge';
import { atlasPositions, globalKnowledgeGraph, incidentKnowledgeGraph, integrationRank, integrationStages, savedExperienceEvent, savedExperiences, starterKnowledge, unlearnedExecutionRecords } from './knowledgeAtlas';
import { readKnowledgeSpeed, rememberKnowledgeSpeed, takeKnowledgeJourney } from './knowledgeJourney';
import { KnowledgeSpeedControl } from './KnowledgeSpeedControl';
import { eventFact, eventLabel, recoveryMethod } from './incidentPresentation';
import { workbenchEdgeRoute, workbenchGraphLayout, workbenchNode, workbenchNodeLines } from './workbenchGraphLayout';
import './KnowledgeExplorer.css';
import {knowledgeText} from './knowledgeText';
import {useVisibleReading} from './useVisibleReading';
import {knowledgeUpdateGraph} from './knowledgeUpdate';
import {useGraphPan} from './useGraphPan';

const short = (value: string, limit = 24) => value.length > limit ? value.slice(0, limit - 1) + '…' : value;
const nodeLines = (value: string) => {
  const limit = /[\u3400-\u9fff]/.test(value) ? 13 : 24;
  if (value.length <= limit) return [value];
  let split = value.lastIndexOf(' ', limit);
  if (split < limit / 2) split = limit;
  return [value.slice(0, split), short(value.slice(split).trim(), limit)];
};
type Playback = { id: string; step: number; playing: boolean; mode: 'live' | 'replay' };
export function KnowledgeExplorer({ data, targetId, incidentId, onIncident, onEvent, active = true, integrationReady = true, autoIntegrate=true, retrievalExperienceId,updateIncidentId,initiallyUnselected=false,initialScope,journey,onJourneyComplete,workbench=false }: {
  data: Snapshot; targetId: string; incidentId: string | null; active?: boolean; integrationReady?: boolean; autoIntegrate?:boolean;
  onIncident: (id: string) => void; onEvent: (incident: string, event: string) => void; retrievalExperienceId?:string;updateIncidentId?:string;initiallyUnselected?:boolean;initialScope?:'all'|'run'|'experience';journey?:'lookup'|'update';onJourneyComplete?:()=>void; workbench?:boolean;
}) {
  useLocale();
  const [scope, setScope] = useState<'all' | 'run' | 'experience'>(() => initialScope??(updateIncidentId||typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('knowledge') ? 'all' : incidentId ? 'run' : 'all'));
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [targetFilter, setTargetFilter] = useState('');
  const [chosen, setChosen] = useState<string | null>(null);
  const [nodeId, setNodeId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [depth, setDepth] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [view, setView] = useState<'graph' | 'list'>('graph');
  const [pathStart, setPathStart] = useState<string | null>(null);
  const [pathOnly, setPathOnly] = useState(false);
  const [playback, setPlayback] = useState<Playback | null>(null);
  const [speed, setSpeed] = useState(readKnowledgeSpeed);
  const [recording, setRecording] = useState(() => typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('knowledge') === 'record');
  const reduceMotion = useReducedMotion();
  const saved = useMemo(() => savedExperiences(data), [data]);
  useEffect(()=>{
    if(journey||!active||!retrievalExperienceId||!data.experiences.some(item=>item.id===retrievalExperienceId&&item.target_id===targetId))return;
    setChosen(retrievalExperienceId);setScope('experience');setNodeId(`experience:${retrievalExperienceId}`);setDepth(0);setPlayback(null);
  },[active,retrievalExperienceId,targetId,journey]);
  const saveKey = (id: string) => `${data.source}:${id}:${savedExperienceEvent(data, data.experiences.find(item => item.id === id)!)?.id}`;
  // Baseline existing records on mount. Refresh never replays historical saves.
  const seen = useRef(new Set(saved.map(item => saveKey(item.id))));
  const queue = useRef<string[]>([]);
  const marker = `kg-arrow-${useId().replace(/:/g, '')}`;
  const viewOptionsId = `kg-options-${useId().replace(/:/g, '')}`;
  const section = useRef<HTMLElement>(null);
  const canvas=useRef<HTMLDivElement>(null);
  useGraphPan(canvas,active&&view==='graph'&&zoom>0);
  const [journeyStep,setJourneyStep]=useState(0);
  const journeyWasActive=useRef(false);
  useLayoutEffect(()=>{if(active&&journey&&!journeyWasActive.current)setJourneyStep(0);journeyWasActive.current=active&&!!journey;},[active,journey]);
  useVisibleReading(section,`graph:${incidentId}:${journey}:${journeyStep}`,active&&!!journey&&journeyStep<6,1300,()=>{setJourneyStep(value=>value+1);if(journeyStep===5)onJourneyComplete?.();});
  const onscreen = useRef(true);
  useEffect(() => {
    if (!section.current || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(([entry]) => { onscreen.current = entry.isIntersecting; });
    observer.observe(section.current); return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    if(!autoIntegrate){saved.forEach(item=>seen.current.add(saveKey(item.id)));queue.current=[];setPlayback(null);return;}
    const params = new URLSearchParams(window.location.search);
    if (active && integrationReady && incidentId && data.incidents.find(item => item.id === incidentId)?.trace_id === params.get('trace')) {
      const request = takeKnowledgeJourney(data, params.get('integration'));
      if (request) {
        seen.current.add(saveKey(request.experienceId)); queue.current = queue.current.filter(id => id !== request.experienceId);
        setChosen(request.experienceId); setScope('all'); setRecording(true); setQuery(''); setStatus('all'); setTargetFilter(''); setDepth(0); setPathOnly(false); setPathStart(null); setExpanded(false); setNodeId(null); setView('graph');
        setPlayback({ id: request.experienceId, step: -1, playing: true, mode: 'live' });
        return;
      }
    }
    for (const item of saved) {
      const key = saveKey(item.id);
      if (!seen.current.has(key)) { seen.current.add(key); queue.current.push(item.id); }
    }
    if (active && !playback && queue.current.length) {
      const id = queue.current.shift()!;
      setChosen(id); setScope('all'); setQuery(''); setStatus('all'); setTargetFilter(''); setDepth(0); setPathOnly(false); setPathStart(null); setExpanded(false); setNodeId(null); setView('graph');
      setPlayback({ id, step: -1, playing: true, mode: 'live' });
    }
  }, [saved, active, playback, integrationReady, incidentId, autoIntegrate]);
  useEffect(() => {
    if (!active || playback?.step !== 5 || !queue.current.length) return;
    const timer = window.setTimeout(() => setPlayback(null), 3200);
    return () => window.clearTimeout(timer);
  }, [active, playback]);
  useEffect(() => {
    if (!active || !playback?.playing || playback.step >= 5) return;
    const timer = window.setInterval(() => {
      if (document.hidden || !onscreen.current) return;
      setPlayback(current => current ? { ...current, step: Math.min(5, current.step + 1), playing: current.step < 4 } : current);
    }, playback.step < 0 ? speed * 1.8 : speed);
    return () => window.clearInterval(timer);
  }, [active, playback?.playing, playback?.step, speed]);
  const resetFocus = () => { setNodeId(null); setDepth(0); setPathStart(null); setPathOnly(false); };
  useEffect(() => { if(workbench) resetFocus(); }, [workbench,incidentId,targetId]);
  const stop = () => { queue.current = []; setPlayback(null); resetFocus(); };
  const records = data.experiences.filter(item => scope === 'all' ? (!targetFilter || item.target_id === targetFilter) : item.target_id === targetId);
  const incident = data.incidents.find(item => item.id === incidentId);
  const filtered = records.filter(item => (status === 'all' || item.status === status)
    && (scope !== 'run' || item.incident_id === incidentId || incident?.experience_ids.includes(item.id))
    && [item.id, item.title, item.symptom, item.root_cause, item.action, ...item.conditions].join(' ').toLowerCase().includes(query.toLowerCase()));
  const experience = filtered.find(item => item.id === chosen) ?? filtered.find(item => item.incident_id === incidentId) ?? filtered.at(-1);
  const playbackExperience = saved.find(item => item.id === playback?.id);
  const updateIncident=data.incidents.find(item=>item.id===updateIncidentId);
  const executionRecords=unlearnedExecutionRecords(data,query,targetFilter,status);
  let graph = scope === 'all' && updateIncident ? knowledgeUpdateGraph(data,updateIncident,filtered,expanded,query,executionRecords) : scope === 'all' ? globalKnowledgeGraph(data, filtered.filter(item => !queue.current.includes(item.id)), expanded, initiallyUnselected?undefined:playbackExperience?.id ?? experience?.id, query,executionRecords)
    : scope === 'run' && incident ? incidentKnowledgeGraph(data, incident, expanded)
    : experience ? knowledgeGraph(data, experience, expanded) : { nodes: [], edges: [], omitted: 0 };
  if(journey==='lookup'&&incident){
    const source=data.experiences.find(item=>item.id===retrievalExperienceId);
    const history=source?knowledgeGraph(data,source,expanded):{nodes:[],edges:[],omitted:0};
    const root=incidentKnowledgeGraph(data,{...incident,events:[],experience_ids:[],model_calls:[]},false).nodes.find(node=>node.id===`incident:${incident.id}`)!;
    const library=globalKnowledgeGraph(data,source?[source]:[],false,source?.id);
    const unique=new Map([...library.nodes,...history.nodes.map(node=>({...node,provenance:'recorded' as const})),root].map(node=>[node.id,node]));
    graph={nodes:[...unique.values()],edges:[...library.edges,...history.edges].filter((edge,index,all)=>all.findIndex(other=>other.from===edge.from&&other.to===edge.to)===index),omitted:history.omitted};
  }
  const rank=(node:typeof graph.nodes[number])=>journey==='lookup'?(node.id===`incident:${incidentId}`?0:node.kind==='incident'?4:integrationRank(node)):integrationRank(node);
  const journeyIds=new Set(graph.nodes.filter(node=>journey==='lookup'||node.incidentId===updateIncidentId).map(node=>node.id));
  const animateIds = new Set(playbackExperience ? graph.nodes
    .filter(node => node.incidentId === playbackExperience.incident_id).map(node => node.id) : []);
  const stagedNodes = graph.nodes.filter(node => (!journey||!journeyIds.has(node.id)||rank(node)<=Math.min(5,journeyStep))&&(!playback || !animateIds.has(node.id) || integrationRank(node) <= playback.step));
  const selected = initiallyUnselected&&!nodeId&&!playback?undefined:stagedNodes.find(node => node.id === nodeId)
    ?? (playback ? stagedNodes.findLast(node => animateIds.has(node.id) && integrationRank(node) <= playback.step) : undefined)
    ?? stagedNodes.find(node => !!updateIncidentId&&node.id===`incident:${updateIncidentId}`)
    ?? stagedNodes.find(node => node.id === `experience:${experience?.id}`) ?? stagedNodes[0];
  const path = pathStart && selected ? evidencePath(graph, pathStart, selected.id) : [];
  const local = pathOnly && path.length ? new Set(path) : selected && depth ? neighborhood(graph, selected.id, depth) : new Set(stagedNodes.map(node => node.id));
  const nodes = stagedNodes.filter(node => local.has(node.id));
  const ids = new Set(nodes.map(node => node.id));
  const edges = graph.edges.filter(edge => ids.has(edge.from) && ids.has(edge.to));
  const atlas = atlasPositions(graph);
  // Give repeated source events their own lane; keep every node and association.
  const columns = [0, 1, 2, 3].map(column => graph.nodes.filter(node => (scope === 'run' && node.eventId ? 3 : node.column) === column));
  const workbenchLayout = workbench && scope !== 'all' ? workbenchGraphLayout(graph, scope === 'run') : null;
  const related = selected ? neighborhood(graph, selected.id, 1) : new Set(nodes.map(node=>node.id));
  path.forEach(id=>related.add(id));
  const height = workbenchLayout?.height ?? (scope === 'all' ? atlas.height : Math.max(320, ...columns.map(column => column.length * 76 + 48)));
  const width = workbenchLayout?.width ?? (scope === 'all' ? 1120 : 1000);
  const positions = workbenchLayout?.positions ?? (scope === 'all' ? atlas.positions : new Map(columns.flatMap((column, index) => column.map((node, row) => [node.id, { x: 120 + index * 250, y: (height - column.length * 76) / 2 + row * 76 + 38 }] as const))));
  const options = filtered.slice(0, 200);
  const chooseNode = (id: string) => {
    setNodeId(id);
    if (!workbench || view !== 'graph') return;
    window.requestAnimationFrame(() => {
      const canvas = section.current?.querySelector<HTMLElement>('.kg-canvas');
      const node = [...(canvas?.querySelectorAll<SVGGElement>('.kg-node') ?? [])].find(item => item.dataset.nodeId === id);
      if (!canvas || !node || node.getAttribute('aria-pressed') !== 'true') return;
      const frame=canvas.getBoundingClientRect(), box=node.getBoundingClientRect();
      canvas.scrollBy({left:box.left<frame.left?box.left-frame.left-12:box.right>frame.right?box.right-frame.right+12:0,
        top:box.top<frame.top?box.top-frame.top-12:box.bottom>frame.bottom?box.bottom-frame.bottom+12:0,behavior:'instant'});
    });
  };
  const resetWorkbenchView = () => { resetFocus(); setZoom(1); section.current?.querySelector('.kg-canvas')?.scrollTo({left:0,top:0,behavior:'instant'}); };
  if (experience && !options.some(item => item.id === experience.id)) options.splice(0, 1, experience);
  const replay = () => {
    const item = experience && saved.some(savedItem => savedItem.id === experience.id) ? experience : saved.at(-1);
    if (!item) return;
    queue.current = []; setScope('all'); setChosen(item.id); setQuery(''); setStatus('all'); setTargetFilter(''); resetFocus(); setExpanded(false); setView('graph');
    setPlayback({ id: item.id, step: -1, playing: true, mode: 'replay' });
  };
  const selectedExperience = data.experiences.find(item => item.id === selected?.record) ?? data.experiences.find(item => item.incident_id === selected?.incidentId) ?? (selected?.provenance !== 'curated'&&(!selected?.incidentId||experience?.incident_id===selected.incidentId) ? experience : undefined);
  const selectedOrigin = data.incidents.find(item => item.id === selected?.incidentId);
  const selectedEvent = selectedOrigin?.events.find(item => item.id === selected?.eventId);
  const relationships = graph.edges.filter(edge => edge.from === selected?.id || edge.to === selected?.id)
    .sort((a,b) => {
      const priority = (edge: typeof graph.edges[number]) => {
        const other = graph.nodes.find(node => node.id === (edge.from === selected?.id ? edge.to : edge.from));
        return other?.kind === 'incident' ? 0 : other?.kind === 'verification' ? 1 : other?.eventId ? 2 : 3;
      };
      return priority(a) - priority(b);
    });
  const nodeLabel = (node: typeof graph.nodes[number]) => node.provenance === 'curated' ? t(node.label) : node.label;
  const renderRelationship = (edge: typeof graph.edges[number]) => {
    const other = graph.nodes.find(node => node.id === (edge.from === selected?.id ? edge.to : edge.from))!;
    return <li key={`${edge.from}:${edge.to}`}><button onClick={() => { setDepth(0); chooseNode(other.id); }}><span>{edge.from === selected?.id ? '→' : '←'} {t(edge.label)}</span>{displayLabel(other)}</button></li>;
  };
  const displayLabel = (node: typeof graph.nodes[number]) => {
    const origin = data.incidents.find(item => item.id === node.incidentId);
    const stamp = origin ? new Intl.DateTimeFormat(getLocale(), { timeZone: 'Asia/Shanghai', hour12: false, year:'numeric',month:'2-digit',day:'2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(origin.started_at)) : '';
    if (node.kind === 'experience' && node.provenance === 'recorded') return t('Recovery · {0}', stamp);
    const event = node.eventId ? origin?.events.find(item => item.id === node.eventId) : undefined;
    if (event?.stage === 'verification') return eventLabel(event);
    const labels: Record<string, string> = {
      'Automatic dependency recovery': 'Dependency recovery incident',
      'Two stopped-database business observations': 'Database stopped; business unavailable',
      'Dependent exit evidence recorded': 'Database exit with dependent exit',
      'Dependent application exit confirmed': 'Dependent exit evidence confirmed',
      'Business verification · passed': 'Business checks passed',
      'start_service(postgres) → SELECT 1 → conditional start_service(api) → two fresh checks': 'Database → SQL ready → application',
    };
    return Object.prototype.hasOwnProperty.call(labels, node.label) ? t(labels[node.label]) : nodeLabel(node);
  };
  const revealed=nodes.map(node=>positions.get(node.id)!).filter(Boolean);
  const journeyCamera=journey&&journeyStep<5&&revealed.length?`${Math.min(...revealed.map(p=>p.x))-125} ${Math.min(...revealed.map(p=>p.y))-65} ${Math.max(300,Math.max(...revealed.map(p=>p.x))-Math.min(...revealed.map(p=>p.x))+250)} ${Math.max(220,Math.max(...revealed.map(p=>p.y))-Math.min(...revealed.map(p=>p.y))+130)}`:undefined;
  const camera = journeyCamera??(recording && playback && playback.step >= 0 && playback.step < 5 ? `0 475 ${width} 260` : `0 0 ${width} ${height}`);
  return <section ref={section} className={`kg ${workbench ? 'kg-workbench' : ''} ${scope === 'all' ? 'kg-atlas' : ''} ${recording ? 'kg-recording' : ''} ${playback && playback.step >= 0 && playback.step < 5 ? 'kg-in-progress' : ''}`} aria-label={t("Experience knowledge explorer")}>

    <header className="kg-heading"><Network size={18} /><div><h3>{t("ReOps Knowledge")}</h3><p>{t("Recovery conclusions linked to their source evidence.")}</p></div><button className="kg-recording-toggle" aria-pressed={recording} onClick={() => setRecording(!recording)}>{recording ? t('Exit recording view') : t('Recording view')}</button></header>
    <div className="kg-overview"><div><strong>{starterKnowledge.length}</strong><span>{t("Starter knowledge")}</span></div><div><strong>{scope === 'all' ? nodes.filter(node => node.kind === 'experience' && node.provenance === 'recorded').length : saved.length}</strong><span>{scope === 'all' ? t('Network experiences') : t('Saved experiences')} · {data.source === 'real' ? t('Local records') : t('Sample source')}</span></div><div><strong>{data.incidents.length}</strong><span>{t("Traceable incidents")}</span></div><KnowledgeSpeedControl value={speed} onChange={value=>{setSpeed(value);rememberKnowledgeSpeed(value);}}/><button onClick={replay} disabled={!saved.length}><Play size={14} />{t("Replay knowledge integration")}</button></div>
    <div className="kg-tools"><label>{t("Scope ")}<select aria-label={t("Knowledge scope")} value={scope} onChange={e => { stop(); setScope(e.target.value as typeof scope); }}><option value="all">{t("Global knowledge graph")}</option><option value="run" disabled={!incident}>{t("This incident graph")}</option><option value="experience" disabled={!records.length}>{t("Selected experience")}</option></select></label>
      {scope === 'all' && <label>{t("Target ")}<select aria-label={t("Knowledge target")} value={targetFilter} onChange={e => { stop(); setTargetFilter(e.target.value); }}><option value="">{t("All targets")}</option>{data.targets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
      <label className="kg-search"><Search size={14} /><input aria-label={t("Search recovery knowledge")} placeholder={t("Search symptoms, causes, actions…")} value={query} onChange={e => { stop(); setQuery(e.target.value); }} /></label>
      <select aria-label={t("Experience status")} value={status} onChange={e => { stop(); setStatus(e.target.value); }}><option value="all">{t("All statuses")}</option>{['verified', 'unverified', 'failed', 'retired'].map(value => <option key={value}>{t(value)}</option>)}</select>
      <div className="kg-switch" aria-label={t("Knowledge display")}><button aria-pressed={view === 'graph'} onClick={() => setView('graph')}>{t("Graph")}</button><button aria-pressed={view === 'list'} onClick={() => setView('list')}>{t("Records")}</button></div>
    </div>
    <div className="kg-record-select"><label>{t("Experience ")}<select aria-label={t("Selected experience")} value={experience?.id ?? ''} disabled={!options.length} onChange={e => { stop(); setChosen(e.target.value); setExpanded(false); }}>
      {!options.length && <option value="">{t("No matching saved record")}</option>}{options.map(item => <option key={item.id} value={item.id}>{item.title} · {item.id}</option>)}</select></label><span>{filtered.length}{t(" matches")}{filtered.length > 200 ? t(' · up to 200 shown; refine search') : ''}</span></div>
    {journey&&<div className="kg-journey" role="status" data-journey-step={journeyStep}><strong>{journey==='lookup' ? t(['Current incident','Reveal historical symptoms','Trace diagnostic evidence','Check recovery conditions','Verify the original source',retrievalExperienceId?'Locate the matched experience in the library':'No matching source available in this graph','Knowledge context ready'][journeyStep]) : t([...integrationStages,'Knowledge graph updated'][journeyStep])}</strong><span>{Math.min(6,journeyStep+1)} / 6</span></div>}
    {playback && <div className="kg-integration" aria-label={t("Experience integration playback")}><div className="kg-integration-top"><span>{playback.mode === 'live' ? t('RECORDED · EXPERIENCE SAVED') : t('REPLAY · SAVED INTEGRATION')}</span><strong role="status">{playback.step < 0 ? t('Global knowledge before this experience') : t(integrationStages[playback.step])}</strong><span>{t(playback.step + 1)} / 6</span></div><ol>{integrationStages.map((label, index) => <li key={label} className={index <= playback.step ? 'reached' : ''}><button aria-label={t("Integration step {0}: {1}", t(index + 1), t(label))} aria-current={index === playback.step ? 'step' : undefined} onClick={() => setPlayback({ ...playback, step: index, playing: false })}><i>{t(index + 1)}</i><span>{t(label)}</span></button></li>)}</ol><div className="kg-playback-tools"><button disabled={playback.step === 5} onClick={() => setPlayback({ ...playback, playing: !playback.playing })}>{playback.playing ? <Pause size={13} /> : <Play size={13} />}{playback.playing ? t('Pause') : t('Play')}</button><button disabled={playback.step === 5} onClick={() => setPlayback({ ...playback, step: playback.step + 1, playing: false })}><SkipForward size={13} />{t("Next")}</button><button onClick={replay}><RotateCcw size={13} />{t("Replay")}</button><button onClick={stop}>{t("End replay")}</button><small>{t(playbackExperience?.id)}</small></div></div>}
    {scope !== 'all' && !graph.nodes.length ? <div className="kg-empty"><h4>{t("No recovery experience recorded")}</h4><p>{data.b_status === 'not_connected' ? t('The B experience feed is not connected for this workspace.') : t('No matching experience.')}</p></div> : <div className="kg-workspace">
      <div className="kg-canvas-area">{workbench ? <>
        <div className="kg-canvas-tools kg-workbench-tools"><span>{nodes.length}{t(" nodes · ")}{edges.length}{t(" links")}</span><div className="kg-primary-tools" aria-label={t("Graph exploration")}><button disabled={!selected} aria-pressed={depth>0} title={t("Show the selected node and its recorded neighbors")} onClick={()=>{setDepth(depth?0:1);setPathOnly(false);}}>{t("Focus")}</button><button disabled={!selected} aria-pressed={!!selected&&pathStart===selected.id} title={t("Use the selected node as the start of an evidence path")} onClick={()=>{setPathStart(selected?.id??null);setPathOnly(false);}}>{t("Path start")}</button><button disabled={!pathStart||path.length<2} aria-pressed={pathOnly} title={t("Show the recorded path to the selected destination")} onClick={()=>{setPathOnly(!pathOnly);setDepth(0);}}>{t("Trace path")}</button><button title={t("Clear focus and path selection; fit the graph")} onClick={resetWorkbenchView}>{t("Reset view")}</button></div></div>
        <div className="kg-secondary-tools"><details id={viewOptionsId}><summary>{t("View options")}{expanded ? t(' · expanded') : ''}{depth ? t(" · {0} hops", t(depth)) : ''}</summary><div><button disabled={!selected||!depth||depth>=4} onClick={()=>setDepth(Math.min(4,depth+1))}>{t("Expand neighbors")}</button><button aria-pressed={expanded} onClick={()=>{stop();setExpanded(!expanded);}}>{expanded ? t('Collapse details') : t('More details')}</button><label>{t("Zoom ")}<select aria-label={t("Graph zoom")} disabled={view!=='graph'} value={zoom} onChange={e=>setZoom(Number(e.target.value))}><option value={0}>{t("Fit")}</option><option value={0.75}>75%</option><option value={1}>100%</option><option value={1.25}>125%</option></select></label></div></details><span>{depth ? t("Showing {0}-hop neighbors", t(depth)) : t('Select a node to highlight its evidence links')}</span></div>
        {pathStart && <p className="kg-path-status" role="status">{selected?.id===pathStart ? t('Start set. Select a destination node.') : path.length>1 ? t("{0} recorded links connect the selected nodes.", t(path.length-1)) : t('No recorded path to this node.')}<button onClick={()=>{setPathStart(null);setPathOnly(false);}}>{t("Clear path")}</button></p>}
      </> : <><div className="kg-canvas-tools"><span>{nodes.length}{t(" nodes · ")}{edges.length}{t(" links")}</span><button disabled={!selected} onClick={() => { setPathStart(selected?.id ?? null); setPathOnly(false); }}>{t("Path start")}</button><button disabled={!pathStart || !path.length} aria-pressed={pathOnly} onClick={() => { setPathOnly(!pathOnly); setDepth(0); }}>{t("Trace path")}</button><button aria-pressed={depth === 1} onClick={() => setDepth(depth === 1 ? 0 : 1)}>{t("Focus")}</button><button disabled={!depth} onClick={() => setDepth(Math.min(4, depth + 1))}>{t("Expand neighbors")}</button><button aria-pressed={expanded} onClick={() => { stop(); setExpanded(!expanded); }}>{expanded ? t('Collapse details') : t('More details')}</button><button onClick={() => { resetFocus(); setZoom(1); }}>{t("Reset view")}</button><label>{t("Zoom ")}<select aria-label={t("Graph zoom")} value={zoom} onChange={e => setZoom(Number(e.target.value))}><option value={0}>{t("Fit")}</option><option value={0.75}>75%</option><option value={1}>100%</option><option value={1.25}>125%</option></select></label></div>
        {pathStart && <p className="kg-path-status" role="status">{t("Path start: ")}{graph.nodes.find(node => node.id === pathStart)?.label}{t(". Select another node, then Trace path.")}</p>}
</>}
        {scope === 'all' && <p className="kg-pan-hint">{t("Global knowledge above; the selected experience and its evidence below. Select a node to inspect its source.")}</p>}
        {view === 'graph' ? <div ref={canvas} className="kg-canvas" data-fit={zoom===0} data-reading-focus={!!journey} tabIndex={0} aria-label={t("Knowledge graph. Tab to select nodes. Scroll to explore. Escape clears focus.")} onKeyDown={e => { if (e.key === 'Escape') resetFocus(); }}>
          <motion.svg width={zoom === 0 ? '100%' : width * zoom} height={journey&&journeyStep<6?Math.min(500,height):zoom === 0 ? 520 : height * zoom} animate={{ viewBox: camera }} initial={false} transition={{ duration: reduceMotion ? 0 : 1.25, ease: 'easeInOut' }} role="group" aria-label={t("Directed evidence relationships")}>
            <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
            {scope === 'all' ? <><text x="560" y="30" textAnchor="middle" className="kg-column-label">{t("GLOBAL KNOWLEDGE / CONTINUOUS LEARNING")}</text><path className="kg-divider" d="M 25 425 H 1095" /><text x="30" y="450" className="kg-column-label">{t("INCIDENT EVIDENCE / SELECTED EXPERIENCE")}</text></> : (scope === 'run' ? ['Incident', 'Saved experience', 'Recovery knowledge', 'Source evidence'] : ['Origin & source', 'Saved experience', 'Knowledge & evidence', 'Persistence & reuse']).map((label, index) => <text key={label} x={workbenchLayout ? [110,350,590,850][index] : 120 + index * 250} y={26} textAnchor="middle" className="kg-column-label">{t(label)}</text>)}
            {edges.map(edge => {
              const a = positions.get(edge.from)!; const b = positions.get(edge.to)!;
              const emerging = !!journey&&(journeyIds.has(edge.from)||journeyIds.has(edge.to))||playback && (animateIds.has(edge.from) || animateIds.has(edge.to));
              const connected = selected?.id === edge.from || selected?.id === edge.to;
              const inPath = path.length>1 && path.some((id,index)=>index>0 && ((path[index-1]===edge.from&&id===edge.to)||(path[index-1]===edge.to&&id===edge.from)));
              const route = workbenchLayout ? workbenchEdgeRoute(edge,graph,workbenchLayout) : null;
              const showLabel = workbench ? inPath || connected && (selected?.kind!=='experience' || ['produced','origin checked','reused by','referenced by'].includes(edge.label)) : scope !== 'all' || emerging || connected;
              const dx = b.x - a.x, dy = b.y - a.y;
              const vertical = Math.abs(dy) > Math.abs(dx);
              const x1 = a.x + (vertical ? 0 : Math.sign(dx) * 96), y1 = a.y + (vertical ? Math.sign(dy) * 28 : 0);
              const x2 = b.x - (vertical ? 0 : Math.sign(dx) * 96), y2 = b.y - (vertical ? Math.sign(dy) * 28 : 0);
              return <g key={`${edge.from}:${edge.to}`} className={`kg-edge ${connected || workbench && inPath ? 'connected' : ''} ${workbench&&!connected&&!inPath?'muted':''} ${emerging ? 'integrating' : ''}`}><title>{t("{0} · {1}", t(edge.label), edge.field)}</title><path markerEnd={`url(#${marker})`} d={route?.path ?? `M ${x1} ${y1} C ${x1} ${(y1 + y2) / 2}, ${x2} ${(y1 + y2) / 2}, ${x2} ${y2}`} />{showLabel && <text x={route?.label.x ?? (x1 + x2) / 2 + (vertical ? 35 : 0)} y={route?.label.y ?? (y1 + y2) / 2 - 6} textAnchor={route?.label.anchor ?? 'middle'}>{t(edge.label)}</text>}</g>;
            })}
            {nodes.map(node => {
              const p = positions.get(node.id)!; const emerging = !!journey&&journeyIds.has(node.id)||playback && animateIds.has(node.id);
              const current = (emerging && integrationRank(node) === playback?.step) || (playback?.step === 5 && node.id === `topic:${graph.nodes.find(item => item.id === `experience:${playback.id}`)?.topic}`);
              const label = displayLabel(node);
              const lines = node.kind==='experience'&&node.provenance==='recorded'&&label.includes(' · ')?[t('Recovery · {0}',label.split(' · ')[1].split(' ')[0]),label.split(' ').at(-1)!]:workbench?workbenchNodeLines(label):nodeLines(label);
              return <g key={node.id} data-node-id={node.id} data-current-run={!!updateIncidentId&&node.incidentId===updateIncidentId} role="button" tabIndex={0} aria-label={t("{0}: {1}", t(kindLabels[node.kind]), nodeLabel(node))} aria-pressed={selected?.id === node.id} className={`kg-node kg-${node.kind} ${selected?.id === node.id ? 'selected' : ''} ${workbench&&!related.has(node.id)?'muted':''} ${emerging ? 'integrating' : ''} ${current ? 'arriving' : ''}`} transform={`translate(${p.x - 96},${p.y - (workbenchLayout?workbenchNode.height/2:28)})`} onClick={() => chooseNode(node.id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); chooseNode(node.id); } }}><title>{nodeLabel(node)}</title><rect width="192" height={workbenchLayout?workbenchNode.height:56} rx={workbenchLayout?6:8} /><text x="12" y="14" className="kg-node-kind">{t(kindLabels[node.kind])}</text>{lines.map((line, index) => <text key={index} x="12" y={workbenchLayout ? lines.length===1?42:36+index*16 : lines.length === 1 ? 38 : 32 + index * 15}>{line}</text>)}</g>;
            })}
          </motion.svg>
        </div> : <div className="kg-node-list" aria-label={t("Knowledge records")}>{nodes.map(node => <button key={node.id} aria-pressed={selected?.id === node.id} onClick={() => chooseNode(node.id)}><span>{t(kindLabels[node.kind])}</span><strong>{nodeLabel(node)}</strong><small>{node.field}</small></button>)}</div>}
        <div className="kg-legend" aria-label={t("Graph legend")}>{[...new Set(nodes.map(node => node.kind))].map(kind => <span key={kind} className={`kg-${kind}`}><i />{t(kindLabels[kind])}</span>)}<span>{t("→ Directed relationship")}</span></div>
        <p className="kg-footnote">{graph.omitted > 0 && t('{0} properties outside this view. ', graph.omitted)}{scope === 'all' ? t('Starter knowledge and saved experiences share a network with inspectable topic associations.') : t('Nodes project this incident and trace. Complete states and original evidence remain available in details.')}{t(!filtered.length && scope === 'all' && ' No runtime experience matches these filters. Starter knowledge remains available.')}</p>
      </div>
      <aside key={selected?.id} className="kg-detail" aria-label={t("Knowledge node details")}>{selected ? <><span className="kg-detail-kind">{t(kindLabels[selected.kind])}</span><h4>{displayLabel(selected)}</h4>
        {workbench && selected.kind==='incident' && selectedOrigin ? <dl className="kg-conclusions"><dt>{t("Recovery / diagnosis")}</dt><dd>{t(recoveryMethod(selectedOrigin))}</dd><dt>{t("Recorded result")}</dt><dd>{t(selectedOrigin.status)}</dd></dl> : selected.kind === 'experience' && selectedExperience ? <dl className="kg-conclusions"><dt>{t("Root cause")}</dt><dd>{short(selectedExperience.root_cause, 180) || t('Not recorded')}</dd><dt>{t("Recovery")}</dt><dd>{short(selectedExperience.action, 180) || t('Not recorded')}</dd><dt>{t("Knowledge status")}</dt><dd>{t(selectedExperience.status)}</dd></dl> : selected.kind === 'verification' && selectedOrigin ? selectedEvent && eventFact(selectedEvent)!==selectedEvent.title && <p className="kg-value">{eventFact(selectedEvent)}</p> : workbench&&selected.value===displayLabel(selected)?null : <p className="kg-value">{short(knowledgeText(selected).split('\n').slice(0, 3).join('\n'), 220)}</p>}
        {selectedOrigin && <p className="kg-origin-check">{t("Recorded verification · ")}<strong>{t(selectedOrigin.verification.status)}</strong> · {selectedOrigin.verification.checks.length}{t(" checks")}</p>}
        <p className="kg-provenance">{selected.provenance === 'curated' ? t('ReOps starter library · curated') : data.source === 'real' ? t('Local incident record') : t('Sample incident record')}</p>
        {selected.incidentId && <button onClick={() => { setRecording(false); selected.eventId ? onEvent(selected.incidentId, selected.eventId) : onIncident(selected.incidentId); }}>{t("View source incident ")}<ArrowUpRight size={13} /></button>}
        {!!relationships.length && <><h5>{t("Evidence links · ")}{relationships.length}</h5><ul>{t(relationships.slice(0, 2).map(renderRelationship))}</ul>{relationships.length > 2 && <details><summary>{t("More relationships · ")}{t(relationships.length - 2)}</summary><ul>{t(relationships.slice(2).map(renderRelationship))}</ul></details>}</>}
        <details className="kg-complete-record"><summary>{t("Conditions & complete record")}</summary><dl><dt>{t("Record")}</dt><dd>{selected.record}</dd><dt>{t("Source field")}</dt><dd>{selected.field}</dd>{selectedOrigin && <><dt>{t("Trace")}</dt><dd>{selectedOrigin.trace_id}</dd></>}</dl>{workbench&&<><h5>{t("Original source text")}</h5><p className="kg-original-value">{selected.value}</p></>}<h5>{t("Selected node")}</h5><pre>{JSON.stringify(selected, null, 2)}</pre>{selectedExperience && <><h5>{t("Complete experience")}</h5><pre>{JSON.stringify(selectedExperience, null, 2)}</pre></>}{selectedOrigin && <><h5>{t("Recorded checks")}</h5><ul>{selectedOrigin.verification.checks.map((check,index) => <li key={index}>{check}</li>)}</ul></>}</details></>:<p className="kg-detail-prompt">{t("Select a node to inspect its details and source.")}</p>}</aside>
    </div>}
  </section>;
}
