import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

function browser(saved: string | null, blocked = false) {
  const values = new Map<string, string>();
  if (saved !== null) values.set('reops.locale', saved);
  const storage = {
    getItem: (key: string) => { if (blocked) throw new Error('blocked'); return values.get(key) ?? null; },
    setItem: (key: string, value: string) => { if (blocked) throw new Error('blocked'); values.set(key, value); },
  };
  const handlers: Record<string, (event: unknown) => void> = {};
  const document = { documentElement: { lang: '' } };
  vi.stubGlobal('document', document);
  vi.stubGlobal('window', { localStorage: storage, addEventListener: (name: string, handler: (event: unknown) => void) => { handlers[name] = handler; } });
  return { storage, handlers, document };
}

describe('shared locale preference', () => {
  it('restores English before rendering any route and saves both switch directions', async () => {
    const { storage, document } = browser('en');
    const { getLocale, setLocale } = await import('./locale');
    expect(getLocale()).toBe('en');
    expect(document.documentElement.lang).toBe('en');
    setLocale('zh-CN');
    expect(getLocale()).toBe('zh-CN');
    expect(storage.getItem('reops.locale')).toBe('zh-CN');
    setLocale('en');
    expect(storage.getItem('reops.locale')).toBe('en');
  });

  it.each([null, 'fr', 'EN', '', 'null'])('defaults invalid or missing preference %s to Chinese', async value => {
    browser(value);
    expect((await import('./locale')).getLocale()).toBe('zh-CN');
  });

  it('continues switching when storage is blocked', async () => {
    const { document } = browser(null, true);
    const { getLocale, setLocale } = await import('./locale');
    expect(() => setLocale('en')).not.toThrow();
    expect(getLocale()).toBe('en');
    expect(document.documentElement.lang).toBe('en');
  });

  it('follows other tabs, including preference removal and storage clear', async () => {
    const { storage, handlers } = browser(null);
    const { getLocale } = await import('./locale');
    storage.setItem('reops.locale', 'en');
    handlers.storage({ key: 'reops.locale', storageArea: storage });
    expect(getLocale()).toBe('en');
    storage.setItem('reops.locale', 'unsupported');
    handlers.storage({ key: null, storageArea: storage });
    expect(getLocale()).toBe('zh-CN');
  });
});
