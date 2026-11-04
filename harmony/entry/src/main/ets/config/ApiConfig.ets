import { SessionCredential } from './SessionCredential';

export interface ApiConfig {
  baseUrl: string;
  credential: SessionCredential;
  timeoutMs: number;
  testEnvironment?: boolean;
}

// Explicit session configuration: no endpoint, credentials or sample data in the package.
export function initialConfig(): ApiConfig {
  return { baseUrl: '', credential: new SessionCredential(), timeoutMs: 8000 };
}

export function normalizeBaseUrl(input: string): string {
  const value = input.trim().replace(/\/+$/, '').replace(/\/api\/v1$/, '');
  // Origin only, no credentials/path/query. Backend routing stays inside ApiService.
  if (!/^https?:\/\/[A-Za-z0-9.-]+(?::[0-9]{1,5})?$/.test(value)) {
    throw new Error('请输入 http(s)://主机[:端口]，不包含路径或凭据');
  }
  const port = value.match(/:([0-9]+)$/);
  if (port && (Number(port[1]) < 1 || Number(port[1]) > 65535)) {
    throw new Error('服务端口无效');
  }
  if (value.startsWith('http://') && !/^http:\/\/(localhost|127\.0\.0\.1)(:[0-9]+)?$/.test(value)) {
    throw new Error('携带只读凭据须使用 HTTPS；HTTP 仅允许本机回环测试');
  }
  return value;
}
