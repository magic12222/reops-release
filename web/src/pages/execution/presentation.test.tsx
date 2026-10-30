import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {describe, expect, it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {fixtureSnapshot, type Incident, type WorkbenchEvent} from '../../workbench/contract';
import {ExecutionTimeline} from '../../workbench/ExecutionTimeline';
import {EventEvidence, RunOutcome} from './ExecutionEvidence';
import {eventPhase, linkedModelCalls, modelRelationship, probeSummary, recordedSpan, runOutcome, verificationEvent} from './presentation';

const run = () => fixtureSnapshot().incidents[0];
const step = (evidence: string[], extra: Partial<WorkbenchEvent> = {}): WorkbenchEvent => ({...run().events[4], evidence, ...extra});

describe('Execution outcomes and evidence integrity', () => {
  it.each(['observing', 'diagnosing', 'executing', 'verifying'] as const)('keeps %s running despite successful steps and checks', status => {
    const incident = {...run(), status};
    expect(runOutcome(incident).label).toBe('Running');
    expect(renderToStaticMarkup(<RunOutcome incident={incident} onSelect={() => {}}/>)).not.toContain('>Succeeded<');
  });
  it('requires the recovered terminal state and passed verification together', () => {
    expect(runOutcome(run()).label).toBe('Succeeded');
    expect(runOutcome({...run(), verification: {status: 'pending', checks: []}}).label).toBe('Unconfirmed');
    expect(runOutcome({...run(), verification: {status: 'passed', checks: []}}).label).toBe('Unconfirmed');
    expect(runOutcome({...run(), status: 'unknown'}).label).toBe('Unknown');
    expect(runOutcome({...run(), status: 'failed'}).label).toBe('Failed');
    expect(runOutcome({...run(), status: 'waiting_human'}).label).toBe('Waiting for authorization');
  });
  it('measures only a valid recorded span and never substitutes memory save time', () => {
    const incident = run();
    incident.events.at(-1)!.timestamp = '2030-01-01T00:00:00Z';
    expect(recordedSpan(incident)).toBe(6);
    expect(recordedSpan({...incident, events: []})).toBeNull();
    expect(recordedSpan({...incident, events: [step([], {timestamp: 'invalid'})]})).toBeNull();
    expect(recordedSpan({...incident, events: [step([], {timestamp: '2020-01-01T00:00:00Z'})]})).toBeNull();
  });
  it('distinguishes action reservation, safety, execution and verification by recorded codes', () => {
    expect(eventPhase(step(['event=dependency_action_reserved']))).toBe('authorization');
    expect(eventPhase(step(['event=dependency_safety_passed']))).toBe('safety');
    expect(eventPhase(step([], {title: 'safety_and_target_policy_passed'}))).toBe('safety');
    expect(eventPhase(step([], {title: 'Looks safe!'}))).toBe('recovery_decision');
    const html = renderToStaticMarkup(<EventEvidence event={step(['event=dependency_action_reserved', 'authorization_consumed_by_a=true', 'step=postgres', 'action_id=actual-action'])} incident={run()}/>);
    expect(html).toContain('single action authorization');
    expect(html).toContain('actual-action');
    expect(html).not.toContain('allowed_actions=');
  });
  it('shows failure reasons and false/zero checks without creating a denial', () => {
    const html = renderToStaticMarkup(<EventEvidence event={step(['reason=dependency_scope_budget_or_order_rejected', 'passed=False', 'check=0'], {status: 'failed'})} incident={run()}/>);
    expect(html).toContain('dependency_scope_budget_or_order_rejected');
    expect(html).toContain('>False<'); expect(html).toContain('>0<');
    expect(html).not.toContain('authorization was consumed');
  });
  it('keeps repeated source keys and full provenance accessible', () => {
    const html = renderToStaticMarkup(<EventEvidence event={step(['source=dependency_audit_projection', 'source=current_identity_scope_budget_and_order_checks', 'source_sha256=actual-hash'])} incident={run()}/>);
    expect(html).toContain('Recorded basis: current_identity_scope_budget_and_order_checks');
    expect(html).toContain('source_sha256=actual-hash');
  });
  it('links checks by exact observation, refusing ambiguous or unrelated evidence', () => {
    const event = step(['observation_id=obs-1;business=passed'], {stage: 'verification', id: 'verification'});
    const incident = {...run(), events: [event]};
    expect(verificationEvent(incident, 'fresh_business_read_and_sql;observation_id=obs-1')?.id).toBe('verification');
    expect(verificationEvent(incident, 'observation_id=obs-10')).toBeUndefined();
    expect(verificationEvent({...incident, events: [event, {...event, id: 'probe'}]}, 'observation_id=obs-1')).toBeUndefined();
  });
  it('does not relate model calls by stage, timestamp or run membership', () => {
    const calls = run().model_calls;
    expect(linkedModelCalls(run().events[3], calls)).toEqual([]);
    expect(linkedModelCalls(step([`model_call_id=${calls[0].id}`]), calls)).toEqual(calls);
    const fixed = {...run(), events: [step(['profile=dependency-audit-v1'])]};
    expect(modelRelationship(fixed)).toContain('model request record');
    expect(modelRelationship({...fixed, model_calls: [{...fixed.model_calls[0],status:'failed',response:null}]})).not.toContain('provide analysis');
    expect(modelRelationship({...fixed, model_calls: []})).toContain('no model request is exposed');
  });
  it('never gives skipped, unknown or waiting steps a successful check icon', () => {
    for (const status of ['skipped', 'unknown', 'waiting_human'] as const) {
      const html = renderToStaticMarkup(<ExecutionTimeline events={[step([], {status})]} onSelect={() => {}}/>);
      expect(html).not.toContain('lucide-check');
      expect(html).toContain(status==='waiting_human'?'Waiting for operator':status==='skipped'?'Skipped':'Unknown');
      expect(html).toContain(`data-status="${status}"`);
    }
  });
  it('keeps source-less empty verification honest', () => {
    const incident: Incident = {...run(), status: 'unknown', events: [], verification: {status: 'unknown', checks: []}};
    const html = renderToStaticMarkup(<RunOutcome incident={incident} onSelect={() => {}}/>);
    expect(html).toContain('No check records');
    expect(html).toContain('Unavailable');
    expect(html).not.toContain('Inspect event');
  });
  it('summarizes actual probes without concealing conflicting business and check results', () => {
    expect(probeSummary(step(['query=SELECT 1', 'passed=True']), 'sql')).toBe('SELECT 1 · Passed');
    expect(probeSummary(step(['query=SELECT 1', 'passed=False']), 'sql')).toBe('SELECT 1 · Failed');
    expect(probeSummary(step(['business_passed=True', 'passed=False', 'status_code=200']), 'business')).toBe('HTTP 200 · Business passed · check failed');
    expect(probeSummary(step([]), 'business')).toBe('Unknown');
  });
});
