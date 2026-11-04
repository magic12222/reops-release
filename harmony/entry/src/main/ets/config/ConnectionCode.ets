import { normalizeBaseUrl } from './ApiConfig';
import { SessionCredential } from './SessionCredential';

export interface ConnectionCode { baseUrl: string; token: string; }

// Parsing never sends a request. The user confirms the visible address separately.
export function decodeConnectionCode(raw: string, now: number = Date.now()): ConnectionCode {
  if (raw.length > 4096) throw new Error('连接码无效');
  let value: Record<string, Object | null>;
  try { value = JSON.parse(raw) as Record<string, Object | null>; }
  catch { throw new Error('连接码无效'); }
  if (!value || Array.isArray(value) || value['type'] !== 'reops-mobile-connection-v1' ||
    typeof value['base_url'] !== 'string' || typeof value['token'] !== 'string' ||
    typeof value['expires_at'] !== 'number') throw new Error('连接码无效');
  const expiry = value['expires_at'] as number;
  if (!Number.isFinite(now) || !Number.isFinite(expiry) || expiry <= now || expiry > now + 300000) {
    throw new Error('连接码已过期，请在电脑上重新打开');
  }
  const base = normalizeBaseUrl(value['base_url'] as string);
  if (!base.startsWith('https://')) throw new Error('连接码必须使用 HTTPS');
  const token = value['token'] as string;
  const check = new SessionCredential();
  try { check.set(token); } finally { check.clear(); }
  return { baseUrl: base, token: token };
}
