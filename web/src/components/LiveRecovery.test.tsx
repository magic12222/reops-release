import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LiveRecoveryView } from './LiveRecovery';
import type { LiveRecoveryViewProps } from './LiveRecovery';
import { RecoveryDemo } from './RecoveryDemo';
import type { EventRecord, RunRecord } from '../types/dashboard';

const run: RunRecord = {
  id: 'run-1', incident_id: 'incident-1', trace_id: 'trace-1', case_id: 'case-1', fault_id: null,
  source: 'real', status: 'unknown', started_at: null, finished_at: null,
  model_calls: null, action_count: null, recovery_latency_ms: null, success: null, metadata: {},
};
const event: EventRecord = {
  event_id: 'event-1', run_id: run.id, incident_id: run.incident_id, trace_id: run.trace_id,
  case_id: run.case_id, ordinal: 0, parent_event_id: null, stage: 'observe', status: null,
  timestamp: null, message: 'Observation recorded', source: 'real', origin: 'decision_trace',
  original_event_id: 'raw-1', data: { value: 'sample' },
};
const base: LiveRecoveryViewProps = {
  source: 'real', onSource: () => {}, onRefresh: () => {}, selectedId: null,
  onSelectRun: () => {}, selectedEventId: null, onSelectEvent: () => {},
  status: { kind: 'loading' }, runs: { kind: 'loading' }, detail: { kind: 'idle' },
  connection: 'off',
};
const render = (props: Partial<LiveRecoveryViewProps>) => renderToStaticMarkup(<LiveRecoveryView {...base} {...props} />);

describe('read-only workbench states', () => {
  it('retains all source choices and propagates list failure to the chamber without a sample fallback', () => {
    const html = render({ runs: { kind: 'error', code: 'unavailable' } });
    expect(html).toContain('value="real"');
    expect(html).toContain('value="offline_fixture"');
    expect(html).toContain('value="simulation"');
    expect(html).toContain('运行记录暂不可用');
    expect(html).toContain('浏览离线样例');
    expect(html).not.toContain('选择一次运行，探索每一步');
    expect(html).not.toContain('agent-chamber-deck');
  });
  it('keeps simulation as the explicit default mode', () => {
    const html = renderToStaticMarkup(<RecoveryDemo />);
    expect(html).not.toContain('workspace-navigation');
    expect(html).toContain('SIMULATION · 演示数据');
    expect(html).toContain('恢复模拟');
    expect(html).not.toContain('C API 不可达');
  });

  it('shows loading and empty results without demo fallback', () => {
    expect(render({})).toContain('正在读取运行记录');
    const html = render({ runs: { kind: 'ready', data: { items: [], total: 0, limit: 50, offset: 0 } } });
    expect(html).toContain('此来源暂无运行记录');
    expect(html).toContain('没有用演示数据补位');
  });

  it('shows unavailable probe, 404 and API failure honestly', () => {
    const html = render({ status: { kind: 'ready', data: { status: 'unavailable', source: 'real', components: {
      api: 'unavailable', postgres: 'unavailable', redis: 'unavailable', users: 'unavailable', control: 'unavailable',
    } } }, detail: { kind: 'error', code: 'not_found' }, runs: { kind: 'error', code: 'unavailable' } });
    expect(html).toContain('未配置或不可达');
    expect(html).toContain('记录不存在或已变化');
    expect(html).toContain('C API 不可达');
  });

  it('keeps null metrics and synthetic event timestamps unavailable', () => {
    const html = render({ selectedId: run.id,
      runs: { kind: 'ready', data: { items: [run], total: 1, limit: 50, offset: 0 } },
      detail: { kind: 'ready', data: { run, trace: [{ event, title: 'Observation', time: '无独立时间戳' }] } } });
    expect(html).toContain('REAL · 实际证据');
    expect(html).toContain('未定义（口径待 C5）');
    expect(html).toContain('无独立时间戳');
    expect(html).toContain('未确认');
    expect(html).toContain('Observation recorded');
    expect(html).not.toContain('8.4s');
  });

  it('keeps the committed trace visible while SSE reconnects and shows parent linkage', () => {
    const html = render({ selectedId: run.id, connection: 'reconnecting',
      detail: { kind: 'ready', data: { run, trace: [{ event, title: 'Observation', time: '无独立时间戳' }] } } });
    expect(html).toContain('正在自动重连');
    expect(html).toContain('保留快照');
    expect(html).toContain('parent_event_id');
    expect(html).toContain('事件记录');
    expect(html).toContain('Observation recorded');
  });

  it('shows offline provenance independently of unavailable probes and stale connection state', () => {
    const fixtureRun = { ...run, source: 'offline_fixture' as const };
    const fixtureEvent = { ...event, source: 'offline_fixture' as const };
    const html = render({ source: 'offline_fixture', selectedId: fixtureRun.id, connection: 'reconnecting', status: { kind: 'error', code: 'unavailable' },
      detail: { kind: 'ready', data: { run: fixtureRun,
        trace: [{ event: fixtureEvent, title: 'Observation', time: '无独立时间戳' }] } } });
    expect(html).toContain('OFFLINE FIXTURE');
    expect(html).toContain('本地样例 · 可离线浏览');
    expect(html).not.toContain('正在自动重连');
    expect(html).not.toContain('C API 不可达');
    expect(html).not.toContain('当前系统探测');
    expect(html).toContain('Observation recorded');
  });

  it('renders one node per actual event without completing conceptual stages', () => {
    const failed = { ...event, event_id: 'event-2', ordinal: 1, stage: 'verification' as const, status: 'failed' as const };
    const html = render({ detail: { kind: 'ready', data: { run, trace: [
      { event, title: 'Observation', time: '无独立时间戳' },
      { event: failed, title: 'Verification', time: '无独立时间戳' },
    ] } }, selectedEventId: event.event_id });
    expect(html.match(/class="event-index"/g)).toHaveLength(2);
    expect(html).toContain('事件失败');
    expect(html).not.toContain('Recovery decision');
    expect(html).toContain('只读回放');
    expect(html).toContain('aria-label="上一个历史事件" disabled');
    expect(html).not.toContain('aria-label="下一个历史事件" disabled');
    expect(html).toContain('原始事件 JSON');
    expect(html).not.toContain('class="raw-evidence" open');
  });

  it('shows unavailable source and leaves empty trace controls disabled', () => {
    expect(render({ runs: { kind: 'error', code: 'unavailable' } })).toContain('UNAVAILABLE');
    const html = render({ detail: { kind: 'ready', data: { run, trace: [] } } });
    expect(html).toContain('此 Run 尚无事件证据');
    expect(html).toMatch(/aria-label="播放历史回放" disabled/);
    expect(html).not.toContain('class="event-index"');
  });
  it('hides the previous snapshot immediately while a different Run loads', () => {
    const html = render({ selectedId: 'pending-run', selectedEventId: event.event_id,
      detail: { kind: 'ready', data: { run, trace: [{ event, title: 'Observation', time: '无独立时间戳' }] } } });
    expect(html).toContain('正在切换运行 · 等待关联证据');
    expect(html).not.toContain('data-run-id="run-1"');
    expect(html).not.toContain('data-run-id="pending-run"');
    expect(html).not.toContain('aria-label="播放历史回放"');
    expect(html).not.toContain('class="event-index"');
    expect(html).not.toContain('Observation recorded');
    expect(html).toContain('正在读取 Run 与轨迹');
  });
  it('removes repeated technical labels from nodes while retaining raw evidence and ID access', () => {
    const html = render({ selectedId: run.id,
      detail: { kind: 'ready', data: { run, trace: [{ event, title: 'Observation', time: '无独立时间戳' }] } } });
    expect(html).not.toContain('node-ordinal');
    expect(html).not.toContain('node-message');
    expect(html).not.toContain('未浏览');
    expect(html).not.toContain('EXECUTION STAGE');
    expect(html).toContain('原始事件 JSON');
    expect(html).toContain('复制完整 Run ID');
    expect(html).not.toContain('阅读说明');
    expect(html).toContain('查看完整记录');
    expect(html).not.toContain('Run details');
    expect(html).not.toContain('证据视图');
  });

  it('hides evidence from a different source even if the run ID matches', () => {
    const html = render({ source: 'offline_fixture', selectedId: run.id,
      detail: { kind: 'ready', data: { run, trace: [{ event, title: 'Observation', time: '无独立时间戳' }] } } });
    expect(html).not.toContain('Observation recorded');
    expect(html).toContain('正在读取 Run 与轨迹');
  });
  it('folds long recorded logs without losing evidence or inferring results', () => {
    const log = 'Recorded tool log\n'.repeat(24);
    const recorded = { ...event, data: { value: { stdout: log, executor_called: false, status: null } } };
    const html = render({ selectedId: run.id, detail: { kind: 'ready', data: { run,
      trace: [{ event: recorded, title: 'Observation', time: '无独立时间戳' }] } } });
    expect(html).toContain('class="evidence-value"');
    expect(html).not.toContain('class="evidence-value" open');
    expect(html).toContain(`<pre>${log}</pre>`);
    expect(html).toContain('<dd>false</dd>');
    expect(html).toContain('<dd>null</dd>');
    expect(html).toContain('状态未提供');
    expect(html).toContain('未确认');
  });
  it('keeps evidence ahead of folded payload identifiers without dropping original fields', () => {
    const recorded = { ...event, data: { value: { schema_version: '1.0', action_id: 'recorded-action',
      action: 'restart_service', target: 'postgres', requires_approval: false } } };
    const html = render({ selectedId: run.id, detail: { kind: 'ready', data: { run,
      trace: [{ event: recorded, title: 'Observation', time: '无独立时间戳' }] } } });
    expect(html).toContain('class="full-record"');
    expect(html).not.toContain('class="full-record" open');
    expect(html).toContain('原始证据字段');
    expect(html).toContain('<dd>recorded-action</dd>');
    expect(html).toContain('<dd>false</dd>');
  });
  it('keeps exactly three named playback controls with tooltips and one focal progress display', () => {
    const html = render({ selectedId: run.id, detail: { kind: 'ready', data: { run,
      trace: [{ event, title: 'Observation', time: '无独立时间戳' }] } } });
    const controls = html.split('class="trace-playback-controls"')[1].split('</div>')[0];
    expect(controls.match(/<button /g)).toHaveLength(3);
    expect(controls).toContain('title="上一事件"');
    expect(controls).toContain('title="播放"');
    expect(controls).toContain('title="下一事件"');
    expect(html).not.toContain('重置历史回放');
    expect(html).not.toContain('>Explore<');
    expect(html).not.toContain('playback-note');
    expect(html.match(/class="chamber-ordinal"/g)).toHaveLength(1);
  });
});
