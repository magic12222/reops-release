import { t, useLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import { useInView } from 'motion/react';
import { ArrowUpRight } from 'lucide-react';
import { useRecovery } from '../hooks/useRecovery';
import { recoveryLabState } from '../data/recoveryLab';
import { LiveRecovery } from './LiveRecovery';
import { RecoveryControls, RecoveryOutcome, RecoveryStage } from './RecoveryStage';
import { RecoveryEvidence } from './RecoveryEvidence';
import './RecoveryLab.css';

export function RecoveryDemo({ mode = 'simulation', active = true }: { mode?: 'simulation' | 'api'; active?: boolean }) {
  useLocale();
  return mode === 'api' ? <LiveRecovery active={active} /> : <SimulationRecovery active={active} />;
}

function SimulationRecovery({ active }: { active: boolean }) {
  useLocale();
  const recovery = useRecovery(active);
  const index = recovery.snapshot?.index ?? -1;
  const state = recoveryLabState(index);
  const [reduced, setReduced] = useState(() => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const stageRef = useRef<HTMLDivElement>(null);
  const inView = useInView(stageRef, { amount: .15 });
  const [ambientPaused, setAmbientPaused] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [selected, setSelected] = useState(0);
  const [reached, setReached] = useState(-1);
  useEffect(() => { if (index >= 0) setSelected(index); }, [index]);
  useEffect(() => { setReached(current => Math.max(current, index)); }, [index]);
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(preference.matches);
    update(); preference.addEventListener('change', update);
    return () => preference.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    const update = () => setHidden(document.hidden);
    update(); document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  // System preference and offscreen changes stop the existing local clock.
  useEffect(() => { if (reduced) recovery.pause(); }, [reduced]);
  useEffect(() => { if (!inView) recovery.pause(); }, [inView]);
  const ambient = index < 0 || state.complete;
  const moving = active && inView && !hidden && !reduced && (ambient ? !ambientPaused : recovery.running);
  const start = () => { setAmbientPaused(false); setReached(0); setSelected(0); reduced ? recovery.seek(0) : recovery.start(); };
  const reset = () => { recovery.reset(); setReached(-1); setSelected(0); setAmbientPaused(true); };
  return <section id="recovery" className="recovery-lab shell">
    <header className="lab-hero">
      <div><span className="lab-kicker">{t("RECOVERY LAB")}</span><h1>{t("Break it. ")}<span>{t("Watch it recover.")}</span></h1><p>{t("让一个依赖失效，看清系统如何恢复业务。")}</p></div>
      <div className="lab-hero-aside"><span className="lab-scenario-number" aria-hidden="true">01</span><div><span>{t("当前演示场景")}</span><strong>{t("PostgreSQL down")}</strong><a href="/agent">{t("查看 Agent 运行记录")}<ArrowUpRight size={13} /></a></div></div>
    </header>
    <div className="lab-workbench" ref={stageRef}>
      <header className="lab-bar"><div><span className="lab-bar-mark" /> <span>{t("RECOVERY SIMULATION")}</span><span className="lab-scenario">{t("F01 / 服务依赖")}</span></div><span className="lab-source">{t("SIMULATION · 演示数据")}</span></header>
      <RecoveryStage index={index} moving={moving} reached={reached} onSeek={recovery.seek} />
      <RecoveryControls recovery={recovery} index={index} reduced={reduced} onStart={start} />
      <div className="lab-boundary"><p>{t("浏览器本地模拟，不操作容器。")}{reduced ? t('已减少动态效果，请使用单步控制。') : t('播放节奏仅用于演示，不代表实际恢复时延。')}</p>
        <button className="lab-reset" onClick={reset} disabled={index < 0} aria-label={t("回到初始状态")} title={t("返回健康基线并暂停；重播会重新开始故障过程")}>{t("回到初始")}</button>
      </div>
      {recovery.error && <p className="lab-error" role="alert">{t("演示出现错误：")}{t(recovery.error)}{t("。请重置后重试。")}</p>}
    </div>
    <RecoveryOutcome index={index} />
    <RecoveryEvidence selected={selected} onSelect={setSelected} index={index} />
  </section>;
}
