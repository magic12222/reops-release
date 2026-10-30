import { t, useLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import { useInView } from 'motion/react';
import { ArrowDown, ArrowUpRight, Pause, Play, SkipForward } from 'lucide-react';
import { SystemTopology } from './SystemTopology';
import { advanceHeroClock, heroStageAt, heroStages } from '../data/heroSimulation';
import { SimulationBadge } from './Primitives';
import { paths } from '../navigation/routes';

export function HeroSystem() {
  useLocale();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref);
  const [reduced, setReduced] = useState(() => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [paused, setPaused] = useState(false);
  const [hidden, setHidden] = useState(() => typeof document !== 'undefined' && document.hidden);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(query.matches);
    update(); query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  useEffect(() => { const update = () => setHidden(document.hidden); document.addEventListener('visibilitychange', update); return () => document.removeEventListener('visibilitychange', update); }, []);
  const stopped = paused || !!reduced || !inView || hidden;
  useEffect(() => {
    if (stopped) return;
    let previous = performance.now();
    const interval = window.setInterval(() => {
      const now = performance.now();
      // No catch-up after suspension: visibility/viewport changes stop this clock.
      const delta = Math.min(now - previous, 250);
      previous = now;
      setElapsed(value => advanceHeroClock(value, delta));
    }, 100);
    return () => window.clearInterval(interval);
  }, [stopped]);
  const stage = heroStageAt(elapsed);
  const next = () => { setPaused(true); setElapsed(heroStages[(stage.index + 1) % heroStages.length].at); };
  return <section id="overview" className="hero" data-demo-stage={stage.index} data-demo-elapsed={Math.round(elapsed)} data-demo-stopped={stopped}>
    <div className="hero-grid" />
    <div className="hero-content shell">
      <div className="hero-eyebrow"><span className="tiny-cross">+</span> {t(" INTELLIGENT OPERATIONS ")}<span className="hero-version">{t("RESEARCH / 2026")}</span></div>
      <div className="hero-layout">
        <div className="hero-copy"><div className="hero-kicker">{t("从证据出发，让恢复有据可循。")}</div><h1>{t("ReOps")}<span>.</span></h1><h2>{t("Failure is")}<br />{t("a beginning.")}</h2><p>{t("Agentic diagnosis. Constrained recovery.")}<br /><span>{t("面向故障诊断与受约束恢复的智能运维。")}</span></p>
          <div className="hero-actions"><a className="button primary" href={paths.recovery}>{t("体验恢复演示 ")}<ArrowUpRight size={17} /></a><a className="hero-secondary" href={paths.architecture}>{t("Explore the system ")}<ArrowUpRight size={16} /></a></div>
        </div>
        <div className="hero-visual" ref={ref}><div className="visual-caption"><span>{t("REOPS / SYSTEM GRAPH")}</span><SimulationBadge>{t("SIMULATION · 非在线状态")}</SimulationBadge></div><SystemTopology phase={stage.phase} paused={stopped} heroDemo />
          <div className="hero-trace"><span className={`status-dot ${stage.tone}`} /><span className="hero-stage-count">0{stage.index + 1} / 04</span><div className="hero-stage-copy"><span>{t(stage.label)}</span><span key={stage.title} className="trace-message">{t(stage.title)}</span></div><div className="hero-playback"><div className="hero-controls"><button className="icon-button" aria-label={paused ? t('继续首页动画') : t('暂停首页动画')} aria-pressed={paused} onClick={() => setPaused(!paused)} disabled={!!reduced} title={reduced ? t('减少动态效果：使用下一阶段查看演示') : paused ? t('继续演示') : t('暂停演示')}>{paused || reduced ? <Play size={15} /> : <Pause size={15} />}</button><button className="icon-button" aria-label={t("首页演示下一阶段")} onClick={next} title={t("下一阶段（保持暂停）")}><SkipForward size={15} /></button></div><span className="trace-time" title={t("演示循环位置，不是恢复时延")}>{t("CYCLE ")}{(elapsed / 1000).toFixed(1)}{t("s")}</span></div></div>
        </div>
      </div>
      <div className="hero-bottom"><a href="#story"><ArrowDown size={15} /> {t(" SCROLL TO FOLLOW A RECOVERY")}</a><span>{t("HUAWEI ICT INNOVATION COMPETITION ")}<span className="slash">/</span> 2026</span></div>
    </div>
  </section>;
}
