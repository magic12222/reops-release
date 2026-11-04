/* Mobile-v1 boundary tests; no network, real credential or business record. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const studio = process.env.REOPS_DEVECO_HOME || 'D:/DevTools/Huawei/DevEcoStudio';
const ts = require(path.join(studio, 'tools/hvigor/hvigor/node_modules/typescript'));
const root = path.resolve(__dirname, '../entry/src/main/ets');
const cache = new Map();
let handler;
let closed = 0, canceled = 0, lastOptions, requests = 0;
const rcp = {
  Request: class { constructor(url, method, headers) { this.url = new URL(url); this.method = method; this.headers = headers; } },
  createSession: options => { lastOptions = options; return {
    fetch: request => { requests++; return handler(request); }, cancel: () => canceled++, close: () => closed++
  }; }
};
function load(file) {
  const resolved = path.resolve(file.endsWith('.ets') ? file : `${file}.ets`);
  if (cache.has(resolved)) return cache.get(resolved).exports;
  const module = { exports: {} }; cache.set(resolved, module);
  const source = ts.transpileModule(fs.readFileSync(resolved, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 }
  }).outputText;
  new Function('require', 'module', 'exports', source)(name => {
    if (name === '@kit.RemoteCommunicationKit') return { rcp };
    return load(path.resolve(path.dirname(resolved), name));
  }, module, module.exports);
  return module.exports;
}
const d = load(path.join(root, 'services/Decoders'));
const { HttpClient } = load(path.join(root, 'services/HttpClient'));
const { ApiService } = load(path.join(root, 'services/ApiService'));
const { normalizeBaseUrl } = load(path.join(root, 'config/ApiConfig'));
const { SessionCredential } = load(path.join(root, 'config/SessionCredential'));
const { decodeConnectionCode } = load(path.join(root, 'config/ConnectionCode'));
const { errorMessage, ApiError } = load(path.join(root, 'services/ApiError'));
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'mobile-v1.fixture.json'), 'utf8'));
const clone = value => JSON.parse(JSON.stringify(value));
const raw = JSON.stringify;
let passed = 0;
async function test(name, fn) { await fn(); passed++; console.log(`PASS ${name}`); }
const response = (statusCode, value) => { const text = typeof value === 'string' ? value : raw(value);
  return { statusCode, body: new TextEncoder().encode(text).buffer, toString: () => text }; };
const secret = crypto.randomBytes(40).toString('base64url'); // ephemeral test-only value, never printed
const credential = new SessionCredential(); credential.set(secret);
const config = { baseUrl: 'https://unit.invalid/api/v1', credential, timeoutMs: 200, testEnvironment: true };
const rejected = fn => assert.throws(fn, error => error.code === 'contract');
const detail = () => clone(fixture.valid.detail);
const decodeDetail = value => d.decodeMobileDetail(raw(value), 'fixture-incident-1', 'fixture-trace-1', 'offline_fixture');
(async () => {
  await test('origin and /api/v1 prefix normalize without duplication', () => {
    assert.equal(normalizeBaseUrl(' https://unit.invalid:8443/api/v1/ '), 'https://unit.invalid:8443');
    assert.equal(normalizeBaseUrl('https://unit.invalid'), 'https://unit.invalid');
    assert.throws(() => normalizeBaseUrl('https://user:password@unit.invalid'));
    assert.throws(() => normalizeBaseUrl('https://unit.invalid/other'));
    assert.throws(() => normalizeBaseUrl('http://private-host.invalid:8030/api/v1'));
    assert.equal(normalizeBaseUrl('http://127.0.0.1:18882/api/v1'), 'http://127.0.0.1:18882');
  });
  await test('credential validation and serialization never expose value', () => {
    assert.equal(credential.authorization(), 'Bearer ' + secret);
    assert.ok(!JSON.stringify(config).includes(secret));
    const empty = new SessionCredential(); assert.throws(() => empty.authorization(), e => e.code === 'auth_unconfigured');
    assert.throws(() => empty.set('Bearer ' + secret));
    assert.throws(() => empty.set(secret + '\r\nHeader: value'));
    assert.throws(() => empty.set('short'));
  });
  await test('GET emits exact Bearer, no cache and no auto redirects', async () => {
    closed = 0;
    handler = async r => { assert.equal(r.headers.Authorization, 'Bearer ' + secret); assert.equal(r.method, 'GET');
      assert.equal(r.headers['Cache-Control'], 'no-store'); return response(200, '{}'); };
    assert.equal(await new HttpClient().get('https://unit.invalid', '/api/v1/mobile/overview', 100, credential), '{}');
    assert.equal(lastOptions.requestConfiguration.transfer.autoRedirect, false); assert.equal(closed, 1);
  });
  await test('missing credential sends zero requests', async () => {
    const before = requests;
    await assert.rejects(new HttpClient().get('https://unit.invalid', '/api/v1/mobile/overview', 100, new SessionCredential()), e => e.code === 'auth_unconfigured');
    assert.equal(requests, before);
  });
  for (const [status, code] of [[401, 'unauthorized'], [403, 'forbidden'], [503, 'service'], [404, 'http'], [422, 'http'], [302, 'http']]) {
    await test(`HTTP ${status} isolated from network error`, async () => {
      handler = async () => response(status, { detail: 'private error text' });
      await assert.rejects(new HttpClient().get('https://unit.invalid', '/api/v1/mobile/overview', 100, credential), e => e.code === code && e.status === status && !e.message.includes('private'));
    });
  }
  await test('server credential configuration 503 is explicit', async () => {
    handler = async () => response(503, { detail: 'mobile_access_not_configured' });
    await assert.rejects(new HttpClient().get('https://unit.invalid', '/api/v1/mobile/overview', 100, credential), e => e.reason === 'mobile_access_not_configured');
  });
  await test('network failure hides native error details', async () => {
    handler = async () => { throw new Error(secret); };
    await assert.rejects(new HttpClient().get('https://unit.invalid', '/api/v1/mobile/overview', 100, credential), e => e.code === 'network' && !e.message.includes(secret));
  });
  await test('whole request timeout cancels and closes native session', async () => {
    canceled = 0; closed = 0; handler = () => new Promise(() => {});
    await assert.rejects(new HttpClient().get('https://unit.invalid', '/api/v1/mobile/overview', 20, credential), e => e.code === 'timeout');
    assert.equal(canceled, 1); assert.equal(closed, 1);
  });
  await test('native transfer timeout classified', async () => {
    handler = async () => { throw { code: 1007900028 }; };
    await assert.rejects(new HttpClient().get('https://unit.invalid', '/api/v1/mobile/overview', 100, credential), e => e.code === 'timeout');
  });
  await test('invalid JSON distinct from HTTP failure', () => assert.throws(() => d.decodeMobileOverview('{'), e => e.code === 'json'));
  await test('monitor offline overview keeps nonempty historical counts', () => {
    const o = d.decodeMobileOverview(raw(fixture.valid.overview), 'offline_fixture');
    assert.equal(o.a_status, 'not_connected'); assert.equal(o.target_health, 'unknown'); assert.equal(o.total, 2);
  });
  await test('offline targets cannot turn cached health healthy', () => {
    const value = clone(fixture.valid.overview); value.target_health = 'healthy';
    rejected(() => d.decodeMobileOverview(raw(value), 'offline_fixture'));
  });
  await test('statistics sums must match total', () => {
    const value = clone(fixture.valid.overview); value.total++;
    rejected(() => d.decodeMobileOverview(raw(value), 'offline_fixture'));
  });
  await test('fixture source rejects default production decoder', () => rejected(() => d.decodeMobileOverview(raw(fixture.valid.overview))));
  await test('pagination validates offset/has_more and out-of-range empty', () => {
    assert.equal(d.decodeMobilePage(raw(fixture.paged['0']), 0, 20, 'offline_fixture').has_more, true);
    assert.equal(d.decodeMobilePage(raw(fixture.paged['20']), 20, 20, 'offline_fixture').items.length, 2);
    assert.equal(d.decodeMobilePage(raw(fixture.paged['40']), 40, 20, 'offline_fixture').items.length, 0);
    rejected(() => d.decodeMobilePage(raw(fixture.paged['20']), 0, 20, 'offline_fixture'));
    const value = clone(fixture.valid.page); value.has_more = true;
    rejected(() => d.decodeMobilePage(raw(value), 0, 20, 'offline_fixture'));
  });
  await test('missing required mobile fields reject', () => {
    const value = detail(); delete value.recovery.verification; rejected(() => decodeDetail(value));
  });
  await test('history detail loads without a current monitored target', () => {
    const value = decodeDetail(detail()); assert.equal(value.a_status, 'not_connected');
    assert.equal(value.incident.events.length, 4); assert.ok(value.gaps.includes('target_monitoring_unavailable'));
  });
  await test('exact Run references retain distinct IDs without old route reads', () => {
    const value = decodeDetail(detail()); assert.equal(value.runs[0].run_id, 'fixture-run-distinct');
    assert.notEqual(value.runs[0].run_id, value.incident.trace_id);
  });
  await test('foreign incident and trace reject even when shapes match', () => {
    let value = detail(); value.incident.id = 'other'; rejected(() => decodeDetail(value));
    value = detail(); value.runs[0].trace_id = 'other'; rejected(() => decodeDetail(value));
    value = detail(); value.runs[0].source = 'real'; rejected(() => decodeDetail(value));
  });
  await test('Run not_imported keeps no fabricated reference', () => {
    const value = d.decodeMobileDetail(raw(fixture.valid.pending_detail), 'fixture-incident-2', 'fixture-trace-2', 'offline_fixture');
    assert.equal(value.run_link_status, 'not_imported'); assert.equal(value.runs.length, 0);
  });
  await test('matched status needs references and no duplicate Run IDs', () => {
    let value = detail(); value.runs = []; rejected(() => decodeDetail(value));
    value = detail(); value.runs.push(clone(value.runs[0])); rejected(() => decodeDetail(value));
  });
  await test('experience requires explicit reference and target, allows historic origin', () => {
    let value = detail(); value.knowledge[0].target_id = 'other'; rejected(() => decodeDetail(value));
    value = detail(); value.knowledge[0].incident_id = 'historical-origin';
    assert.equal(decodeDetail(value).knowledge[0].incident_id, 'historical-origin');
  });
  await test('event subset cannot inject another event', () => {
    const value = detail(); value.diagnosis.evidence_events[0].id = 'foreign'; rejected(() => decodeDetail(value));
  });
  await test('execution or model success never substitutes verification', () => {
    const value = detail(); value.recovery.verification.status = 'unknown'; rejected(() => decodeDetail(value));
    const noCalls = detail(); noCalls.diagnosis.status = 'succeeded'; rejected(() => decodeDetail(noCalls));
  });
  await test('rule recovery can coexist with later recorded model analysis', () => {
    const value = detail(); const call = { id: 'test-call', model: 'TEST ONLY', status: 'succeeded', request: 'TEST ONLY', response: 'TEST ONLY: retrospective', duration_ms: null, input_tokens: null, output_tokens: null, redacted: true };
    value.incident.model_calls = [call]; value.diagnosis.calls = [call]; value.diagnosis.status = 'succeeded';
    assert.equal(decodeDetail(value).diagnosis.source, 'rule');
  });
  await test('service uses only documented mobile paths with a single prefix', async () => {
    const seen = [];
    handler = async request => {
      seen.push(request.url.pathname + request.url.search);
      if (request.url.pathname.endsWith('/overview')) return response(200, fixture.valid.overview);
      if (request.url.pathname.endsWith('/fixture-incident-1')) return response(200, fixture.valid.detail);
      return response(200, fixture.valid.page);
    };
    const service = new ApiService(config);
    await service.overview(); await service.incidents(); await service.detail('fixture-incident-1', 'fixture-trace-1');
    assert.deepEqual(seen, ['/api/v1/mobile/overview', '/api/v1/mobile/incidents?limit=20&offset=0', '/api/v1/mobile/incidents/fixture-incident-1']);
  });
  await test('detail path encodes ID and decoder still checks requested identity', async () => {
    const value = detail(); value.incident.id = 'id with %'; value.runs[0].incident_id = value.incident.id;
    handler = async request => { assert.ok(request.url.pathname.endsWith('/id%20with%20%25')); return response(200, value); };
    await new ApiService(config).detail(value.incident.id, value.incident.trace_id);
  });
  await test('clearing session requires reconfiguration', () => {
    const current = new SessionCredential(); current.set(secret); current.clear();
    assert.throws(() => current.authorization(), e => e.code === 'auth_unconfigured');
    assert.ok(!JSON.stringify(current).includes(secret));
  });
  await test('401/403/timeout messages remain distinct without credential', () => {
    const messages = ['unauthorized', 'forbidden', 'timeout', 'network'].map(code => errorMessage(new ApiError(code)));
    assert.equal(new Set(messages).size, 4); assert.ok(messages.every(value => !value.includes(secret)));
  });
  await test('connection code is HTTPS-only, expires and never starts transport', () => {
    const now = 1700000000000;
    const value = { type: 'reops-mobile-connection-v1', base_url: 'https://unit.invalid:8443', token: secret, expires_at: now + 180000 };
    const before = requests;
    assert.deepEqual(decodeConnectionCode(raw(value), now), { baseUrl: value.base_url, token: secret });
    for (const bad of [null, [], {}, { ...value, type: 'other' }, { ...value, expires_at: now },
      { ...value, expires_at: now + 300001 }, { ...value, expires_at: 'later' },
      { ...value, base_url: 'http://127.0.0.1' }, { ...value, base_url: 'https://unit.invalid/?token=x' },
      { ...value, token: 'short' }]) assert.throws(() => decodeConnectionCode(raw(bad), now));
    assert.throws(() => decodeConnectionCode('invalid json', now));
    assert.throws(() => decodeConnectionCode('x'.repeat(4097), now));
    assert.equal(requests, before);
  });
  credential.clear();
  console.log(`${passed} passed; pinned B mobile-v1 fixtures + native transport doubles, not real deployment acceptance.`);
})().catch(error => { console.error(error instanceof assert.AssertionError ? error.message.replaceAll(secret, '[redacted]') : 'Test failed; details omitted'); process.exitCode = 1; });
