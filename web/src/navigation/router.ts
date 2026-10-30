import { useSyncExternalStore } from 'react';
import { resolveRoute } from './routes';

type Point = { x: number; y: number };
type Entry = { key: string; point: Point };
type Route = ReturnType<typeof resolveRoute> & { key: string; action: 'initial' | 'push' | 'pop'; point: Point };
const origin = { x: 0, y: 0 };
const serverRoute: Route = { page: 'overview', hash: '', href: '/', key: 'server', action: 'initial', point: origin };
let current = serverRoute;
let started = false;
let pending = false;
const listeners = new Set<() => void>();
const positions = new Map<string, Point>();
let scrollTimer = 0;
const emit = () => listeners.forEach(listener => listener());
const entry = (): Entry | undefined => window.history.state?.reopsNavigation;
const writeEntry = (value: Entry, href?: string) => window.history.replaceState({ ...window.history.state, reopsNavigation: value }, '', href);
const newEntry = (): Entry => ({ key: crypto.randomUUID(), point: origin });
function saveScroll() {
  if (pending) return;
  window.clearTimeout(scrollTimer);
  const point = { x: window.scrollX, y: window.scrollY };
  positions.set(current.key, point);
  writeEntry({ key: current.key, point });
}
function recordScroll() {
  if (pending) return;
  positions.set(current.key, { x: window.scrollX, y: window.scrollY });
  window.clearTimeout(scrollTimer);
  // Persist for refresh without repeatedly rewriting history during a scroll gesture.
  scrollTimer = window.setTimeout(saveScroll, 200);
}

export function initializeRouter() {
  if (started) return;
  started = true;
  window.history.scrollRestoration = 'manual';
  const route = resolveRoute(new URL(window.location.href));
  const initial = entry() ?? newEntry();
  writeEntry(initial, route.href);
  current = { ...route, ...initial, action: 'initial' };
  pending = true;
  positions.set(initial.key, initial.point);
  window.addEventListener('scroll', recordScroll, { passive: true });
  window.addEventListener('pagehide', saveScroll);
  window.addEventListener('popstate', () => {
    window.clearTimeout(scrollTimer);
    if (!pending) positions.set(current.key, { x: window.scrollX, y: window.scrollY });
    const route = resolveRoute(new URL(window.location.href));
    const target = entry() ?? newEntry();
    target.point = positions.get(target.key) ?? target.point;
    writeEntry(target, route.href);
    current = { ...route, ...target, action: 'pop' };
    pending = true;
    emit();
  });
  // Also support a legacy hash pasted into the address bar of the running app.
  window.addEventListener('hashchange', () => {
    const route = resolveRoute(new URL(window.location.href));
    if (route.href === current.href) return;
    const target = newEntry();
    writeEntry(target, route.href);
    current = { ...route, ...target, action: 'push' };
    pending = true;
    emit();
  });
  document.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href]') : null;
    if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
    const url = new URL(link.href);
    if (url.origin !== window.location.origin || resolveRoute(url).page === 'not-found') return;
    event.preventDefault();
    navigate(url.href);
  });
}

export function navigate(href: string) {
  const route = resolveRoute(new URL(href, window.location.href));
  if (route.href === current.href) return;
  // Clicking the selected primary page keeps its local anchor/position as well.
  if (route.page === current.page && !route.hash && new URL(href, window.location.href).search === window.location.search) return;
  saveScroll();
  const target = newEntry();
  window.history.pushState({ reopsNavigation: target }, '', route.href);
  current = { ...route, ...target, action: 'push' };
  pending = true;
  emit();
}

export function finishNavigation() { pending = false; saveScroll(); }
export function useRoute() {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener); }; }, () => current, () => serverRoute);
}
