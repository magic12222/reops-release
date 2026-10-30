import { t, useLocale, getLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, RefreshCw } from 'lucide-react';
import { DashboardApiError, readSystemStatus } from '../data/api';
import { agentSource } from '../data/agentSource';
import { subscribeRun } from '../data/live';
import type { LiveConnectionState } from '../data/live';
import { formatEvidenceTime, provenanceLabels, runStatusLabels, toReadTrace } from '../data/adapter';
import type { ReadTraceStep } from '../data/adapter';
import type { Provenance, RunPage, RunRecord, SystemStatus } from '../types/dashboard';
import { preferredRunId, runName } from '../data/traceExplorer';
import { ExecutionExplorer } from './ExecutionExplorer';
import { linkedRun } from '../data/traceLink';

export type LoadState<T> = { kind: 'idle' } | { kind: 'loading' } | { kind: 'ready'; data: T } | { kind: 'error'; code: string };
export interface RunDetail { run: RunRecord; trace: ReadTraceStep[] }

function errorCode(error: unknown): string {
  return error instanceof DashboardApiError ? error.code : 'invalid_response';
}

function errorText(code: string): string {
  if (code === 'not_found') return '记录不存在或已变化，请刷新列表。';
  if (code === 'unavailable') return 'C API 不可达。请确认服务已启动，页面不会切换为演示数据。';
  if (code === 'invalid_response') return 'C API 返回的数据格式或关联信息无效。';
  return 'C API 请求失败；未使用演示数据填充。';
}

const componentNames = { api: 'FastAPI', postgres: 'PostgreSQL', redis: 'Redis', users: 'GET /users', control: 'A control plane' } as const;
const componentLabels = { healthy: '健康', unhealthy: '异常', unknown: '未知', unavailable: '不可用' } as const;
const overallLabels = { healthy: '健康', degraded: '降级', unknown: '未知', unavailable: '未配置或不可达' } as const;
const sourceOptions: Provenance[] = ['real', 'offline_fixture', 'simulation'];
const followsLiveJournal = (source: Provenance) => source === 'real';

function SystemReadout({ state }: { state: LoadState<SystemStatus> }) {
  useLocale();
  return <div className="live-panel"><h3>{t("reops-lab 系统状态 ")}<small>{t("原 API 场景的实时探测 · 不代表选中历史 Run 的结果")}</small></h3>
    {state.kind === 'loading' || state.kind === 'idle' ? <p role="status">{t("正在读取系统状态…")}</p>
      : state.kind === 'error' ? <p role="alert">{t(errorText(state.code))}</p>
        : <><p className="live-overall">{t("当前：")}{t(overallLabels[state.data.status])} <span>{t("LIVE PROBE")}</span></p>
          <div className="live-services">{(Object.keys(componentNames) as (keyof typeof componentNames)[]).map(key =>
            <div key={key} className={`live-service state-${state.data.components[key]}`}><span>{t(componentNames[key])}</span><strong>{t(componentLabels[state.data.components[key]])}</strong></div>)}</div></>}
  </div>;
}

function RunList({ state, selectedId, pendingId, onSelect, onRetry, error }: { state: LoadState<RunPage>; selectedId: string | null; pendingId: string | null; onSelect: (id: string) => void; onRetry: () => void; error: (code: string) => string }) {
  useLocale();
  return <aside className="run-explorer" aria-label={t("Run Explorer")}><header className="explorer-heading"><h2>{t("Runs")}</h2><span className="explorer-count">{state.kind === 'ready' ? t("{0} / {1}", state.data.items.length, state.data.total) : '—'}</span></header>
    {state.kind === 'loading' || state.kind === 'idle' ? <p className="run-list-empty" role="status">{t("正在读取运行记录…")}</p>
      : state.kind === 'error' ? <div className="run-list-empty" role="alert"><p>{t(error(state.code))}</p><button className="trace-button" onClick={onRetry}>{t("重试只读查询")}</button></div>
        : state.data.items.length === 0 ? <p className="run-list-empty" role="status">{t("此来源暂无运行记录。没有用演示数据补位。")}</p>
          : <><div className="live-run-list">{state.data.items.map((run, index) => <button key={run.id}
              className={`${selectedId === run.id ? 'selected' : ''} ${pendingId === run.id ? 'pending-run' : ''}`} title={run.id} onClick={() => onSelect(run.id)} aria-pressed={selectedId === run.id}>
              <span className="agent-run-ordinal">{String(index + 1).padStart(2, '0')}</span><strong>{runName(run)}</strong>
              <span className="run-list-meta"><span className={`run-result run-${run.status}`}>{t(runStatusLabels[run.status])}</span>
                {run.started_at && !Number.isNaN(Date.parse(run.started_at)) ? <time dateTime={run.started_at} title={formatEvidenceTime(run.started_at)}>
                  {new Intl.DateTimeFormat(getLocale(), { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(run.started_at))}
                </time> : <small>{t("时间未提供")}</small>}</span>
              {pendingId === run.id && <small>{t("加载中")}</small>}
            </button>)}</div></>}
  </aside>;
}

export interface LiveRecoveryViewProps {
  source: Provenance; onSource: (source: Provenance) => void; onRefresh: () => void;
  status: LoadState<SystemStatus>; runs: LoadState<RunPage>; detail: LoadState<RunDetail>;
  selectedId: string | null; onSelectRun: (id: string) => void;
  selectedEventId: string | null; onSelectEvent: (id: string) => void;
  connection: LiveConnectionState | 'off';
  active?: boolean; playbackScope?: string;
  requestedTrace?: string | null;
}

const connectionText: Record<LiveConnectionState | 'off', string> = {
  off: '已保存记录', connecting: '正在连接快照', connected: '快照已连接', reconnecting: '正在自动重连 · 保留快照',
  waiting_for_journal: '等待事件日志', unconfigured: '日志跟随未配置 · 已保存记录', source_error: '日志校验失败 · 保留快照',
  gone: '记录已不存在', invalid_response: '无效快照 · 连接已停止',
};

export function LiveRecoveryView(props: LiveRecoveryViewProps) {
  useLocale();
  const offline = props.source === 'offline_fixture';
  const currentError = (code: string) => offline ? code === 'not_found' ? '本地样例记录不存在。' : '本地样例数据无效，请刷新。' : errorText(code);
  const switching = props.detail.kind === 'ready' && (props.detail.data.run.source !== props.source
    || (props.selectedId !== null && props.detail.data.run.id !== props.selectedId));
  // Keep the validated snapshot in the loader, but never present it under a new selection.
  const visibleDetail: LoadState<RunDetail> = switching ? { kind: 'loading' }
    : props.runs.kind === 'error' && props.detail.kind === 'idle' ? { kind: 'error', code: props.runs.code }
    : props.runs.kind === 'loading' && props.detail.kind === 'idle' ? { kind: 'loading' } : props.detail;
  return <section id="records" className="recovery-section section shell live-recovery agent-intelligence">
    <header className="agent-page-header"><div><span className="agent-page-eyebrow">{t("REOPS / INTELLIGENCE")}</span><h1>{t("Agent ")}<span>{t("Intelligence")}</span></h1><p>{t("聚焦一次执行，读懂每一步的依据。")}</p></div>
      <div className="live-toolbar"><label><span className="sr-only">{t("运行记录来源")}</span><select value={props.source} onChange={event => props.onSource(event.target.value as Provenance)}>
        {sourceOptions.map(source => <option value={source} key={source}>{t(provenanceLabels[source])}</option>)}</select></label>
        {props.source === 'real' && <a className="trace-button" href={`/workbench?source=real${props.requestedTrace ? `&trace=${encodeURIComponent(props.requestedTrace)}` : ''}`}>{t("Open Workbench")}</a>}
        <button className="trace-button" onClick={props.onRefresh} aria-label={t("刷新只读数据")}><RefreshCw size={14} />{t("刷新")}</button></div></header>
    <div className="agent-read-status" role="status"><span className={`status-dot ${props.runs.kind === 'error' || props.detail.kind === 'error' ? '' : 'cyan'}`} />
      {props.runs.kind === 'error' || props.detail.kind === 'error' ? offline ? t("UNAVAILABLE · 本地样例不可用") : t("UNAVAILABLE · API 记录不可用") : switching ? t("正在切换运行 · 等待关联证据") : offline ? t("本地样例 · 可离线浏览") : followsLiveJournal(props.source) && props.selectedId ? t(connectionText[props.connection]) : t("只读运行记录")}
      <span title={t("历史回放仅改变浏览位置，不执行操作")}>{t("只读回放")}</span></div>
    {props.requestedTrace && <p className="agent-read-status" role="status">{t("Requested trace: ")}{props.requestedTrace}. {props.runs.kind === 'ready' && !props.selectedId ? t("No exact match in the loaded C records. B workbench traces may not be imported into C. No other run has been selected.") : t("Selecting only the matching recorded trace.")}</p>}
    <div className="agent-explorer-grid"><RunList state={props.runs} selectedId={props.selectedId} pendingId={switching ? props.selectedId : null} onSelect={props.onSelectRun} onRetry={props.onRefresh} error={currentError} />
      <ExecutionExplorer detail={visibleDetail} selectedEventId={props.selectedEventId} onSelectEvent={props.onSelectEvent}
        active={props.active} busy={switching} scope={props.playbackScope ?? `${props.source}:${props.selectedId ?? ''}`} error={currentError} onRetry={props.onRefresh}
        emptyMessage={props.runs.kind === 'ready' && !props.runs.data.items.length ? '此来源暂无运行记录。' : props.requestedTrace && !props.selectedId ? '未找到对应的运行记录。' : undefined}
        onBrowseSamples={!offline ? () => props.onSource('offline_fixture') : undefined} /></div>
    <div className="agent-support-row"><a href="/recovery" className="page-cross-link">{t("打开恢复模拟器 ↗")}</a>
      {!offline && <details className="agent-support"><summary>{t("当前系统探测")}<ChevronDown size={14} /></summary><SystemReadout state={props.status} /></details>}</div>
  </section>;
}

export function LiveRecovery({ active = true }: { active?: boolean }) {
  useLocale();
  const [source, setSource] = useState<Provenance>('real');
  const [requestedTrace, setRequestedTrace] = useState<string | null>(() => typeof window === 'undefined' ? null : new URLSearchParams(window.location.search).get('trace'));
  const [refresh, setRefresh] = useState(0);
  const [status, setStatus] = useState<LoadState<SystemStatus>>({ kind: 'loading' });
  const [runs, setRuns] = useState<LoadState<RunPage>>({ kind: 'loading' });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<LoadState<RunDetail>>({ kind: 'idle' });
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [connection, setConnection] = useState<LiveConnectionState | 'off'>('off');
  const displayedRunId = useRef<string | null>(null);

  useEffect(() => {
    if (!active) return;
    const trace = new URLSearchParams(window.location.search).get('trace');
    setRequestedTrace(trace);
    if (trace) { setSource('real'); setSelectedId(null); setDetail({ kind: 'idle' }); }
  }, [active]);

  useEffect(() => {
    if (!active || source === 'offline_fixture') return;
    const controller = new AbortController();
    setStatus(current => current.kind === 'ready' ? current : { kind: 'loading' });
    readSystemStatus(controller.signal).then(data => {
      if (!controller.signal.aborted) setStatus({ kind: 'ready', data });
    })
      .catch(error => { if (!controller.signal.aborted) setStatus({ kind: 'error', code: errorCode(error) }); });
    return () => controller.abort();
  }, [active, source, refresh]);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setRuns(current => current.kind === 'ready' ? current : { kind: 'loading' });
    agentSource(source).readRuns(controller.signal).then(data => {
      if (controller.signal.aborted) return;
      setRuns({ kind: 'ready', data });
      setSelectedId(current => requestedTrace ? linkedRun(data, requestedTrace) : data.items.some(run => run.id === current) ? current : preferredRunId(data.items));
    }).catch(error => {
      if (!controller.signal.aborted) { setRuns({ kind: 'error', code: errorCode(error) }); }
    });
    return () => controller.abort();
  }, [active, source, refresh, requestedTrace]);

  // Discover a new run only within the explicitly selected live source.
  useEffect(() => {
    if (!active || !followsLiveJournal(source) || selectedId) return;
    const controller = new AbortController();
    let busy = false;
    const timer = window.setInterval(() => {
      if (busy) return;
      busy = true;
      agentSource(source).readRuns(controller.signal).then(data => {
        if (controller.signal.aborted) return;
        setRuns({ kind: 'ready', data });
        setSelectedId(requestedTrace ? linkedRun(data, requestedTrace) : preferredRunId(data.items));
      }).catch(error => {
        if (!controller.signal.aborted) setRuns({ kind: 'error', code: errorCode(error) });
      }).finally(() => { busy = false; });
    }, 2000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [active, source, selectedId, refresh, requestedTrace]);

  useEffect(() => {
    if (!active) return;
    if (!selectedId) { setDetail({ kind: 'idle' }); setConnection('off'); return; }
    const controller = new AbortController();
    let stopLive: (() => void) | undefined;
    // Keep the previous, explicitly identified Run visible until the new correlated snapshot is ready.
    setDetail(current => current.kind === 'ready' && current.data.run.source === source ? current : { kind: 'loading' });
    setConnection(followsLiveJournal(source) ? 'connecting' : 'off');
    const reader = agentSource(source);
    Promise.all([reader.readRun(selectedId, controller.signal), reader.readEvents(selectedId, controller.signal)])
      .then(([run, page]) => {
        if (controller.signal.aborted) return;
        if (run.source !== source) throw new DashboardApiError('invalid_response');
        let trace: ReadTraceStep[];
        try { trace = toReadTrace(run, page.items); }
        catch { throw new DashboardApiError('invalid_response'); }
        if (displayedRunId.current !== run.id) setSelectedEventId(source === 'offline_fixture'
          ? trace.find(step => step.event.stage === 'root_cause_analysis')?.event.event_id ?? trace[0]?.event.event_id ?? null : null);
        displayedRunId.current = run.id;
        setDetail({ kind: 'ready', data: { run, trace } });
        if (followsLiveJournal(source)) stopLive = subscribeRun(selectedId, source, snapshot => {
          if (controller.signal.aborted) return;
          try {
            setDetail({ kind: 'ready', data: { run: snapshot.run,
              trace: toReadTrace(snapshot.run, snapshot.events) } });
            setRuns(current => current.kind === 'ready' ? { kind: 'ready', data: {
              ...current.data, items: current.data.items.map(item =>
                item.id === snapshot.run.id ? snapshot.run : item),
            } } : current);
          }
          catch { setConnection('invalid_response'); stopLive?.(); }
        }, state => {
          if (controller.signal.aborted) return;
          setConnection(state);
          if (state === 'gone') setDetail({ kind: 'error', code: 'not_found' });
          if (state === 'invalid_response') setDetail({ kind: 'error', code: 'invalid_response' });
        });
      }).catch(error => { if (!controller.signal.aborted) setDetail({ kind: 'error', code: errorCode(error) }); });
    return () => { controller.abort(); stopLive?.(); };
  }, [active, selectedId, source, refresh]);

  return <><LiveRecoveryView source={source} onSource={value => {
    if (value === source) return;
    displayedRunId.current = null;
    setRequestedTrace(null); setSource(value); setSelectedId(null); setSelectedEventId(null); setRuns({ kind: 'loading' }); setDetail({ kind: 'idle' }); setConnection('off'); setStatus({ kind: 'idle' });
  }} onRefresh={() => {
    setRuns({ kind: 'loading' }); setStatus({ kind: 'loading' });
    setDetail(selectedId ? { kind: 'loading' } : { kind: 'idle' });
    setRefresh(value => value + 1);
  }} status={status} runs={runs} detail={detail} requestedTrace={requestedTrace} connection={connection} active={active} playbackScope={`${source}:${selectedId ?? ''}:${refresh}`}
    selectedId={selectedId} onSelectRun={id => {
      setRequestedTrace(null); if (id !== selectedId) setSelectedId(id);
    }}
    selectedEventId={selectedEventId} onSelectEvent={setSelectedEventId} />
    </>;
}
