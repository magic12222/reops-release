import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { describe, expect, it } from 'vitest';
import { fixtureSnapshot } from './contract';
import { eventLabel, eventFact, incidentHistory, recordedSpan } from './incidentPresentation';

describe('incident history presentation', () => {
  it('distinguishes consecutive checks by recorded codes without discarding false or zero', () => {
    const event = {...fixtureSnapshot().incidents[0].events[0], stage:'verification' as const};
    expect(eventLabel({...event,evidence:['event=verification_passed','check=0']})).toBe('Verify 0');
    expect(eventLabel({...event,evidence:['event=verification_passed','check=2']})).toBe('Verify 2');
    expect(eventLabel({...event,evidence:['event=sql_probe']})).toBe('SQL probe');
    expect(eventFact({...event,evidence:['query=SELECT 1','passed=False']})).toBe('SELECT 1 · Failed');
    expect(eventFact({...event,evidence:['business_passed=True','passed=False','status_code=200']})).toContain('check failed');
  });
  it('keeps separate identically named records, ordered by actual start time', () => {
    const incident = fixtureSnapshot().incidents[0];
    const older = { ...incident, id: 'older', trace_id: 'trace-older', title: 'Automatic dependency recovery', started_at: '2026-10-27T03:00:00Z' };
    const newer = { ...older, id: 'newer', trace_id: 'trace-newer', started_at: '2026-10-28T03:00:00Z' };
    expect(incidentHistory([newer, older], '', false).map(item => item.id)).toEqual(['newer', 'older']);
    expect(incidentHistory([newer, older], 'trace-older', false)).toEqual([older]);
    expect(incidentHistory([newer, older], 'OLDER', false)).toEqual([older]);
  });
  it('retains failed, pending and unknown records when filtering for attention', () => {
    const incident = fixtureSnapshot().incidents[0];
    const incidents = (['recovered', 'failed', 'verifying', 'unknown'] as const).map(status => ({ ...incident, id: status, status }));
    expect(incidentHistory(incidents, '', true).map(item => item.status)).toEqual(['failed', 'verifying', 'unknown']);
  });
  it('labels only a valid terminal event span and never invents recovery duration', () => {
    const incident = fixtureSnapshot().incidents[0];
    incident.started_at = '2026-10-28T03:00:00Z';
    incident.events = incident.events.map((event, index) => ({...event,
      timestamp:new Date(Date.parse(incident.started_at)+index*1000).toISOString()}));
    incident.events[6].timestamp = '2026-10-28T03:00:12Z';
    incident.events.at(-1)!.timestamp = '2030-01-01T00:00:00Z';
    expect(recordedSpan(incident)).toBe('12.0s recorded span');
    expect(recordedSpan({ ...incident, status: 'executing' })).toBeNull();
    expect(recordedSpan({ ...incident, events: [] })).toBeNull();
    expect(recordedSpan({ ...incident, started_at: 'invalid' })).toBeNull();
    expect(recordedSpan({ ...incident, started_at: '2026-10-29T03:00:00Z' })).toBeNull();
  });
});
