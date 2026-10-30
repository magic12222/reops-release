import { t, useLocale } from '../i18n';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { ReadTraceStep } from '../data/adapter';
import { eventStatus, traceName } from '../data/traceExplorer';
import { agentTime } from '../data/agentDisplay';
import { chamberPresentation, chamberStageName } from '../data/agentChamber';
import type { ChamberSignal } from '../data/agentChamber';

const number = (index: number) => String(index + 1).padStart(2, '0');
interface Wire { key: string; path: string; x: number; y: number }

/** Agent-only display: focal text and evidence belong to the selected recorded event. */
export function AgentCinematicStage({ trace, position, onSelect, active, busy, controls, onInspect, inspectedKey }: {
  trace: ReadTraceStep[]; position: number; onSelect: (index: number) => void;
  active: boolean; busy: boolean; controls?: ReactNode;
  onInspect: (signal: ChamberSignal) => void; inspectedKey?: string;
}) {
  const locale = useLocale();
  const step = trace[position];
  const view = useMemo(() => step ? chamberPresentation(step.event) : null, [step, locale]);
  const scene = useRef<HTMLDivElement>(null), core = useRef<HTMLDivElement>(null);
  const signalRefs = useRef<(HTMLButtonElement | null)[]>([]), indexList = useRef<HTMLOListElement>(null);
  const [wires, setWires] = useState<Wire[]>([]);
  const titleId = useId();
  useEffect(() => {
    const container = scene.current, center = core.current;
    if (!container || !center || !active) return;
    const draw = () => {
      const box = container.getBoundingClientRect(), target = center.getBoundingClientRect();
      if (!box.width) { setWires([]); return; }
      const x = target.left - box.left + target.width / 2, y = target.top - box.top + target.height / 2;
      setWires((view?.signals ?? []).flatMap((signal, index) => {
        const node = signalRefs.current[index]; if (!node) return [];
        const rect = node.getBoundingClientRect(), sx = rect.left - box.left + rect.width / 2,
          sy = rect.top - box.top + rect.height / 2, dx = (x - sx) * .45;
        return [{ key: signal.key, x, y, path: `M ${sx} ${sy} C ${sx + dx} ${sy},${x - dx} ${y},${x} ${y}` }];
      }));
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(container); observer.observe(center);
    signalRefs.current.forEach(node => { if (node) observer.observe(node); });
    return () => observer.disconnect();
  }, [active, view]);
  useEffect(() => {
    const list = indexList.current, item = list?.children[position] as HTMLElement | undefined;
    if (!active || busy || !list || !item) return;
    const reveal = () => {
      const left = item.getBoundingClientRect().left - list.getBoundingClientRect().left + list.scrollLeft;
      if (left < list.scrollLeft) list.scrollLeft = left;
      else if (left + item.offsetWidth > list.scrollLeft + list.clientWidth) list.scrollLeft = left + item.offsetWidth - list.clientWidth;
    };
    reveal(); const observer = new ResizeObserver(reveal); observer.observe(list);
    return () => observer.disconnect();
  }, [position, trace.length, active, busy]);
  if (!step || !view) return null;
  return <div className="agent-evidence-chamber cinematic-stage">
    <div className="agent-chamber-scene" ref={scene}>
      <div className="agent-scene-label"><span>{t("EXECUTION CHAMBER")}</span><span>{t("证据聚焦 · 已记录事件")}</span></div>
      <div className="agent-chamber-backword" aria-hidden="true">{t(traceName(step.event)).toUpperCase()}</div>
      <svg className="agent-evidence-wires" aria-labelledby={titleId} role="img">
        <title id={titleId}>{t("当前事件与已记录证据的展示关联")}</title>
        {wires.map(wire => <g key={wire.key}><path d={wire.path} className={wire.key === inspectedKey ? 'is-selected' : undefined} />
          <circle cx={wire.x} cy={wire.y} r="2" /></g>)}
      </svg>
      <div className="agent-chamber-deck" aria-hidden="true"><div /><div /><div /><span /></div>
      <div className="agent-chamber-core" ref={core}>
        <div className="agent-core-copy" key={step.event.event_id} aria-live="polite">
          <div className="chamber-ordinal">{number(position)}<span> / {number(trace.length - 1)} · {t(traceName(step.event)).toUpperCase()}</span></div>
          <h3 data-long={view.primary.length > 28}>{view.primary}</h3>
          {view.secondary && <p>{view.secondary}</p>}
          <div className={`agent-core-status status-${step.event.status}`}><span>{t(eventStatus(step.event.status))}</span>
            <time dateTime={step.event.timestamp ?? undefined}>{agentTime(step.event.timestamp, '无独立时间戳')}</time></div>
          {!view.signals.length && <p className="agent-no-signals">{t("此事件未提供结构化证据。")}</p>}
        </div>
      </div>
      {view.signals.map((signal, index) => <button key={signal.key} ref={node => { signalRefs.current[index] = node; }}
        className={`agent-evidence-signal signal-${index}`} aria-pressed={inspectedKey === signal.key}
        aria-label={t("查看证据：{0} · {1}", t(signal.label), signal.text)} title={signal.text}
        disabled={busy || !active} onClick={() => onInspect(signal)}>
        <span className="agent-signal-label"><span>{t(signal.label)}</span><span>{number(index)}</span></span>
        <strong data-long={signal.display.length > 22}>{signal.display}</strong>
        <span className="agent-signal-caption">{signal.display === signal.text ? t("查看原始证据 ↗") : signal.text}</span>
      </button>)}
      <div className="agent-chamber-corner" aria-hidden="true"><b>{number(position)}</b><span>{t("选中事件")}<br />{t("关联证据")}</span></div>
    </div>
    <div className="agent-chamber-transport">
      <nav aria-label={t("事件索引")} className="agent-chamber-index"><ol ref={indexList}>
        {trace.map((item, index) => <li key={item.event.event_id}><button className="event-index" aria-pressed={index === position}
          disabled={busy || !active} title={t("{0} · {1}", t(item.title), t(eventStatus(item.event.status)))}
          aria-label={t("{0}. {1} · {2}", index + 1, t(item.title), t(eventStatus(item.event.status)))} onClick={() => onSelect(index)} onKeyDown={event => {
            const target = event.key === 'ArrowRight' ? Math.min(trace.length - 1, index + 1) : event.key === 'ArrowLeft' ? Math.max(0, index - 1)
              : event.key === 'Home' ? 0 : event.key === 'End' ? trace.length - 1 : null;
            if (target === null) return;
            event.preventDefault(); onSelect(target); (indexList.current?.children[target]?.querySelector('button') as HTMLButtonElement)?.focus({ preventScroll: true });
          }}><span>{number(index)}</span>{t(chamberStageName(item.event))}</button></li>)}
      </ol></nav>
      <div className="agent-chamber-playbar"><span>{t("EVENT ")}{number(position)} / {number(trace.length - 1)}</span>{controls}<span>{t("只读回放")}</span></div>
    </div>
  </div>;
}
