import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import {describe, expect, it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {fixtureSnapshot} from './contract';
import {recordedSpan as workbenchSpan} from './incidentPresentation';
import {recordedSpan as executionSpan} from '../pages/execution/presentation';
import {RunOutcome} from '../pages/execution/ExecutionEvidence';

describe('shared Workbench and Execution recorded span', () => {
  it('shows the same six seconds for the original seven-second Memory fixture', () => {
    for (const incident of fixtureSnapshot().incidents) {
      expect(workbenchSpan(incident)).toBe('6.0s recorded span');
      expect(executionSpan(incident)).toBe(6);
      expect(renderToStaticMarkup(<RunOutcome incident={incident} onSelect={() => {}}/>)).toContain('>6.0s</dd>');
    }
  });
  it('ignores delayed Memory persistence and event array order with the same rounding', () => {
    const incident = fixtureSnapshot().incidents[0];
    incident.events[6].timestamp = '2026-10-27T09:01:06.260+08:00';
    incident.events[7].timestamp = '2030-01-01T00:00:00Z';
    incident.events.reverse();
    expect(executionSpan(incident)).toBeCloseTo(6.26);
    expect(workbenchSpan(incident)).toBe('6.3s recorded span');
    expect(renderToStaticMarkup(<RunOutcome incident={incident} onSelect={() => {}}/>)).toContain('>6.3s</dd>');
  });
  it('retains unknown duration for missing, invalid or pre-start execution evidence', () => {
    const incident = fixtureSnapshot().incidents[0];
    for (const events of [[], [incident.events[7]], [{...incident.events[6], timestamp:'invalid'}],
      [{...incident.events[6], timestamp:'2020-01-01T00:00:00Z'}]]) {
      expect(executionSpan({...incident, events})).toBeNull();
      expect(workbenchSpan({...incident, events})).toBeNull();
    }
    expect(executionSpan({...incident, started_at:'invalid'})).toBeNull();
    expect(workbenchSpan({...incident, started_at:'invalid'})).toBeNull();
  });
  it('updates only when execution evidence changes, without inventing a final duration', () => {
    const incident = fixtureSnapshot().incidents[0];
    incident.status = 'executing';
    incident.events = incident.events.slice(0, 6);
    expect(executionSpan(incident)).toBe(5);
    expect(workbenchSpan(incident)).toBeNull(); // Workbench history labels terminal records only.
    incident.events.push({...incident.events[5], timestamp:'2026-10-27T09:01:08+08:00'});
    incident.status = 'failed';
    expect(executionSpan(incident)).toBe(8);
    expect(workbenchSpan(incident)).toBe('8.0s recorded span');
  });
});
