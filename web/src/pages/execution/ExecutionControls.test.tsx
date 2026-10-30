import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {describe, expect, it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {fixtureSnapshot, type WorkbenchEvent} from '../../workbench/contract';
import {ExecutionPhaseNavigation, ExecutionRefreshStatus} from './ExecutionControls';
import {EventEvidence, RunOutcome} from './ExecutionEvidence';

const incident = () => fixtureSnapshot().incidents[0];
const feed = {sample: false, active: true, error: false, loaded: true, monitorError: false};
const event = (extra: Partial<WorkbenchEvent> = {}): WorkbenchEvent => ({...incident().events[4], ...extra});

describe('Execution refresh and recorded-phase navigation', () => {
  it('distinguishes polling from both a completed run and an executing run', () => {
    for (const status of ['recovered', 'executing'] as const) {
      const html = renderToStaticMarkup(<><RunOutcome incident={{...incident(), status}} onSelect={() => {}}/><ExecutionRefreshStatus {...feed} updatedAt="2026-10-29T01:02:03Z"/></>);
      expect(html).toContain(`${status === 'recovered' ? 'Succeeded' : 'Running'}</span>`);
      expect(html).toContain('DATA POLL · 750ms');
      expect(html).toContain('Last received 09:02:03 CST');
      expect(html).not.toMatch(/UPDATING|is-working|SSE|SUBSCRIBED/);
    }
  });
  it.each([
    [{loaded: false}, 'DATA · CONNECTING'],
    [{error: true}, 'DATA · RECONNECTING'],
    [{active: false}, 'DATA REFRESH PAUSED'],
    [{sample: true}, 'SAMPLE · NO EXECUTION'],
  ])('shows only the actual refresh mode for %j', (extra, label) => {
    const html = renderToStaticMarkup(<ExecutionRefreshStatus {...feed} {...extra}/>);
    expect(html).toContain(label);
    expect(html).not.toContain('Last received');
  });
  it('keeps monitor availability independent of snapshot polling', () => {
    const html = renderToStaticMarkup(<ExecutionRefreshStatus {...feed} monitorError/>);
    expect(html).toContain('DATA POLL · 750ms');
    expect(html).toContain('Monitor feed unavailable');
    expect(html).not.toContain('DATA · RECONNECTING');
  });
  it('marks the selected historical phase instead of the latest executing phase', () => {
    const events = incident().events;
    const html = renderToStaticMarkup(<ExecutionPhaseNavigation events={events} selected={events[0]} onSelect={() => {}}/>);
    expect(html).toContain('Jump to phase');
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1);
    expect(html).toMatch(/aria-pressed="true"[^>]*><span>Observe/);
    expect(html).not.toContain('lucide-check');
    expect(html).not.toContain('data-current');
  });
  it('lists only recorded phases, keeping their first occurrence order and actual status', () => {
    const events = [event({id: 'detect', stage: 'failure_detection'}),
      event({id: 'auth', evidence: ['event=dependency_action_reserved']}),
      event({id: 'safe', evidence: ['event=dependency_safety_passed'], status: 'skipped'}),
      event({id: 'auth2', evidence: ['event=dependency_action_reserved'], status: 'unknown'})];
    const html = renderToStaticMarkup(<ExecutionPhaseNavigation events={events} selected={events[1]} onSelect={() => {}}/>);
    expect(html.indexOf('<span>Detect')).toBeLessThan(html.indexOf('<span>Authorization'));
    expect(html.indexOf('<span>Authorization')).toBeLessThan(html.indexOf('<span>Safety Guard'));
    expect(html).toContain('2 recorded events · latest event: Unknown');
    expect(html).toContain('1 recorded event · latest event: Skipped');
    expect(html).not.toMatch(/<span>(Execute|Verify|Learn|Observe)<\/span>/);
    expect(html).not.toMatch(/completed|progressbar|lucide-check/);
  });
  it('leaves empty runs without invented phase buttons', () => {
    const html = renderToStaticMarkup(<ExecutionPhaseNavigation events={[]} onSelect={() => {}}/>);
    expect(html).toContain('No recorded phases');
    expect(html).not.toContain('<button');
  });
  it('deduplicates exact display fields while preserving conflicts and the original record', () => {
    const sample = event({detail: 'Keep this actual failure detail', evidence: ['passed=False', 'passed=False', 'passed=True', 'source=actual-check', 'source=actual-check']});
    const html = renderToStaticMarkup(<EventEvidence event={sample} incident={incident()}/>);
    expect(html.match(/<dt>Check passed<\/dt>/g)).toHaveLength(2);
    expect(html).toContain('>False<'); expect(html).toContain('>True<');
    expect(html).toContain('Recorded basis: actual-check</p>');
    expect(html.match(/passed=False/g)).toHaveLength(2);
    expect(html).toContain('Keep this actual failure detail');
  });
  it('hides only exact repetitive audit boilerplate and keeps its original text accessible', () => {
    const detail = 'Recorded automatic dependency recovery event. Original audit remains unchanged.';
    const html = renderToStaticMarkup(<EventEvidence event={event({detail, evidence: ['profile=dependency-audit-v1']})} incident={{...incident(), model_calls: []}}/>);
    expect(html).not.toContain(`<p>${detail}</p>`);
    expect(html).toContain(detail);
    expect(html).not.toContain('execution-association');
    const extra = renderToStaticMarkup(<EventEvidence event={event({detail: detail + ' Additional failure evidence.'})} incident={incident()}/>);
    expect(extra).toContain(`<p>${detail} Additional failure evidence.</p>`);
  });
});
