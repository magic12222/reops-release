import type {Incident} from './contract';

// Both pages measure recorded execution evidence, not total Run duration or SLA.
// Experience persistence may arrive later and must not extend this interval.
export function recordedSpanSeconds(incident: Incident): number | null {
  const start = Date.parse(incident.started_at);
  const timestamps = incident.events.filter(event => event.stage !== 'experience_update')
    .map(event => Date.parse(event.timestamp));
  if (!timestamps.length || !Number.isFinite(start)
      || timestamps.some(time => !Number.isFinite(time) || time < start)) return null;
  return (Math.max(...timestamps) - start) / 1000;
}
