import { useLayoutEffect } from 'react';
import { finishNavigation, useRoute } from './router';
import { pages } from './routes';

export function ScrollPosition() {
  const route = useRoute();
  useLayoutEffect(() => {
    const label = pages.find(page => page.id === route.page)?.label ?? '页面不存在';
    document.title = route.page === 'overview' ? 'ReOps — Failure is a beginning.' : `${label} · ReOps`;
    const main = document.getElementById('main');
    const page = document.querySelector<HTMLElement>('[data-page]:not([hidden])');
    let anchor: HTMLElement | null = null;
    if (route.hash) {
      try {
        const id = decodeURIComponent(route.hash.slice(1));
        anchor = id === 'main' ? main : page?.querySelector<HTMLElement>(`#${CSS.escape(id)}`) ?? null;
      } catch { /* A malformed fragment does not block page navigation. */ }
    }
    const point = route.action === 'push' ? { x: 0, y: 0 } : route.point;
    const restore = () => {
      if (anchor && (route.action === 'push' || point.y === 0)) {
        const offset = (document.querySelector('.navbar')?.getBoundingClientRect().height ?? 82) + 24;
        window.scrollTo({ top: Math.max(0, anchor.getBoundingClientRect().top + window.scrollY - offset), behavior: 'instant' });
      } else window.scrollTo({ left: point.x, top: point.y, behavior: 'instant' });
    };
    restore();
    if (route.action === 'push') main?.focus({ preventScroll: true });
    // Fonts and an initial read-only response can change page height after mounting.
    // Retry only while a history position is clamped; user input cancels restoration.
    let observer: ResizeObserver | undefined;
    let timer = 0;
    const stop = () => {
      observer?.disconnect(); window.clearTimeout(timer);
      window.removeEventListener('wheel', cancel); window.removeEventListener('touchstart', cancel); window.removeEventListener('keydown', cancel);
      finishNavigation();
    };
    const cancel = () => stop();
    if (point.y > window.scrollY + 1 && page) {
      window.addEventListener('wheel', cancel, { passive: true });
      window.addEventListener('touchstart', cancel, { passive: true });
      window.addEventListener('keydown', cancel);
      observer = new ResizeObserver(() => { restore(); if (window.scrollY >= point.y - 1) stop(); });
      observer.observe(page);
      timer = window.setTimeout(stop, 2000);
    } else finishNavigation();
    return () => {
      observer?.disconnect(); window.clearTimeout(timer);
      window.removeEventListener('wheel', cancel); window.removeEventListener('touchstart', cancel); window.removeEventListener('keydown', cancel);
    };
  }, [route]);
  return null;
}
