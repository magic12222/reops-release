import { t, useLocale } from '../i18n';
import { useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { architectureLayers } from '../data/demoData';
import { Brand, Reveal, SectionLabel } from './Primitives';

export function ModuleStory() {
  useLocale();
  const [active, setActive] = useState(0);
  return <section id="team" className="module-story shell section"><Reveal><SectionLabel>{t("CORE CAPABILITIES")}</SectionLabel><div className="section-heading"><h2>{t("Infrastructure.")}<br />{t("Intelligence.")}<br /><span>{t("Observability.")}</span></h2><p>{t("System、Agent、Evaluation 协同工作。")}<br />{t("让恢复从系统状态走向可核对的证据。")}</p></div></Reveal><div className="module-accordion">{architectureLayers.map((layer, i) => <Reveal key={layer.id}><div className={`module-row ${active === i ? 'active' : ''}`}><button onClick={() => setActive(i)} aria-expanded={active === i} aria-controls={`module-body-${i}`}><span>{layer.number}</span><h3>{t(layer.name)}</h3><small>{t(layer.state)}</small><ArrowUpRight size={20} /></button><div id={`module-body-${i}`} className="module-body" hidden={active !== i}><p>{t(layer.description)}</p><div>{layer.modules.map(item => <span key={item.name}>{t(item.name)}</span>)}</div></div></div></Reveal>)}</div><div className="module-result"><span className="result-line" /><Brand /><span className="result-line" /></div></section>;
}
