import { ApiConfig, normalizeBaseUrl } from '../config/ApiConfig';
import { IncidentPage, MobileOverview, MobileDetail } from '../models/MobileModels';
import { HttpClient } from './HttpClient';
import { decodeMobileOverview, decodeMobilePage, decodeMobileDetail } from './Decoders';

// Only the three authenticated B mobile-v1 GET endpoints. No legacy/control fallback.
export class ApiService {
  private config: ApiConfig;
  private http: HttpClient = new HttpClient();
  constructor(config: ApiConfig) { this.config = config; }
  private source(): string { return this.config.testEnvironment ? 'offline_fixture' : 'real'; }
  private async read(path: string): Promise<string> {
    const base = normalizeBaseUrl(this.config.baseUrl);
    return this.http.get(base, path, this.config.timeoutMs, this.config.credential);
  }
  async overview(): Promise<MobileOverview> {
    return decodeMobileOverview(await this.read('/api/v1/mobile/overview'), this.source());
  }
  async incidents(offset: number = 0): Promise<IncidentPage> {
    return decodeMobilePage(await this.read(`/api/v1/mobile/incidents?limit=20&offset=${offset}`), offset, 20, this.source());
  }
  async detail(id: string, trace: string): Promise<MobileDetail> {
    return decodeMobileDetail(await this.read(`/api/v1/mobile/incidents/${encodeURIComponent(id)}`), id, trace, this.source());
  }
}
