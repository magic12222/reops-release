import { t, useLocale, getLocale } from '../../i18n';
import {ChevronRight} from 'lucide-react';
import type {WorkbenchEvent} from '../../workbench/contract';
import {eventPhase, phaseNames} from './presentation';

export function ExecutionRefreshStatus({sample, active, error, loaded, monitorError, updatedAt}: {
  sample: boolean; active: boolean; error: boolean; loaded: boolean; monitorError: boolean; updatedAt?: string;
}) {
  useLocale();
  const state = sample ? 'sample' : !active ? 'paused' : error ? 'reconnecting' : !loaded ? 'connecting' : 'polling';
  const label = {sample: 'SAMPLE · NO EXECUTION', paused: 'DATA REFRESH PAUSED', reconnecting: 'DATA · RECONNECTING',
    connecting: 'DATA · CONNECTING', polling: 'DATA POLL · 750ms'}[state];
  return <div className="execution-feed-status" aria-label={t("Data refresh status")}>
    <span className="execution-connection" data-state={state}><i aria-hidden="true"/>{t(label)}</span>
    {!sample && updatedAt && <time dateTime={updatedAt} title={t("Last snapshot received: {0}", t(updatedAt))}>{t("Last received ")}{t(new Date(updatedAt).toLocaleTimeString(getLocale(), {timeZone: 'Asia/Shanghai', hour12: false}))}{t(" CST")}</time>}
    {!sample && loaded && monitorError && <span className="execution-monitor-note">{t("Monitor feed unavailable")}</span>}
  </div>;
}

// Navigation over recorded events, not a progress estimate or a fixed lifecycle.
export function ExecutionPhaseNavigation({events, selected, onSelect}: {
  events: WorkbenchEvent[]; selected?: WorkbenchEvent; onSelect: (event: WorkbenchEvent) => void;
}) {
  useLocale();
  const phases = new Map<string, WorkbenchEvent[]>();
  for (const event of events) {
    const phase = eventPhase(event);
    phases.set(phase, [...(phases.get(phase) ?? []), event]);
  }
  return <nav className="execution-phases" aria-label={t("Recovery phase navigation")}>
    <span className="execution-phases-label" title={t("Only phases with recorded events are listed. Missing phases are not inferred.")}>{t("Jump to phase")}</span>
    {[...phases].map(([phase, records]) => {
      const current = selected && eventPhase(selected) === phase;
      const name = phaseNames[phase] ?? phase;
      return <button type="button" key={phase} aria-pressed={!!current}
        title={t("{0} recorded {1} · latest event: {2}", records.length, records.length === 1 ? t('event') : t('events'), t(records.at(-1)!.status.replaceAll('_', ' ')))}
        onClick={() => onSelect(records.find(event => event.id === selected?.id) ?? records[0])}>
        <span>{t(name)}</span><small aria-label={t("{0} recorded events", records.length)}>{records.length}</small><ChevronRight size={11} aria-hidden="true"/>
      </button>;
    })}
    {!phases.size && <span className="execution-phases-empty">{t("No recorded phases")}</span>}
  </nav>;
}
