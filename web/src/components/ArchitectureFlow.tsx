import { t, useLocale } from '../i18n';
import { useId, useRef, useState } from 'react';
import { ChevronRight, X } from 'lucide-react';
import { architectureNeighbors, architectureTabIndex, architectureViews } from '../data/architecture';
import { architectureLayerPurposes, architectureNodeDescriptions } from '../data/architecturePresentation';
import type { ArchitectureNode } from '../data/architecture';
import { Reveal, SectionLabel } from './Primitives';

export function ArchitectureNodeDetail({ node, onClose }: { node: ArchitectureNode; onClose: () => void }) {
  useLocale();
  return <div className="arch-node-detail" id="arch-node-detail" data-detail-node={node.id}>
    <div aria-live="polite" aria-atomic="true">
      <strong>{t(node.name)}</strong>
      <p>{t(architectureNodeDescriptions[node.id])}</p>
    </div>
    <button type="button" className="icon-button arch-detail-close" aria-label={t("关闭组件详情")} onClick={onClose}><X size={16} /></button>
  </div>;
}

export function ArchitectureFlow() {
  useLocale();
  const sectionRef = useRef<HTMLElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const nodeRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const arrowId = `architecture-arrow-${useId().replaceAll(':', '')}`;
  const [active, setActive] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const layer = architectureViews[active];
  const highlighted = hovered ?? focused ?? selected;
  const neighbors = highlighted ? architectureNeighbors(layer, highlighted) : [];
  const detail = layer.nodes.find(node => node.id === selected);
  const chooseLayer = (index: number) => { setActive(index); setSelected(null); setHovered(null); setFocused(null); };
  const closeDetail = () => {
    if (selected) nodeRefs.current[selected]?.focus({ preventScroll: true });
    setSelected(null); setHovered(null); setFocused(null);
  };

  return <section id="architecture" className="architecture section shell" ref={sectionRef} data-architecture-layer={layer.id}>
    <Reveal><SectionLabel>{t("SYSTEM ARCHITECTURE")}</SectionLabel><div className="section-heading"><h1>{t("Built to recover.")}<br /><span>{t("Designed to explain.")}</span></h1><p>{t("系统、决策与证据，组成 ReOps。")}</p></div></Reveal>
    <Reveal className="architecture-grid">
      <div className="layer-list" role="tablist" aria-label={t("架构层次")} aria-orientation="vertical">
        {architectureViews.map((item, i) => <button key={item.id} ref={element => { tabRefs.current[i] = element; }} type="button" role="tab" aria-selected={active === i} tabIndex={active === i ? 0 : -1} aria-controls="layer-panel" id={`layer-tab-${i}`} className={`layer-tab ${active === i ? 'active' : ''}`} onClick={() => chooseLayer(i)} onKeyDown={event => {
          const next = architectureTabIndex(i, event.key, architectureViews.length);
          if (next !== null) { event.preventDefault(); chooseLayer(next); tabRefs.current[next]?.focus(); }
        }}><span className="layer-number">{item.number}</span><div><small>{t(item.label)}</small><h3>{t(item.name)}</h3><span className="layer-state">{t(architectureLayerPurposes[item.id])}</span></div><ChevronRight size={18} aria-hidden="true" /></button>)}
      </div>
      <div className="layer-panel" id="layer-panel" role="tabpanel" aria-labelledby={`layer-tab-${active}`} tabIndex={0} data-selected-node={selected ?? undefined} onKeyDown={event => { if (event.key === 'Escape') closeDetail(); }}>
        <div className="panel-topline"><span>{t("REOPS / ARCHITECTURE")}</span><span>{t("逻辑示意")}</span></div>
        <div className="arch-view" key={layer.id}>
          <div className="schema-head"><span>{layer.number}</span><h3>{t(layer.summary)}</h3></div>
          <div className="arch-diagram" role="group" aria-label={t("{0} 组件关系，非在线拓扑", t(layer.name))}>
            <svg className="arch-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><defs><marker id={arrowId} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 1 1 L 8 5 L 1 9" fill="none" stroke="context-stroke" strokeWidth="1.5" /></marker></defs>{layer.edges.map(edge => <g key={`${edge.from}-${edge.to}`} data-architecture-edge={`${edge.from}-${edge.to}`} data-associated={highlighted ? edge.from === highlighted || edge.to === highlighted : undefined}><path d={edge.route} className={edge.external ? 'arch-external-edge' : undefined} /><path className="arch-direction" d={edge.arrow} markerEnd={`url(#${arrowId})`} /></g>)}</svg>
            {layer.edges.map(edge => <span key={`${edge.from}-${edge.to}`} className={`arch-edge-label ${edge.external ? 'external' : ''}`} data-kind={edge.kind} data-secondary={edge.from === 'docker' ? true : undefined} style={{ left: `${edge.labelX}%`, top: `${edge.labelY}%` }} data-associated={highlighted ? edge.from === highlighted || edge.to === highlighted : undefined}>{t(edge.label)}</span>)}
            {layer.nodes.map(node => <button key={node.id} ref={element => { nodeRefs.current[node.id] = element; }} type="button" className={`arch-node ${selected === node.id ? 'selected' : ''}`} style={{ left: `${node.x}%`, top: `${node.y}%` }} data-architecture-node={node.id} data-related={highlighted ? node.id === highlighted || neighbors.includes(node.id) : undefined} aria-pressed={selected === node.id} aria-controls={detail ? 'arch-node-detail' : undefined} aria-label={t("{0}，{1}", t(node.name), t(node.tag))} onPointerEnter={() => setHovered(node.id)} onPointerLeave={() => setHovered(null)} onFocus={() => setFocused(node.id)} onBlur={() => setFocused(null)} onClick={() => { if (selected === node.id) closeDetail(); else setSelected(node.id); }}><span className="arch-node-port" /><strong>{t(node.name)}</strong><span>{t(node.tag)}</span></button>)}
          </div>
          <div className="arch-relation-key" aria-label={t("连线语义与展示模式")}><span data-kind="dependency">{t("依赖")}</span><span data-kind="data">{t("数据")}</span><span data-kind="control">{t("控制")}</span><small>{t("非实时执行 · 在线联调待验收")}</small></div>
        </div>
        {detail && <ArchitectureNodeDetail node={detail} onClose={closeDetail} />}
      </div>
    </Reveal>
  </section>;
}
