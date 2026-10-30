import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { describe, expect, it } from 'vitest';
import { fixtureSnapshot } from './contract';
import { workbenchTrace } from './traceProjection';

describe('explicit workbench projection into Agent', () => {
  it('preserves exact incident, trace, event IDs and order without fabricating parent links or zero usage', () => {
    const data = fixtureSnapshot(); data.source = 'real';
    const incident = data.incidents[0];
    const result = workbenchTrace(data, incident.trace_id);
    expect(result.run.id).toBe(incident.id);
    expect(result.run.incident_id).toBe(incident.id);
    expect(result.run.trace_id).toBe(incident.trace_id);
    expect(result.trace.every(step => step.event.run_id === result.run.id
      && step.event.incident_id === incident.id && step.event.trace_id === incident.trace_id)).toBe(true);
    expect(result.run.metadata.c_database_imported).toBe(false);
    expect(result.run.model_calls).toBeNull();
    expect(result.trace.map(step => step.event.event_id)).toEqual(incident.events.map(event => event.id));
    expect(result.trace.every(step => step.event.origin === 'workbench_projection' && step.event.parent_event_id === null)).toBe(true);
  });
  it('rejects samples, absent traces and ambiguous matches', () => {
    const data = fixtureSnapshot();
    expect(() => workbenchTrace(data, data.incidents[0].trace_id)).toThrow();
    data.source = 'real';
    expect(() => workbenchTrace(data, 'missing')).toThrow();
    data.incidents[1].trace_id = data.incidents[0].trace_id;
    expect(() => workbenchTrace(data, data.incidents[0].trace_id)).toThrow();
  });
});
