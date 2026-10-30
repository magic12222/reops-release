import { getLocale, type Locale } from './locale';
import { messages } from './messages';
import { workspaceMessages } from './workspaceMessages';
export { useLocale, getLocale, setLocale } from './locale';

/** Source text is the key. Only UI/presentation text belongs here, never raw records. */
export function translate(source: string, locale: Locale, ...values: unknown[]): string {
  const key = source.trim();
  const entry = Object.prototype.hasOwnProperty.call(messages, key) ? messages[key] : workspaceMessages[key];
  const selected = entry?.[locale] || entry?.['zh-CN'];
  const text = selected ? source.slice(0, source.indexOf(key)) + selected + source.slice(source.indexOf(key) + key.length) : source;
  return text.replace(/\{(\d+)\}/g, (placeholder, index: string) =>
    Number(index) < values.length ? String(values[Number(index)]) : placeholder);
}

export function t<T>(value: T, ...values: unknown[]): T {
  return (typeof value === 'string' ? translate(value, getLocale(), ...values) : value) as T;
}
