import { t, useLocale } from '../i18n';
import './KnowledgeSpeedControl.css';

const speeds = [
  { value: 1000, label: 'Fast', detail: '1.0s' },
  { value: 2200, label: 'Standard', detail: '2.2s' },
  { value: 3600, label: 'Slow', detail: '3.6s' },
];
export function KnowledgeSpeedControl({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  useLocale();
  return <div className="knowledge-speed-control"><span className="knowledge-speed-label">{t("Playback speed")}</span>
    <div className="knowledge-speed-options" role="group" aria-label={t("Knowledge playback speed")}>
      {speeds.map(speed => <button key={speed.value} type="button" aria-label={t("{0} playback", t(speed.label))} aria-pressed={value === speed.value}
        title={t("{0} · {1} per stage", t(speed.label), t(speed.detail))} onClick={() => onChange(speed.value)}><span>{t(speed.label)}</span><small>{t(speed.detail)}</small></button>)}
    </div>
  </div>;
}
