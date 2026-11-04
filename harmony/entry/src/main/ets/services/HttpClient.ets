import { rcp } from '@kit.RemoteCommunicationKit';
import { SessionCredential } from '../config/SessionCredential';
import { ApiError } from './ApiError';

interface TransportError { code?: number; }

export class HttpClient {
  async get(baseUrl: string, path: string, timeoutMs: number, credential: SessionCredential): Promise<string> {
    if (!baseUrl) throw new ApiError('configuration');
    const authorization = credential.authorization();
    // SDK RCP supports disabling redirects since API11, including our minimum API20.
    let session: rcp.Session;
    try {
      session = rcp.createSession({ requestConfiguration: {
        transfer: { autoRedirect: false, timeout: { connectMs: timeoutMs, transferMs: timeoutMs } }, proxy: 'no-proxy'
      } });
    } catch { throw new ApiError('network'); }
    let timer: number = -1;
    let timedOut: boolean = false;
    try {
      const deadline = new Promise<rcp.Response>((resolve, reject) => {
        timer = setTimeout(() => { timedOut = true; reject(new ApiError('timeout')); session.cancel(); }, timeoutMs);
      });
      const pending = session.fetch(new rcp.Request(`${baseUrl}${path}`, 'GET',
        { 'Accept': 'application/json', 'Authorization': authorization, 'Cache-Control': 'no-store' }));
      const response = await Promise.race([pending, deadline]);
      if (response.statusCode === 401) throw new ApiError('unauthorized', 401);
      if (response.statusCode === 403) throw new ApiError('forbidden', 403);
      if (response.statusCode === 503) {
        let reason = '';
        try {
          const value = JSON.parse(response.toString() ?? '') as Record<string, string>;
          if (value['detail'] === 'mobile_access_not_configured') reason = 'mobile_access_not_configured';
        } catch { /* Never display server error text. */ }
        throw new ApiError('service', 503, reason);
      }
      if (response.statusCode < 200 || response.statusCode >= 300) throw new ApiError('http', response.statusCode);
      if (!response.body || response.body.byteLength > 2 * 1024 * 1024) throw new ApiError('json');
      const body = response.toString();
      if (body === null) throw new ApiError('json');
      return body;
    } catch (error) {
      if (timedOut || (error as TransportError).code === 1007900028) throw new ApiError('timeout');
      if (error instanceof ApiError) throw error;
      throw new ApiError('network');
    } finally {
      if (timer !== -1) clearTimeout(timer);
      session.close();
    }
  }
}
