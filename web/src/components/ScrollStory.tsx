import { t, useLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import { useInView, useReducedMotion } from 'motion/react';
import { SectionLabel } from './Primitives';
import { SystemTopology } from './SystemTopology';
import { overviewStory as story } from '../data/overviewStory';

const readerQuery = '(max-width: 760px)';

export function stageAtPosition(markerTops: number[], offset: number) {
  let index = 0;
  markerTops.forEach((top, i) => { if (top <= offset + 1) index = i; });
  return index;
}

function StageDiagram({ index, paused }: { index: number; paused: boolean }) {
  useLocale();
  const item = story[index];
  return <div className="story-diagram" data-stage={item.phase}>
    <SystemTopology phase={item.phase} compact narrative paused={paused} />
    <div className="story-detail"><span>0{index + 1} / 06</span><p>{t(item.detail)}</p></div>
  </div>;
}

export function ScrollStory() {
  useLocale();
  const ref = useRef<HTMLElement>(null);
  const reduced = useReducedMotion();
  const inView = useInView(ref);
  const [reader, setReader] = useState(() => typeof window !== 'undefined' && window.matchMedia(readerQuery).matches);
  const [index, setIndex] = useState(0);
  const pendingStage = useRef<number | null>(null);
  const position = useRef({ inside: false, index: 0 });
  useEffect(() => {
    const query = window.matchMedia(readerQuery);
    const update = () => {
      if (position.current.inside) pendingStage.current = position.current.index;
      setReader(query.matches);
    };
    update(); query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    let frame = 0;
    const offset = () => (document.querySelector('.navbar')?.getBoundingClientRect().height ?? 82) + 16;
    const update = () => {
      frame = 0;
      const markers = Array.from(ref.current?.querySelectorAll<HTMLElement>('[data-story-marker]') ?? []);
      const target = pendingStage.current;
      pendingStage.current = null;
      if (target !== null && markers[target]) window.scrollTo({ top: markers[target].getBoundingClientRect().top + window.scrollY - offset() + 1, behavior: 'instant' });
      const next = stageAtPosition(markers.map(marker => marker.getBoundingClientRect().top), offset());
      const bounds = ref.current?.getBoundingClientRect();
      position.current = { inside: !!bounds && bounds.top <= offset() + 1 && bounds.bottom > window.innerHeight, index: next };
      setIndex(next);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    const resize = () => { if (position.current.inside) pendingStage.current = position.current.index; schedule(); };
    // Panel height defines the release point; fonts and viewport changes cannot leave an empty tail.
    const panel = ref.current?.querySelector<HTMLElement>('.story-sticky');
    const observer = new ResizeObserver(() => {
      if (panel) ref.current?.style.setProperty('--story-panel-height', `${panel.getBoundingClientRect().height}px`);
      schedule();
    });
    if (panel) observer.observe(panel);
    update();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', resize);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('scroll', schedule); window.removeEventListener('resize', resize); };
  }, [reader]);
  const select = (i: number) => {
    const marker = ref.current?.querySelectorAll<HTMLElement>('[data-story-marker]')[i];
    if (!marker) return;
    const offset = (document.querySelector('.navbar')?.getBoundingClientRect().height ?? 82) + 16;
    // Keep native scroll and the selected stage in agreement after clicks.
    window.scrollTo({ top: marker.getBoundingClientRect().top + window.scrollY - offset, behavior: 'instant' });
    setIndex(i);
    if (reader) marker.querySelector<HTMLElement>('h3')?.focus({ preventScroll: true });
  };
  const words = <div className="story-words" role="group" aria-label={t("六阶段恢复叙事")}>{story.map((item, i) => <button key={item.word} className={index === i ? 'active' : ''} onClick={() => select(i)} aria-pressed={index === i} aria-controls={reader ? `story-stage-${i}` : 'story-current'}><span className="word-index">0{i + 1}</span><span>{t(item.word)}</span><span className="word-cn">{t(item.sub)}</span></button>)}</div>;
  const heading = <><SectionLabel>{t("HOW REOPS WORKS")}</SectionLabel>
    <div className="story-heading"><h2>{t("Systems fail.")}<br /><span>{t("Recovery can evolve.")}</span></h2><div className="story-concept"><span>{t("CONCEPT · 概念示意")}</span><small>{t("非在线状态 · Worker 为概念节点")}</small></div></div></>;
  return <section id="story" className={`scroll-story light ${reader ? 'story-reader' : ''}`} ref={ref} aria-label={t("六阶段故障恢复概念示意")} data-active-stage={story[index].phase}>
    {reader ? <div className="shell story-reading"><div className="story-intro">{heading}{words}</div>{story.map((item, i) => <article id={`story-stage-${i}`} key={item.phase} data-story-marker className={`story-stage ${index === i ? 'active' : ''}`} aria-labelledby={`story-title-${i}`}><h3 id={`story-title-${i}`} tabIndex={-1}><span>0{i + 1}</span> {t(item.word)}<small>{t(item.sub)}</small></h3><StageDiagram index={i} paused /></article>)}</div> : <div className="story-track">
    <div className="story-sticky shell">{heading}<div className="story-body">{words}<div id="story-current" aria-live="polite" aria-atomic="true"><StageDiagram index={index} paused={!!reduced || !inView} /></div></div>
        <div className="story-progress" aria-hidden="true">{story.map((item, i) => <span key={item.word} className={i <= index ? 'filled' : ''} />)}<span className="story-hint">{t("滚动继续 · 点击跳转")}</span></div>
      </div>{story.map((item, i) => <div key={item.phase} className="story-marker" data-story-marker style={{ top: `calc(var(--story-step) * ${i})` }} aria-hidden="true" />)}
    </div>}
  </section>;
}
