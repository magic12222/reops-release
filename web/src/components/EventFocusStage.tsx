import { useLayoutEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import './ExecutionExplorer.css';

export interface FocusEvent { id: string; title: string; shortTitle: string; status: string; fact?: string }

/** Persistent event surfaces move through depth; the index is the accessible navigation. */
export function EventFocusStage({ items, position, onSelect, active, busy, controls, focusLabel = '当前焦点事件', navigationLabel = '事件索引' }: {
  items: FocusEvent[]; position: number; onSelect: (index: number) => void;
  active: boolean; busy: boolean; controls?: ReactNode; focusLabel?: string; navigationLabel?: string;
}) {
  const indexList = useRef<HTMLOListElement>(null);
  useLayoutEffect(() => {
    const list = indexList.current;
    const item = list?.children[position] as HTMLElement | undefined;
    if (!list || !item || !active || busy) return;
    // Only move the index viewport. Never scroll the page or the stable evidence region.
    const reveal = () => {
      const left = item.getBoundingClientRect().left - list.getBoundingClientRect().left + list.scrollLeft;
      if (left < list.scrollLeft) list.scrollLeft = left;
      else if (left + item.offsetWidth > list.scrollLeft + list.clientWidth)
        list.scrollLeft = left + item.offsetWidth - list.clientWidth;
    };
    reveal();
    const observer = new ResizeObserver(reveal);
    observer.observe(list);
    return () => observer.disconnect();
  }, [position, items.length, active, busy]);

  return <div className="cinematic-stage">
    <div className="chamber-space" aria-label={focusLabel}>
      {items.map((step, index) => {
        const offset = index - position;
        const depth = offset < -1 ? 'past' : offset === -1 ? 'previous' : offset === 0 ? 'focus' : offset === 1 ? 'next' : 'future';
        return <div key={step.id} className="chamber-plane" data-depth={depth}
          data-event-id={step.id} aria-hidden={offset !== 0}>
          <span className="chamber-ordinal">{String(index + 1).padStart(2, '0')}<span> / {String(items.length).padStart(2, '0')}</span></span>
          <h3>{step.shortTitle}</h3>
          {step.fact && <p className="chamber-fact">{step.fact}</p>}
        </div>;
      })}
    </div>
    <div className="chamber-footer"><nav className="chamber-navigation" aria-label={navigationLabel}>
      <ol ref={indexList}>{items.map((step, index) => <li key={step.id}>
        <button className="event-index" aria-pressed={index === position} disabled={busy || !active}
          aria-label={`${index + 1}. ${step.title} · ${step.status}`}
          title={`${step.title} · ${step.status}`} onClick={() => onSelect(index)}
          onKeyDown={event => {
            const target = event.key === 'ArrowRight' ? Math.min(items.length - 1, index + 1)
              : event.key === 'ArrowLeft' ? Math.max(0, index - 1) : event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : null;
            if (target === null) return;
            event.preventDefault(); onSelect(target);
            (indexList.current?.children[target]?.querySelector('button') as HTMLButtonElement)?.focus({ preventScroll: true });
          }}><span>{String(index + 1).padStart(2, '0')}</span>{step.shortTitle}</button>
      </li>)}</ol>
    </nav>{controls}</div>
  </div>;
}
