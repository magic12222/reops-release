import { useSyncExternalStore } from 'react';

export type Locale = 'zh-CN' | 'en';
export const DEFAULT_LOCALE: Locale = 'zh-CN';
export const LOCALE_STORAGE_KEY = 'reops.locale';
export const normalizeLocale = (value: unknown): Locale => value === 'en' ? 'en' : DEFAULT_LOCALE;

function savedLocale(): Locale {
  try { return normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY)); }
  catch { return DEFAULT_LOCALE; }
}

let locale = typeof window === 'undefined' ? DEFAULT_LOCALE : savedLocale();
const listeners = new Set<() => void>();
export const getLocale = () => locale;

function applyLocale(next: Locale) {
  const changed = locale !== next;
  locale = next;
  if (typeof document !== 'undefined') document.documentElement.lang = next;
  if (changed) listeners.forEach(listener => listener());
}

export function setLocale(next: Locale) {
  applyLocale(normalizeLocale(next));
  // A blocked/full storage must never prevent switching in the current session.
  try { window.localStorage.setItem(LOCALE_STORAGE_KEY, locale); } catch { /* session preference remains active */ }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** Every consumer shares this store; changing language never remounts a page. */
export function useLocale() {
  return useSyncExternalStore(subscribe, getLocale, () => DEFAULT_LOCALE);
}

if (typeof window !== 'undefined') {
  applyLocale(locale);
  window.addEventListener('storage', event => {
    try {
      if (event.storageArea === window.localStorage && (event.key === LOCALE_STORAGE_KEY || event.key === null)) {
        applyLocale(savedLocale());
      }
    } catch { /* storage may become unavailable after startup */ }
  });
}
