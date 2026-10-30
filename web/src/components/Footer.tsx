import { t, useLocale } from '../i18n';
import { ArrowUpRight } from 'lucide-react';
import { Brand } from './Primitives';
import './Footer.css';

export function Footer() {
  useLocale();
  return <footer className="footer footer-compact"><div className="shell">
    <div className="footer-bottom"><div><Brand /><p>{t("Detect. Reason. Recover. Learn.")}</p></div>
      <div className="footer-links"><a href="https://github.com/magic12222/reops-release" target="_blank" rel="noreferrer">{t("GitHub ")}<ArrowUpRight size={14} /></a>
        <a href="/#team">{t("Team ")}<ArrowUpRight size={14} /></a><span>{t("Huawei ICT Competition")}</span></div>
    </div>
    <div className="footer-fine"><span>{t("ReOps / Interactive presentation prototype")}</span>
      <span>{t("受控闭环已有验收记录 · 真实与演示数据分开展示")}</span><span>2026</span></div>
  </div></footer>;
}
