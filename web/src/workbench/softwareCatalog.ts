export interface LocalSoftware {
  id: string; kind: 'process' | 'service' | 'container'; name: string; pids: number[]; ports: number[];
  instances: number; memory_bytes: number | null; windowed: boolean;
  image: string | null; project: string | null; service: string | null;
}
export interface SoftwareWatch {
  record: LocalSoftware; alive: boolean | null; last_seen_at: string;
  history: { timestamp: string; alive: boolean | null }[];
}
export interface SoftwareCatalog {
  source: 'real'; state: 'starting' | 'ready' | 'partial' | 'unavailable' | 'disabled' | 'stale';
  generated_at: string | null; interval_seconds: number; records: LocalSoftware[]; watches: SoftwareWatch[];
  sources: Record<'process' | 'service' | 'container' | 'ports', 'ready' | 'unavailable'>;
  omitted: number; capabilities: string[]; recovery_available: false;
}
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 200;
const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const alive = (value: unknown) => value === null || typeof value === 'boolean';
function software(value: unknown): value is LocalSoftware {
  return object(value) && text(value.id) && text(value.name) && ['process','service','container'].includes(String(value.kind))
    && Array.isArray(value.pids) && value.pids.every(count) && Array.isArray(value.ports) && value.ports.every(port => count(port) && port > 0 && port < 65536)
    && count(value.instances) && value.instances > 0 && (value.memory_bytes === null || count(value.memory_bytes))
    && typeof value.windowed === 'boolean' && ['image','project','service'].every(key => value[key] === null || typeof value[key] === 'string');
}
export function parseSoftwareCatalog(value: unknown): SoftwareCatalog {
  if (!object(value) || value.source !== 'real' || value.recovery_available !== false
    || !['starting','ready','partial','unavailable','disabled','stale'].includes(String(value.state))
    || !(value.generated_at === null || text(value.generated_at) && Number.isFinite(Date.parse(value.generated_at)))
    || !count(value.interval_seconds) || value.interval_seconds < 1 || value.interval_seconds > 60 || !count(value.omitted)
    || !Array.isArray(value.records) || value.records.length > 2000 || !value.records.every(software)
    || new Set(value.records.map(item => item.id)).size !== value.records.length
    || !object(value.sources) || !['process','service','container','ports'].every(key => ['ready','unavailable'].includes(String((value.sources as Record<string,unknown>)[key])))
    || !Array.isArray(value.capabilities) || value.capabilities.join(',') !== 'liveness,listener_ports,working_set'
    || !Array.isArray(value.watches) || value.watches.length > 64
    || value.watches.some(item => !object(item) || !software(item.record) || !alive(item.alive) || !text(item.last_seen_at)
      || !Array.isArray(item.history) || item.history.length > 12 || item.history.some(sample => !object(sample) || !text(sample.timestamp) || !alive(sample.alive)))
    || new Set(value.watches.map(item => (item as SoftwareWatch).record.id)).size !== value.watches.length) {
    throw new Error('Local discovery returned an invalid record.');
  }
  return value as unknown as SoftwareCatalog;
}

export function createSoftwareCatalogClient(fetcher: typeof fetch = (...args) => fetch(...args)) {
  let token = '';
  const prefix = '/api/v1/workbench/control';
  async function read(signal?: AbortSignal) {
    const response = await fetcher(prefix + '/catalog', { cache:'no-store', credentials:'same-origin', redirect:'error', mode:'same-origin', signal });
    if (!response.ok) throw new Error('Local discovery is not available on this monitoring service.');
    return parseSoftwareCatalog(await response.json());
  }
  async function watch(id: string, watching: boolean) {
    if (!token) {
      const response = await fetcher(prefix + '/status', {cache:'no-store',credentials:'same-origin',redirect:'error',mode:'same-origin'});
      const value: unknown = await response.json();
      if (!response.ok || !object(value) || typeof value.csrf !== 'string') throw new Error('Refresh the monitoring connection and try again.');
      token = value.csrf;
    }
    const response = await fetcher(prefix + '/catalog/watch', {method:'POST',cache:'no-store',credentials:'same-origin',redirect:'error',mode:'same-origin',
      headers:{'Content-Type':'application/json','X-ReOps-Monitor-Token':token},body:JSON.stringify({software_id:id,watching})});
    if (!response.ok) { if (response.status === 403) token = ''; throw new Error('The software or session changed. Refresh and try again.'); }
    return parseSoftwareCatalog(await response.json());
  }
  return {read,watch};
}
