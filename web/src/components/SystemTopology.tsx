import { t, useLocale } from '../i18n';
import { useId, useState } from 'react';
import { Activity, Database, Layers, Radio, Server, Workflow } from 'lucide-react';
import { systemNodes, topologyEdges } from '../data/demoData';
import type { NodeId, SystemPhase } from '../types/system';
import { overviewStory, storyEdge, storyNode } from '../data/overviewStory';
import { heroEdgeKind, heroNeighbors, heroNodeDetail, heroNodeState } from '../data/heroSimulation';

const icons = { api: Server, redis: Layers, postgres: Database, worker: Workflow, monitor: Radio, agent: Activity };
const activePhases: SystemPhase[] = ['detect', 'locate', 'reason', 'decide', 'execute', 'verify'];
export function SystemTopology({ phase = 'healthy', compact = false, paused = false, narrative = false, heroDemo = false }: { phase?: SystemPhase; compact?: boolean; paused?: boolean; narrative?: boolean; heroDemo?: boolean }) {
  useLocale();
  const id = useId().replaceAll(':', '');
  const [selected, setSelected] = useState<NodeId | null>(null);
  const [hovered, setHovered] = useState<NodeId | null>(null);
  const [focused, setFocused] = useState<NodeId | null>(null);
  const clearHeroDetail = () => { setSelected(null); setHovered(null); setFocused(null); };
  const selectNode = (node: NodeId) => {
    if (heroDemo && selected === node) clearHeroDetail();
    else setSelected(selected === node ? null : node);
  };
  const highlighted = heroDemo ? hovered ?? focused ?? selected : null;
  const neighbors = highlighted ? heroNeighbors(highlighted) : [];
  const failed = ['failed', 'detect', 'locate', 'reason', 'decide'].includes(phase);
  const active = activePhases.includes(phase);
  const recovered = phase === 'recovered' || phase === 'learn';
  const current = systemNodes.find(node => node.id === selected);
  const stage = overviewStory.find(item => item.phase === phase);
  const detailNode = systemNodes.find(node => node.id === highlighted);
  const detail = highlighted ? heroNodeDetail(highlighted) : null;
  const agentX = heroDemo ? 83 : 82;
  const graph = <>
    <div className="topology-cross cross-a" /><div className="topology-cross cross-b" />
    <svg className="topology-lines" viewBox="0 0 800 520" preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id={`flow-${id}`}><stop stopColor="#6ee7f9" stopOpacity="0" /><stop offset="0.5" stopColor="#6ee7f9" /><stop offset="1" stopColor="#6ee7f9" stopOpacity="0" /></linearGradient><marker id={`arrow-${id}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 1 1 L 8 5 L 1 9" fill="none" stroke="context-stroke" strokeWidth="1.5" /></marker></defs>
      {topologyEdges.map(([from, to], i) => {
        const a = systemNodes.find(n => n.id === from)!; const b = systemNodes.find(n => n.id === to)!;
        const adjusted = narrative || heroDemo;
        const x1 = (adjusted && from === 'agent' ? agentX : a.x) * 8; const y1 = (adjusted && from === 'agent' ? 46 : a.y) * 5.2; const x2 = (adjusted && to === 'agent' ? agentX : b.x) * 8; const y2 = (adjusted && to === 'agent' ? 46 : b.y) * 5.2;
        const d = `M ${x1} ${y1} C ${x1} ${(y1 + y2) / 2}, ${x2} ${(y1 + y2) / 2}, ${x2} ${y2}`;
        const faultEdge = failed && (from === 'postgres' || to === 'postgres');
        const kind = narrative ? storyEdge(phase, from, to) : heroDemo ? heroEdgeKind(phase, from, to) : 'neutral';
        const associated = highlighted === from || highlighted === to;
        // Direction at the curve midpoint stays visible outside the node buttons.
        const mx = (x1 + x2) / 2; const my = (y1 + y2) / 2;
        return <g key={`${from}-${to}`} data-edge={`${from}-${to}`} data-kind={kind} data-associated={heroDemo && highlighted ? associated : undefined} className={heroDemo && to === 'worker' ? 'concept-edge' : undefined}><path d={d} className={`edge ${narrative ? `story-edge-${kind}` : heroDemo ? `hero-edge-${kind}` : faultEdge ? 'fault-edge' : ''}`} />{narrative || heroDemo ? kind !== 'neutral' && <path d={`M ${x1} ${y1} C ${x1} ${(y1 + my) / 2}, ${(x1 + mx) / 2} ${(y1 + 3 * my) / 4}, ${mx} ${my}`} className={`edge edge-direction ${narrative ? 'story' : 'hero'}-edge-${kind}`} markerEnd={`url(#arrow-${id})`} /> : <path d={d} className={`flow ${faultEdge ? 'fault-flow' : ''}`} style={{ animationDelay: `${i * -0.65}s` }} stroke={`url(#flow-${id})`} />}</g>;
      })}
    </svg>
    {systemNodes.map(node => {
      const Icon = icons[node.id];
      const narrativeState = storyNode(phase, node.id);
      const heroState = heroNodeState(phase, node.id);
      const status = narrative ? narrativeState.status : heroDemo ? heroState.status : node.id === 'postgres' && failed ? 'failed' : node.id === 'postgres' && phase === 'execute' ? 'recovering' : node.id === 'agent' && active ? 'active' : 'healthy';
      const label = narrative ? narrativeState.label : heroDemo ? heroState.label : status === 'failed' ? 'connection refused' : status === 'recovering' ? 'restarting…' : node.id === 'agent' ? (active ? phase : 'standby') : node.latency;
      const position = (narrative || heroDemo) && node.id === 'agent' ? { x: agentX, y: 46 } : node;
      return <button key={node.id} className={`system-node node-${node.id} ${status} ${!narrative && !heroDemo && recovered && node.id === 'postgres' ? 'just-recovered' : ''} ${selected === node.id ? 'selected' : ''}`} style={{ left: `${position.x}%`, top: `${position.y}%` }} aria-label={t("{0}: {1}{2}", node.label, t(label), node.conceptual ? t('，概念演示节点') : '')} aria-pressed={selected === node.id} aria-describedby={heroDemo ? `hero-detail-${id}` : undefined} data-muted={heroDemo && highlighted ? highlighted !== node.id && !neighbors.includes(node.id) : undefined} onPointerEnter={heroDemo ? () => setHovered(node.id) : undefined} onPointerLeave={heroDemo ? () => setHovered(null) : undefined} onFocus={heroDemo ? () => setFocused(node.id) : undefined} onBlur={heroDemo ? () => setFocused(null) : undefined} onClick={() => selectNode(node.id)}>
        <span className="node-head"><Icon size={17} strokeWidth={1.5} /><span className="status-light" /></span><strong>{node.label}</strong><span className="node-meta">{t(label)}</span>
      </button>;
    })}
    {!heroDemo && <><div className="topology-readout"><span className={`status-dot ${failed ? 'red' : narrative ? 'cyan' : 'green'}`} /><span>{narrative ? t(stage?.readout) : failed ? t('DEPENDENCY FAILURE') : recovered ? t('RECOVERY VERIFIED') : active ? t('AGENT PROCESSING') : t('ALL SYSTEMS NOMINAL')}</span><span className="readout-count">{narrative ? t('CONCEPT') : failed ? '01 / 04' : '04 / 04'}</span></div>
    <div className="node-description" aria-live="polite">{current ? <><span>{current.label}</span>{narrative && current.id === 'agent' ? t('诊断建议 · Planner / Safety · 经验记录；不连接真实模型或执行器。') : t(current.detail)}</> : narrative ? null : <><span>{t("TOPOLOGY / DEMO")}</span>{t("点击节点查看详情 · Worker 为概念节点")}</>}</div></>}
  </>;
  return <div className={`system-topology ${compact ? 'compact' : ''} ${paused ? 'motion-paused' : ''} ${narrative ? 'narrative-topology' : ''} ${heroDemo ? 'hero-topology' : ''}`} data-phase={phase} data-selected={heroDemo ? selected ?? undefined : undefined} aria-label={narrative ? t("{0} {1} · 概念拓扑", t(stage?.word), t(stage?.readout)) : heroDemo ? t('演示拓扑，不连接真实执行器') : t('演示拓扑')} onKeyDown={heroDemo ? event => { if (event.key === 'Escape') clearHeroDetail(); } : undefined}>
    {heroDemo ? <div className="hero-topology-canvas">{graph}</div> : graph}
    {heroDemo && <div className="hero-node-detail" id={`hero-detail-${id}`} aria-live="polite" aria-atomic="true">{detailNode && detail ? <><div><strong>{detailNode.label}</strong><span>{t(heroNodeState(phase, detailNode.id).label)}</span></div><p>{t(detail.role)}</p><small>{t("关联 ")}{t(detail.related)}{t(detail.conceptual)}</small></> : <p className="hero-node-hint">{t("悬停或选择节点，查看职责与关联。")}</p>}</div>}
  </div>;
}
