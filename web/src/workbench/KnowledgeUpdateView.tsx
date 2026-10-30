import { t, useLocale } from '../i18n';
import type {Incident,Snapshot} from './contract';
import {confirmedNewExperiences,knowledgeUpdateSnapshot} from './knowledgeUpdate';
import {recoveryBaseline} from './recoveryNavigation';
import {KnowledgeJourneyStage} from './KnowledgeJourneyStage';

export function KnowledgeUpdate({data,incident,active}:{data:Snapshot;incident:Incident;active:boolean}){
  useLocale();
  const saved=confirmedNewExperiences(data,incident);
  const snapshot=knowledgeUpdateSnapshot(data,incident,recoveryBaseline(incident.trace_id)??data);
  const failedSave=incident.events.some(event=>event.stage==='experience_update'&&event.status==='failed');
  return <section className="knowledge-update" aria-label={t("Execution knowledge update")}>
    <header className="knowledge-update-heading" aria-live="polite"><span>{t("EXECUTION → KNOWLEDGE")}</span><h2>{saved.length ? t('Execution and new experience added') : t('Execution evidence added to knowledge')}</h2><p>{saved.length ? t("{0} verified {1} saved with this execution.", saved.length, saved.length===1 ? t('experience') : t('experiences')) : failedSave ? t('Experience saving failed. The actual execution evidence is retained; no new experience node is claimed.') : t('No new experience recorded. The fault, actions and verification still extend the graph.')}</p><small>{t("Existing knowledge + this execution")}{saved.length ? t(' + verified new experience') : ''}{t(". Graph relationships come from recorded identifiers and evidence.")}</small></header>
    <KnowledgeJourneyStage key={incident.trace_id} data={snapshot} incident={incident} mode="update" active={active}/>
  </section>;
}
