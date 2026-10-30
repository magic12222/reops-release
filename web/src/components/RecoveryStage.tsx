import { t, useLocale } from '../i18n';
import { Pause, Play, RotateCcw, SkipBack, SkipForward } from 'lucide-react';
import { demoSteps } from '../data/demoData';
import { recoveryLabState } from '../data/recoveryLab';
import type { useRecovery } from '../hooks/useRecovery';
import { RecoveryTopology } from './RecoveryTopology';

type Playback = ReturnType<typeof useRecovery>;
const sequence = [
  { name: '故障注入', index: 0, note: '数据库不可用' },
  { name: '根因定位', index: 3, note: '关联业务与依赖证据' },
  { name: '执行恢复', index: 5, note: '局部重启数据库' },
  { name: '业务验证', index: 6, note: '检查服务与业务请求' },
] as const;

export function RecoveryStage({ index, moving, reached, onSeek }: {
  index: number; moving: boolean; reached: number; onSeek: (index: number) => void;
}) {
  useLocale();
  const state = recoveryLabState(index);
  const current = index < 0 ? -1 : index === 0 ? 0 : index < 5 ? 1 : index === 5 ? 2 : 3;
  return <div className="lab-stage-grid">
    <div className="lab-theater">
      <RecoveryTopology index={index} moving={moving} />
      <div className="lab-caption" data-tone={state.complete ? 'verified' : state.database}>
        <div className="lab-caption-copy" key={index} role="status" aria-live="polite"><h2>{t(state.title)}</h2><p>{t(state.description)}</p></div><i aria-hidden="true" />
      </div>
    </div>
    <aside className="lab-sequence" aria-label={t("Recovery Sequence")}>
      <header><span>{t("Recovery sequence")}</span><span>{t("阶段 ")}{current + 1} / 4</span></header>
      <ol className="lab-stages" aria-label={t("恢复生命周期")}>{sequence.map((phase, i) =>
        <li key={phase.name}><button className={`${current > i || state.complete ? 'visited' : ''}`} onClick={() => onSeek(phase.index)} disabled={phase.index > reached}
          aria-current={current === i ? 'step' : undefined}>
          <span className="lab-sequence-number">{i + 1}</span><span className="lab-sequence-copy"><strong>{t(phase.name)}</strong><small>{i > current ? t("尚未开始") : i === 1 && index >= 3 ? t("根因已确认") : i === 3 && state.complete ? t("核验完成") : t(phase.note)}</small></span>
        </button></li>)}</ol>
      <div className="lab-sequence-evidence"><span>{t("当前证据")}</span><code>{state.evidence}</code></div>
    </aside>
  </div>;
}

export function RecoveryControls({ recovery, index, reduced, onStart }: {
  recovery: Playback; index: number; reduced: boolean; onStart: () => void;
}) {
  useLocale();
  const state = recoveryLabState(index);
  const playing = !reduced && recovery.running;
  const label = state.complete ? '重播恢复演示' : playing ? '暂停恢复演示' : '播放恢复演示';
  return <div className="lab-controls">
    <button className="lab-inject" onClick={onStart} disabled={index >= 0}>{t("Inject Failure")}</button>
    <div className="lab-event-progress">
      <span>{t("事件 ")}{index + 1} / {demoSteps.length}</span>
      <div className="lab-progress" role="progressbar" aria-label={t("模拟事件回放进度")} aria-valuemin={0} aria-valuemax={demoSteps.length} aria-valuenow={index + 1}>
        {demoSteps.map((step, i) => <i key={step.event.event_id} className={i < index ? 'past' : i === index ? 'current' : ''} />)}
      </div>
    </div>
    <div className="lab-playback" role="group" aria-label={t("模拟回放控制")}>
      <button onClick={() => recovery.moveEvent(-1)} disabled={index <= 0} aria-label={t("上一模拟事件")} title={t("上一事件")}><SkipBack size={15} /></button>
      <button className="lab-play-toggle" onClick={state.complete ? onStart : recovery.toggle} disabled={index < 0 || (reduced && !state.complete)}
        aria-label={label} title={reduced && !state.complete ? t("已减少动态效果，请单步浏览") : label}>
        {state.complete ? <RotateCcw size={15} /> : playing ? <Pause size={15} /> : <Play size={15} />}</button>
      <button onClick={() => recovery.moveEvent(1)} disabled={index < 0 || state.complete} aria-label={t("下一模拟事件")} title={t("下一事件")}><SkipForward size={15} /></button>
    </div>
  </div>;
}

export function RecoveryOutcome({ index }: { index: number }) {
  useLocale();
  const state = recoveryLabState(index);
  return <dl className="lab-results" aria-label={t("模拟恢复结果")}>
    <div><dt>{t("业务请求")}</dt><dd className={state.complete ? 'lab-result-passed' : index >= 0 && index < 6 ? 'lab-result-failed' : ''}>
      {index < 0 ? t("200 OK") : state.complete ? '503 → 200' : index === 6 ? t("等待核验") : t("503 · 请求失败")}
      <small>{index < 0 ? t("基线 · GET /users") : state.complete ? t("服务与业务验证均通过") : index === 6 ? t("执行结果不等于业务恢复") : t("数据库连接失败")}</small></dd></div>
    <div><dt>{t("根因")}</dt><dd>{index >= 3 ? t("PostgreSQL 服务停止") : index < 0 ? t("无活动故障") : t("正在定位")}<small>{index >= 3 ? t("连接拒绝 · postgres:5432") : index < 0 ? t("等待模拟故障注入") : t("根据观测关联失败依赖")}</small></dd></div>
    <div><dt>{t("恢复动作")}</dt><dd>{index >= 4 ? t("局部重启数据库") : t("尚未执行")}<small>{index >= 5 ? t("模拟执行 · restart_service(postgres)") : index === 4 ? t("已选定 · 等待执行") : t("仅使用白名单动作")}</small></dd></div>
  </dl>;
}
