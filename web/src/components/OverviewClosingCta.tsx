import { t, useLocale } from '../i18n';
import { ArrowUpRight } from 'lucide-react';
import { Reveal } from './Primitives';

export function OverviewClosingCta() {
  useLocale();
  return <section className="footer overview-closing-cta" aria-label={t("Explore recovery")}><div className="shell"><Reveal>
    <div className="footer-eyebrow">{t("THE NEXT RESPONSE STARTS HERE.")}</div>
    <h2>{t("Failures happen.")}<br /><span>{t("Recovery shouldn't wait.")}</span></h2>
    <a href="/recovery" className="button primary">{t("Explore recovery ")}<ArrowUpRight size={17} /></a>
  </Reveal></div></section>;
}
