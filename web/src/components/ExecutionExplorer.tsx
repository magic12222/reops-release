import { t, useLocale } from '../i18n';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, ChevronDown, Circle, Copy, Fingerprint, Pause, Play } from 'lucide-react';
import { evidenceFields, evidencePreview, eventStatus, EVENT_PLAYBACK_MS, runName } from '../data/traceExplorer';
import { evidenceFactText, evidencePresentation } from '../data/evidencePresentation';
import { provenanceLabels, runStatusLabels } from '../data/adapter';
import type { ChamberSignal } from '../data/agentChamber';
import { chamberPresentation } from '../data/agentChamber';
import { agentDuration, agentTime } from '../data/agentDisplay';
import type { ReadTraceStep } from '../data/adapter';
import type { RunRecord } from '../types/dashboard';
import type { LoadState, RunDetail } from './LiveRecovery';
import { AgentCinematicStage } from './AgentCinematicStage';
import './ExecutionExplorer.css';
import './AgentEvidenceChamber.css';

function RecordFields({ fields, raw = false }: { fields: [string, unknown][]; raw?: boolean }) {
  useLocale();
  return <dl className="explorer-fields">{fields.map(([key, value]) => <div key={key}><dt>{raw ? key : t(key)}</dt>
    <dd>{(typeof value === 'object' && value !== null) || (typeof value === 'string' && (value.length > 240 || value.split('\n').length > 3))
      ? <details className="evidence-value"><summary>{evidencePreview(value).slice(0, 160)}<ChevronDown size={13} /></summary>
        <pre>{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre></details> : evidencePreview(value)}</dd></div>)}</dl>;
}

function RunContext({ run }: { run: RunRecord }) {
  useLocale();
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);
  return <section className="record-section run-context" aria-label={t("运行上下文")}><h4>{t("运行上下文")}</h4><RecordFields fields={[
    ['Run ID', run.id], ['Incident', run.incident_id], ['Trace', run.trace_id], ['Case', run.case_id ?? t('未提供')],
    ['Fault', run.fault_id ?? t('未提供')], ['开始时间', agentTime(run.started_at)],
    ['结束时间', agentTime(run.finished_at)],
    ['结果', t(runStatusLabels[run.status])],
    ['恢复确认', run.success === true ? t('是') : run.success === false ? t('否') : t('未确认')],
    ['模型调用次数', run.model_calls ?? t('未提供')], ['恢复动作次数', run.action_count ?? t('未提供')],
    ['恢复耗时', run.recovery_latency_ms === null ? t('未定义（口径待 C5）') : agentDuration(run.recovery_latency_ms)],
    ['运行元数据', run.metadata],
  ]} /><button className="trace-button copy-run" title={t("复制完整 Run ID")} onClick={async () => {
    try { await navigator.clipboard.writeText(run.id); setCopied(true); setCopyError(false); }
    catch { setCopyError(true); }
  }}><Copy size={13} />{copied ? t("已复制 Run ID") : t("复制完整 Run ID")}</button>
    <span role="status" className="explorer-muted">{copyError ? t("复制不可用，请选取上方完整 ID。") : copied ? t("完整 Run ID 已复制。") : ''}</span>
    <details className="raw-evidence"><summary>{t("原始 Run JSON")}<ChevronDown size={14} /></summary><pre>{JSON.stringify(run, null, 2)}</pre></details></section>;
}

function EvidenceInspector({ step, run, trace, onSelectParent, inspected, inspectRevision }: {
  step?: ReadTraceStep; run?: RunRecord; trace: ReadTraceStep[]; onSelectParent: (id: string) => void; inspected?: ChamberSignal; inspectRevision?: number;
}) {
  useLocale();
  const disclosure = useRef<HTMLDetailsElement>(null);
  // Only an explicit signal click opens this disclosure; later SSE snapshots may update its text.
  useEffect(() => { if (inspectRevision && disclosure.current) disclosure.current.open = true; }, [inspectRevision]);
  const fields = step ? evidenceFields(step.event) : [];
  const preview = step ? evidencePresentation(step.event) : undefined;
  const parent = trace.find(item => item.event.event_id === step?.event.parent_event_id);
  return <section className="evidence-inspector" aria-label={t("Evidence Inspector")} data-run-id={run?.id}>
    <details className="agent-evidence-disclosure" ref={disclosure}><summary><span>{t("Evidence ")}<span>{t("查看证据原文与完整记录")}</span></span><ChevronDown size={14} /></summary>
    <div key={step?.event.event_id ?? 'empty'} className="evidence-content" data-event-id={step?.event.event_id}>
      {inspected && <div className="agent-inspected-evidence" role="status"><span>{t(inspected.label)}</span><pre>{typeof inspected.value === 'string' ? inspected.value : JSON.stringify(inspected.value, null, 2)}</pre></div>}
      {step && preview ? <div className="evidence-preview">
        {preview.status && <span className={`event-status status-${preview.status}`}><Circle size={6} fill="currentColor" />{t(eventStatus(preview.status))}</span>}
        {preview.summary && <p className="evidence-message">{preview.summary}</p>}
        {preview.facts.length > 0 ? <dl className="evidence-facts">{preview.facts.map(fact => <div key={fact.key}
          data-wide={typeof fact.value === 'object' || evidenceFactText(fact).length > 70}>
          <dt>{t(fact.label)}</dt><dd data-negative={fact.value === false && ['health_check_passed', 'business_request_passed', 'fault_cleared'].includes(fact.key)}>{evidenceFactText(fact)}</dd></div>)}</dl>
          : !preview.summary && <p className="explorer-muted">{fields.length ? t("此事件仅提供部分记录；完整内容可展开查看。") : t("此事件未提供结构化证据。")}</p>}
      </div> : <p className="explorer-muted">{run ? t("此 Run 尚无事件证据。") : t("选择一次运行，查看事件证据。")}</p>}
      {run && <details className="full-record"><summary>{t("查看完整记录")}<ChevronDown size={14} /></summary><div className="full-record-content">
        {step && <><section className="record-section"><h4>{t("事件记录")}</h4><RecordFields fields={[
          ['事件名称', t(step.title)], ['消息', step.event.message], ['状态', eventStatus(step.event.status)], ['时间', agentTime(step.event.timestamp, '未提供（无独立时间戳）')],
          ['Event ID', step.event.event_id], ['parent_event_id', step.event.parent_event_id],
          ['原始事件 ID', step.event.original_event_id], ['阶段', step.event.stage], ['事件序号', step.event.ordinal],
          ['记录来源', step.event.origin], ['Incident', step.event.incident_id], ['Trace', step.event.trace_id],
        ]} />{parent && <button className="record-link" title={t("查看已记录的关联事件")} onClick={() => onSelectParent(parent.event.event_id)}>{t("前序关联 · ")}{t(parent.title)}<ArrowLeft size={13} /></button>}</section>
          <section className="record-section"><h4>{t("原始证据字段")}</h4>{fields.length ? <RecordFields fields={fields} raw /> : <p className="explorer-muted">{t("data 为空。")}</p>}
            <details className="raw-evidence"><summary>{t("原始事件 JSON")}<ChevronDown size={14} /></summary><pre>{JSON.stringify(step.event, null, 2)}</pre></details></section></>}
        <RunContext run={run} />
        <p className="record-reading-note">{t("按已记录顺序浏览；事件成功不等于恢复成功，运行结果以上方上下文为准。缺失字段不推断。")}</p>
      </div></details>}
    </div></details>
  </section>;
}

export function ExecutionExplorer({ detail, selectedEventId, onSelectEvent, active = true, busy = false, scope, error, onRetry, emptyMessage, onBrowseSamples }: {
  detail: LoadState<RunDetail>; selectedEventId: string | null; onSelectEvent: (id: string) => void;
  active?: boolean; busy?: boolean; scope: string; error: (code: string) => string; onRetry: () => void;
  emptyMessage?: string; onBrowseSamples?: () => void;
}) {
  const locale = useLocale();
  const trace = detail.kind === 'ready' ? detail.data.trace : [];
  const found = trace.findIndex(step => step.event.event_id === selectedEventId);
  const position = found >= 0 ? found : trace.length - 1;
  const [playing, setPlaying] = useState(false);
  const [inspection, setInspection] = useState<{ eventId: string; key: string; revision: number } | null>(null);
  const step = trace[position];
  const inspected = useMemo(() => step && inspection?.eventId === step.event.event_id
    ? chamberPresentation(step.event).signals.find(signal => signal.key === inspection.key) : undefined, [step, inspection, locale]);
  useEffect(() => { setInspection(null); }, [step?.event.event_id, scope]);
  const nextEventId = trace[position + 1]?.event.event_id;
  const select = (index: number) => { setPlaying(false); if (!busy && active && trace[index]) onSelectEvent(trace[index].event.event_id); };

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => { if (query.matches) setPlaying(false); };
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  useEffect(() => { setPlaying(false); }, [scope]);
  useEffect(() => { if (!active || busy || detail.kind !== 'ready') setPlaying(false); }, [active, busy, detail.kind]);
  useEffect(() => {
    const pause = () => { if (document.hidden) setPlaying(false); };
    document.addEventListener('visibilitychange', pause);
    return () => document.removeEventListener('visibilitychange', pause);
  }, []);
  useEffect(() => {
    if (!playing || !active || busy || detail.kind !== 'ready' || document.hidden) return;
    if (!nextEventId) { setPlaying(false); return; }
    const timer = window.setTimeout(() => onSelectEvent(nextEventId), EVENT_PLAYBACK_MS);
    return () => window.clearTimeout(timer);
  }, [playing, active, busy, detail.kind, nextEventId, onSelectEvent]);

  const playbackControls = <div className="trace-playback"><div className="trace-playback-controls">
    <button className="trace-button" title={t("上一事件")} aria-label={t("上一个历史事件")} disabled={busy || !active || position <= 0} onClick={() => select(position - 1)}><ArrowLeft size={15} /></button>
    <button className="trace-button play-button" title={playing ? t("暂停") : t("播放")} aria-label={playing ? t("暂停历史回放") : t("播放历史回放")} disabled={busy || trace.length < 2 || !active} onClick={() => {
      if (playing) { setPlaying(false); return; }
      if (position >= trace.length - 1) onSelectEvent(trace[0].event.event_id);
      else if (step) onSelectEvent(step.event.event_id);
      setPlaying(true);
    }}>{playing ? <Pause size={15} /> : <Play size={15} />}<span className="agent-play-label">{playing ? t("暂停回放") : t("播放回放")}</span></button>
    <button className="trace-button" title={t("下一事件")} aria-label={t("下一个历史事件")} disabled={busy || !active || position < 0 || position >= trace.length - 1} onClick={() => select(position + 1)}><ArrowRight size={15} /></button>
  </div></div>;

  return <div id="run-evidence" className={`execution-explorer ${busy ? 'run-switching' : ''}`} aria-busy={busy || detail.kind === 'loading'} data-run-id={detail.kind === 'ready' ? detail.data.run.id : undefined}>
    {detail.kind === 'ready' && <header className="agent-record-heading"><div><p>{t(provenanceLabels[detail.data.run.source])} · {agentTime(detail.data.run.started_at, '开始时间未提供')}</p><h2>{runName(detail.data.run)}</h2></div>
      <div><span>{t("运行记录结果")}</span><strong className={`run-${detail.data.run.status}`}>{t(runStatusLabels[detail.data.run.status])}</strong></div></header>}
    <section className="execution-stage" aria-label={t("Cinematic Stage")}>
      {detail.kind !== 'ready' && <header className="explorer-heading"><h2>{t("Execution chamber")}</h2></header>}
      {detail.kind !== 'ready' ? <div className="explorer-empty" role={detail.kind === 'error' ? 'alert' : 'status'}>
        <Fingerprint size={30} strokeWidth={1} />
        <h3>{detail.kind === 'loading' ? t("正在读取 Run 与轨迹…") : detail.kind === 'error' ? t("运行记录暂不可用") : t(emptyMessage) ?? t("选择一次运行，探索每一步。")}</h3>
        <p>{detail.kind === 'error' ? t(error(detail.code)) : detail.kind === 'loading' ? t("读取已落库的执行证据。") : t("选择一条 Run 查看详情与轨迹。")}</p>
        {detail.kind === 'error' && <button className="trace-button" onClick={onRetry}>{t("重试只读查询")}</button>}
        {detail.kind !== 'loading' && onBrowseSamples && <button className="trace-button" onClick={onBrowseSamples}>{t("浏览离线样例")}</button>}
      </div> : <div className="trace-run-content" key={detail.data.run.id}>
        {trace.length > 0 ? <AgentCinematicStage trace={trace} position={position} onSelect={select}
          active={active} busy={busy} controls={playbackControls} inspectedKey={inspected?.key}
          onInspect={signal => { if (step) setInspection(current => ({ eventId: step.event.event_id, key: signal.key, revision: (current?.revision ?? 0) + 1 })); }} />
          : <><p className="explorer-empty" role="status">{t("此 Run 尚无事件证据。")}</p>{playbackControls}</>}
      </div>}
    </section>
    <EvidenceInspector key={step?.event.event_id ?? (detail.kind === 'ready' ? detail.data.run.id : 'empty')} run={detail.kind === 'ready' ? detail.data.run : undefined}
      step={step} trace={trace} inspected={inspected} inspectRevision={inspected ? inspection?.revision : undefined} onSelectParent={id => select(trace.findIndex(item => item.event.event_id === id))} />
  </div>;
}
