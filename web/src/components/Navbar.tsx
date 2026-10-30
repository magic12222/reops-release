import { setLocale, t, useLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import { Menu, X } from 'lucide-react';
import { pages, paths } from '../navigation/routes';
import { useRoute } from '../navigation/router';
import './Navbar.css';

export function Navbar() {
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const route = useRoute();
  const menuRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      setScrolled(window.scrollY > 30);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    update();
    window.addEventListener('scroll', schedule, { passive: true });
    return () => { cancelAnimationFrame(frame); window.removeEventListener('scroll', schedule); };
  }, []);
  useEffect(() => { setOpen(false); }, [route]);
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); menuRef.current?.focus(); } };
    const query = window.matchMedia('(min-width: 1101px)');
    const resize = () => { if (query.matches) setOpen(false); };
    document.addEventListener('keydown', close); query.addEventListener('change', resize);
    return () => { document.removeEventListener('keydown', close); query.removeEventListener('change', resize); };
  }, [open]);
  return <><a className="skip-link" href="#main">{t("跳到主要内容")}</a><header className={`navbar ${scrolled ? 'scrolled' : ''}`}>
    <a className="navbar-brand" href={paths.overview} aria-label={t("ReOps 首页")} onClick={() => setOpen(false)}><img src="/reops-logo.png" alt="ReOps" width={865} height={256} /></a>
    <nav id="main-navigation" aria-label={t("主导航")} className={open ? 'open' : ''}>{pages.map(({ id, label, href }) => <a key={id} href={href} aria-current={route.page === id ? 'page' : undefined} onClick={() => setOpen(false)}>{t(label)}</a>)}</nav>
    <button type="button" className="locale-toggle" lang={locale === 'zh-CN' ? 'en' : 'zh-CN'}
      aria-label={t(locale === 'zh-CN' ? '切换为英文' : '切换为中文')}
      title={t('语言')} onClick={() => setLocale(locale === 'zh-CN' ? 'en' : 'zh-CN')}>
      {locale === 'zh-CN' ? 'EN' : '中文'}
    </button>
    <button ref={menuRef} className="menu-toggle icon-button" aria-label={open ? t('关闭导航') : t('打开导航')} aria-controls="main-navigation" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? <X size={20} /> : <Menu size={20} />}</button>
  </header></>;
}
