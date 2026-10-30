// Build first. Reuses an existing Playwright installation; never contacts a backend.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..'), dist = path.join(root, 'web/dist');
const output = path.join(root, 'output/playwright/restored-navigation');
fs.mkdirSync(output, { recursive: true });
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'workbench/example.snapshot.json'), 'utf8'));
const original = JSON.stringify(fixture);
let snapshot = { ...structuredClone(fixture), source: 'real' }, unavailable = false;
const checks = [], issues = [], errors = [], writes = [], reads = [];
const check = (name, condition) => { assert(condition, name); checks.push(name); };
const api = { enabled: true, busy: false, csrf: 'isolated-test-session', job: null, model: {
  configured: false, verified: false, source: 'isolated_fixture', model: 'fixture-model', endpoint: 'https://example.com/v1',
  storage: 'session', services: [], checks: [],
} };
const automation = { available: false, demo_busy: false, demo: null, automation: {
  mode: 'observe', state: 'observe', offer_id: null, remaining_actions: 3, remaining_seconds: 0, inflight: false, events: [],
  policy: { duration_hours: 8, max_actions: 3, cooldown_seconds: 60, action: 'start_service(postgres)', model_calls: 0, fault_injection: false },
} };
const catalog = { source: 'real', state: 'ready', generated_at: '2026-10-30T08:00:00Z', interval_seconds: 3,
  records: [{ id: 'process:node', kind: 'process', name: 'node.exe', pids: [123], ports: [4173], instances: 1,
    memory_bytes: 1024 * 1024, windowed: false, image: null, project: null, service: null }], watches: [],
  sources: { process: 'ready', service: 'ready', container: 'ready', ports: 'ready' }, omitted: 0,
  capabilities: ['liveness', 'listener_ports', 'working_set'], recovery_available: false };

async function intercept(route) {
  const request = route.request(), url = new URL(request.url());
  if (!url.pathname.startsWith('/api/')) {
    const file = path.resolve(dist, '.' + url.pathname);
    if (file !== dist && !file.startsWith(dist + path.sep)) return route.abort();
    return route.fulfill({ path: fs.existsSync(file) && fs.statSync(file).isFile() ? file : path.join(dist, 'index.html') });
  }
  if (request.method() !== 'GET') { writes.push(url.pathname); return route.fulfill({ status: 403, body: '{}' }); }
  reads.push(url.pathname);
  if (unavailable) return route.fulfill({ status: 503, body: '{}' });
  if (url.pathname === '/api/v1/workbench/snapshot') return route.fulfill({ json: snapshot });
  if (url.pathname === '/api/v1/workbench/control/catalog') return route.fulfill({ json: catalog });
  if (url.pathname === '/api/v1/workbench/control/status') return route.fulfill({ json: {
    csrf: 'isolated-monitor-session', enabled: false, busy: false, unified_monitoring: false,
    feed: { status: 'ready', targets: snapshot.targets },
    agent: { enabled: false, state: 'disabled', execution_enabled: false, model_enabled: false },
  } });
  if (url.pathname === '/api/v1/workbench/control/vikunja/status') return route.fulfill({ json: automation });
  if (url.pathname === '/api/v1/researchloop/control/status') return route.fulfill({ json: api });
  if (url.pathname.includes('/dependency-diagnosis/knowledge/')) return route.fulfill({ json: {
    profile: 'dependency-knowledge-retrieval-v1', status: 'miss', trace_id: snapshot.incidents[0].trace_id,
    query: { target_id: snapshot.targets[0].id }, duration_ms: 0, matches: [],
    started_at: '2026-10-30T08:00:00Z', completed_at: '2026-10-30T08:00:00Z',
  } });
  return route.fulfill({ status: 503, body: '{}' });
}
async function locale(page, value) {
  if (await page.locator('html').getAttribute('lang') !== value) await page.locator('.locale-toggle').click();
  await page.waitForFunction(expected => document.documentElement.lang === expected, value);
}
async function open(page, href) {
  await page.goto('http://127.0.0.1:4187' + href);
  await page.locator('h1:visible').first().waitFor();
  await page.evaluate(() => document.fonts.ready);
}
async function layout(page, name) {
  const result = await page.evaluate(() => {
    const problems = [];
    if (document.documentElement.scrollWidth > innerWidth + 1) problems.push(`page overflow ${document.documentElement.scrollWidth}/${innerWidth}`);
    for (const node of document.querySelectorAll('h1,.wb-heading,.execution-page-heading,.retrieval-page-heading,.api-page-heading')) {
      if (node.checkVisibility() && !node.closest('[hidden]') && node.scrollWidth > node.clientWidth + 3) problems.push(`text overflow ${node.className || node.tagName}`);
    }
    for (const node of document.querySelectorAll('.navbar a,.navbar button')) {
      if (!node.checkVisibility() || node.closest('nav:not(.open)') && innerWidth <= 1100) continue;
      const box = node.getBoundingClientRect();
      if (box.left < -1 || box.right > innerWidth + 1) problems.push('navigation outside viewport');
    }
    return problems;
  });
  issues.push(...result.map(problem => `${name}: ${problem}`));
  checks.push(`${name}: layout inspected`);
}
async function nav(page, href) {
  if (await page.locator('header nav').evaluate(node => getComputedStyle(node).display === 'none')) await page.locator('.menu-toggle').click();
  await page.locator(`header nav a[href="${href}"]`).click();
  await page.locator('h1:visible').first().waitFor();
}

async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true, args: ['--no-proxy-server'] });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    await context.route('**/*', intercept);
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await open(page, '/');
    const destinations = ['/', '/workbench', '/execution', '/knowledge-retrieval', '/architecture', '/agent', '/recovery', '/benchmark', '/api'];
    check('all candidate destinations restored', JSON.stringify(await page.locator('header nav a').evaluateAll(nodes => nodes.map(node => node.getAttribute('href')))) === JSON.stringify(destinations));
    for (const lang of ['zh-CN', 'en']) {
      await locale(page, lang);
      for (const href of destinations) {
        await nav(page, href);
        check(`${lang} navigation to ${href} resolves a real page`, await page.locator('.route-page[data-page="not-found"]').count() === 0);
        check(`${lang} navigation to ${href} retains language`, await page.locator('html').getAttribute('lang') === lang);
      }
    }
    await nav(page, '/workbench');
    await nav(page, '/execution');
    await page.goBack();
    check('back restores Workbench and language', new URL(page.url()).pathname === '/workbench' && await page.locator('html').getAttribute('lang') === 'en');
    await page.goForward();
    check('forward restores Execution and language', new URL(page.url()).pathname === '/execution' && await page.locator('html').getAttribute('lang') === 'en');

    await open(page, '/workbench?source=offline_fixture');
    await locale(page, 'zh-CN');
    check('Workbench is the implemented sample explorer', await page.locator('.wb-incident-list > button').count() === fixture.incidents.length);
    await page.locator('.wb-incident-list > button').first().click();
    const trace = new URL(page.url()).searchParams.get('trace');
    await locale(page, 'en');
    check('language switching retains exact incident', new URL(page.url()).searchParams.get('trace') === trace);
    await page.locator('.wb-knowledge-entry').click();
    await page.locator('.knowledge-library .kg').waitFor();
    check('Global knowledge keeps the independent graph entry', new URL(page.url()).pathname === '/knowledge-retrieval');
    await open(page, '/workbench?source=offline_fixture&trace=' + encodeURIComponent(trace));
    await page.locator('.wb-tabs button').last().click();
    await page.locator('.kg-workbench').waitFor();
    await locale(page, 'zh-CN');
    check('embedded graph controls translate', (await page.locator('.kg-tools').innerText()).includes('知识'));
    await nav(page, '/knowledge-retrieval');
    await page.locator('.knowledge-library .kg').waitFor();
    check('Knowledge has a separate implemented library page', new URL(page.url()).pathname === '/knowledge-retrieval');
    const library = page.locator('.knowledge-library');
    await library.locator('[data-node-id="starter:postgres-startup"]').click();
    const selected = await library.locator('.kg-node[aria-pressed="true"]').getAttribute('data-node-id');
    check('curated knowledge detail is translated', (await library.locator('.kg-detail').innerText()).includes('数据库就绪后恢复'));
    await locale(page, 'en');
    check('graph selection persists in English', await library.locator('.kg-node[aria-pressed="true"]').getAttribute('data-node-id') === selected);
    check('knowledge detail updates immediately', (await library.locator('.kg-detail').innerText()).includes('Recover after database readiness'));
    const knowledgeSearch = library.locator('.kg-search input');
    await locale(page, 'zh-CN');
    await knowledgeSearch.fill('数据库');
    check('Chinese knowledge search finds real curated nodes', await library.locator('[data-node-id="starter:postgres-startup"]').count() === 1);
    await knowledgeSearch.fill('');
    await open(page, '/workbench?source=offline_fixture&knowledge=retrieve&trace=' + encodeURIComponent(fixture.incidents[0].trace_id));
    check('legacy lookup URL opens exact independent Knowledge page', new URL(page.url()).pathname === '/knowledge-retrieval' && new URL(page.url()).searchParams.get('trace') === fixture.incidents[0].trace_id);

    snapshot.incidents[0].model_calls = [{ id: 'collision-call', model: 'Unknown', request: 'Unknown', response: 'Unknown',
      status: 'succeeded', duration_ms: null, input_tokens: null, output_tokens: null, redacted: true }];
    await open(page, '/execution?source=real&trace=' + encodeURIComponent(snapshot.incidents[0].trace_id));
    await page.locator('.execution-selected-evidence').waitFor();
    await page.locator('.execution-timeline button').first().click();
    const eventId = await page.locator('.execution-selected-evidence').getAttribute('data-event-id');
    await locale(page, 'en');
    check('raw model reply matches the source in English', await page.locator('.execution-typewriter').innerText() === 'Unknown');
    check('Execution selection persists after translation', await page.locator('.execution-selected-evidence').getAttribute('data-event-id') === eventId);
    await page.locator('.execution-selected-evidence details > summary').first().click();
    const originalEvent = await page.locator('.execution-selected-evidence pre').textContent();
    await locale(page, 'zh-CN');
    check('raw model reply is not translated in Chinese', await page.locator('.execution-typewriter').innerText() === 'Unknown');
    check('event JSON remains unchanged', await page.locator('.execution-selected-evidence pre').textContent() === originalEvent);
    const first = snapshot.incidents[0], initialCount = first.events.length;
    first.events.push({ ...first.events.at(-1), id: 'untranslated-event-id', sequence: initialCount, title: '原始新增事件 — preserve verbatim', detail: 'Original event detail', timestamp: new Date().toISOString() });
    await page.waitForFunction(count => document.querySelectorAll('.execution-timeline button').length === count, initialCount + 1);
    check('dynamic event is consumed without losing selected evidence', await page.locator('.execution-selected-evidence').getAttribute('data-event-id') === eventId);
    await locale(page, 'en');
    check('new raw event text stays original in English', (await page.locator('.execution-timeline').innerText()).includes('原始新增事件 — preserve verbatim'));
    snapshot = { ...structuredClone(fixture), source: 'real' };

    await open(page, '/api');
    await page.locator('.api-form-grid input').first().fill('unsaved-name-原文');
    await page.locator('.api-form-grid input').nth(1).fill('fixture-provider');
    await locale(page, 'zh-CN');
    check('API editor is translated', (await page.locator('.api-editor').innerText()).includes('保存配置'));
    await locale(page, 'en');
    check('unsaved API form values survive translation', await page.locator('.api-form-grid input').first().inputValue() === 'unsaved-name-原文');
    check('API editor controls switch to English', (await page.locator('.api-editor').innerText()).includes('Save configuration'));
    await page.reload();
    check('refresh keeps English on a restored direct route', await page.locator('html').getAttribute('lang') === 'en' && new URL(page.url()).pathname === '/api');

    await open(page, '/workbench?source=real');
    await page.locator('.wb-local-browse').click();
    await page.locator('.software-directory').waitFor();
    await page.locator('.software-search input').fill('node');
    await page.locator('.software-name').first().click();
    await locale(page, 'zh-CN');
    check('software search persists on translation', await page.locator('.software-search input').inputValue() === 'node');
    check('software details stay open', (await page.locator('.software-detail h3').innerText()) === 'node.exe');
    await locale(page, 'en');
    check('software detail labels translate', (await page.locator('.software-detail').innerText()).includes('Basic observation only'));

    unavailable = true;
    for (const href of ['/workbench', '/execution', '/knowledge-retrieval', '/api']) {
      await open(page, href);
      await locale(page, 'zh-CN');
      await page.waitForFunction(() => !!document.querySelector('[role="alert"]') || document.body.textContent.includes('配置服务尚未连接'));
      await locale(page, 'en');
      check(`${href} unavailable state still shows a real page`, await page.locator('h1:visible').count() === 1);
    }
    unavailable = false;
    const samples = ['/workbench?source=offline_fixture', '/execution?source=offline_fixture', '/knowledge-retrieval?source=offline_fixture', '/api'];
    for (const width of [1920, 1440, 1100, 768, 390, 320]) for (const lang of ['zh-CN', 'en']) {
      await page.setViewportSize({ width, height: width > 760 ? 1000 : 844 });
      await locale(page, lang);
      for (const href of samples) {
        await open(page, href);
        const name = `${new URL(page.url()).pathname.slice(1)}-${lang}-${width}`;
        await layout(page, name);
        if (width === 1440 || width === 390) await page.screenshot({ path: path.join(output, name + '.png') });
      }
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await locale(page, 'en');
    for (const href of destinations) {
      await nav(page, href);
      check(`mobile destination ${href} accessible`, await page.locator('header nav a[aria-current="page"]').getAttribute('href') === href);
    }
    check('no fixture mutation', JSON.stringify(fixture) === original);
    check('no backend writes', writes.length === 0);
    check('no uncaught errors', errors.length === 0);
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ checks, issues, errors, writes, reads }, null, 2));
    console.log(JSON.stringify({ checks: checks.length, issues, errors, writes, reads: reads.length }, null, 2));
    assert.deepEqual(issues, [], 'Restored page layout issues');
  } finally { await browser.close(); }
}
main().catch(error => { fs.writeFileSync(path.join(output, 'failure.json'), JSON.stringify({ error: error.message, checks, issues, errors, writes }, null, 2)); console.error(error); process.exitCode = 1; });
