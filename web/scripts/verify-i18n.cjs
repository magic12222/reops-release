// Optional browser regression. Use an existing Playwright installation; no app dependency.
// Build first, then: node web/scripts/verify-i18n.cjs
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const dist = path.join(root, 'web/dist');
const output = path.join(root, 'output/playwright/i18n');
fs.mkdirSync(output, { recursive: true });
const checks = [], issues = [], pageErrors = [], writes = [];
let apiReads = 0, reportMode = 'empty', detailMode = 'ready', evidenceMode = 'empty';
const pendingDetails = [];
const check = (name, condition) => { assert(condition, name); checks.push(name); };

const report = source => ({ id: 'i18n-report', source, mode: 'offline-fixture-comparison', sample_count: 2,
  provenance: { raw_key: '原始报告字段，保持不变' }, groups: [{ suite: 'design', strategy: 'rule_based', sample_count: 2,
    case_ids: ['case-01', 'case-02'], fixture_model_calls: 1, real_model_calls: null, recovery_latency_ms: null,
    outcomes: { not_executed: 1, rejected: 0, result_unknown: 1 }, metrics: {
      detection_accuracy: { numerator: 1, denominator: 2, rate: .5, missing: 0, status: 'available' },
      plan_accuracy: { numerator: 0, denominator: 2, rate: null, missing: 1, status: 'missing_fields' },
    } }] });
const evidence = source => ({ source, run_id: 'raw-run-id', incident_id: 'incident-01', trace_id: 'trace-01',
  case_id: null, experiment_id: null, scenario: null, strategy: null, action: null, target: null, event_count: 2,
  execution_outcome_reported: 'unknown', verification_status_reported: 'recovered',
  verify_samples: [{ event_id: 'raw-event-id', observation_id: null, timestamp: null }],
  provenance: { normalized_evidence_sha256: 'raw-sha256', authenticated: false },
  conflicts: ['reported_recovery_conflict'], gaps: ['original_report_unavailable'] });

async function intercept(route) {
  const request = route.request(), url = new URL(request.url()), source = url.searchParams.get('source');
  if (!url.pathname.startsWith('/api/')) {
    const file = path.resolve(dist, '.' + url.pathname);
    if (file !== dist && !file.startsWith(dist + path.sep)) return route.abort();
    return route.fulfill({ path: fs.existsSync(file) && fs.statSync(file).isFile() ? file : path.join(dist, 'index.html') });
  }
  apiReads++;
  if (request.method() !== 'GET') { writes.push(url.pathname); return route.fulfill({ status: 403, body: '{}' }); }
  if (url.pathname === '/api/v1/benchmarks') {
    if (reportMode === 'error') return route.fulfill({ status: 503, body: '{}' });
    return route.fulfill({ json: { source, items: reportMode === 'empty' ? [] : [report(source)], total: reportMode === 'empty' ? 0 : 1 } });
  }
  if (url.pathname.startsWith('/api/v1/benchmarks/')) {
    if (detailMode === 'delayed') await new Promise(resolve => pendingDetails.push(resolve));
    return route.fulfill(detailMode === 'error' ? { status: 503, body: '{}' } : { json: report(source) });
  }
  if (url.pathname === '/api/v1/evaluation-evidence') return route.fulfill({ json: { source,
    items: evidenceMode === 'empty' ? [] : [evidence(source)], total: evidenceMode === 'empty' ? 0 : 1,
    offset: Number(url.searchParams.get('offset')), limit: 20, evaluation_sample_count: 0, recovery_success_rate: null } });
  if (url.pathname === '/api/v1/experiments/capabilities') return route.fulfill({ json: {
    entry: 'terminal', scenarios: [], request_enabled: false, request_blocked: false, execution: 'disabled' } });
  if (url.pathname === '/api/v1/experiments') return route.fulfill({ json: { items: [{ id: 'experiment-raw-id',
    state: 'waiting_operator', result: 'unknown', ground_truth: { injection: 'stop_api_once', root_cause: 'api_service_down' },
    incident_id: null, trace_id: null, authorization: 'not_requested', injection: 'not_attempted',
    recovery: 'not_attempted', verify: 'not_run', cleanup: 'not_run' }] } });
  return route.fulfill({ status: 503, body: '{}' });
}

async function language(page, locale) {
  if (await page.locator('html').getAttribute('lang') !== locale) await page.locator('.locale-toggle').click();
  await page.waitForFunction(expected => document.documentElement.lang === expected, locale);
}
async function goto(page, route) {
  await page.goto('http://127.0.0.1:4187' + route);
  await page.locator('h1:visible').first().waitFor();
  await page.evaluate(() => document.fonts.ready);
}
async function layout(page, name) {
  const problems = await page.evaluate(() => {
    const result = [];
    if (document.documentElement.scrollWidth > innerWidth + 1) result.push(`page overflow ${document.documentElement.scrollWidth}/${innerWidth}`);
    for (const el of document.querySelectorAll('h1,h2,.lab-caption-copy,.lab-sequence-copy,.studio-row-name,.arch-node strong')) {
      if (!el.checkVisibility() || el.closest('[hidden]')) continue;
      if (el.scrollWidth > el.clientWidth + 2) result.push(`${el.className || el.tagName}: ${el.scrollWidth}/${el.clientWidth}: ${el.textContent}`);
    }
    const toggle = document.querySelector('.locale-toggle').getBoundingClientRect();
    if (toggle.left < 0 || toggle.right > innerWidth) result.push('language switch outside viewport');
    return result;
  });
  checks.push(name + ' layout checked');
  issues.push(...problems.map(problem => name + ': ' + problem));
}

async function englishContent(page, name) {
  const untranslated = await page.evaluate(() => {
    const raw = '.locale-toggle,pre,code,.chamber-fact,.evidence-message,.record-section dd,.lab-key-evidence dd,.lab-action-boundary p,.lab-event-details h3,.lab-event-details dd';
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), found = [];
    while (walker.nextNode()) {
      const node = walker.currentNode, parent = node.parentElement;
      if (!parent?.checkVisibility() || parent.closest('[hidden]') || parent.closest(raw)) continue;
      if (/\p{Script=Han}/u.test(node.textContent)) found.push(node.textContent.trim());
    }
    return found;
  });
  check(name + ' English UI has no untranslated Chinese: ' + untranslated.join(' | '), untranslated.length === 0);
}

async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true,
    args: ['--no-proxy-server'] });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    await context.route('**/*', intercept);
    const page = await context.newPage();
    page.on('pageerror', error => pageErrors.push(error.message));
    await goto(page, '/');
    check('missing preference defaults to Chinese', await page.locator('html').getAttribute('lang') === 'zh-CN');
    await language(page, 'en');
    await page.getByLabel('Next overview demo stage', { exact: true }).click();
    check('Overview dynamic stage is translated', (await page.locator('.trace-message').innerText()) === 'A dependency fails.');
    check('Overview content switches to English', (await page.locator('.hero-kicker').innerText()).startsWith('Start with evidence'));
    check('English preference persisted', await page.evaluate(() => localStorage.getItem('reops.locale')) === 'en');
    check('document title translated', (await page.title()).includes('Failure is a beginning.'));
    await page.locator('header nav a[href="/architecture"]').click();
    check('SPA navigation preserves language', await page.locator('html').getAttribute('lang') === 'en');
    await page.locator('.layer-tab').nth(1).click();
    await page.locator('[data-architecture-node="safety"]').click();
    check('dynamic Architecture detail is English', (await page.locator('.arch-node-detail p').innerText()).includes('independent authorization'));
    await language(page, 'zh-CN');
    check('Architecture selection survives switching', await page.locator('[data-architecture-node="safety"]').getAttribute('aria-pressed') === 'true');
    check('dynamic Architecture detail switches to Chinese', (await page.locator('.arch-node-detail p').innerText()).includes('独立授权'));
    await language(page, 'en');
    for (let layer = 0; layer < 3; layer++) {
      await page.locator('.layer-tab').nth(layer).click();
      for (let node = 0; node < 6; node++) {
        await page.locator('.arch-node').nth(node).click();
        await englishContent(page, `Architecture layer ${layer} node ${node}`);
        await language(page, 'zh-CN');
        check(`Architecture layer ${layer} node ${node} detail retranslates`, /\p{Script=Han}/u.test(await page.locator('.arch-node-detail p').innerText()));
        await language(page, 'en');
      }
    }
    await goto(page, '/recovery');
    await page.reload();
    check('direct route and refresh restore English', (await page.locator('.lab-hero h1').innerText()).includes('Watch it recover.'));
    await page.locator('.lab-inject').click();
    for (let index = 0; index < 8; index++) {
      await page.waitForFunction(i => document.querySelector('.lab-progress')?.getAttribute('aria-valuenow') === String(i + 1), index);
      const position = await page.locator('.lab-progress').getAttribute('aria-valuenow');
      await language(page, 'zh-CN');
      check(`Recovery event ${index} survives English → Chinese`, await page.locator('.lab-progress').getAttribute('aria-valuenow') === position);
      await language(page, 'en');
      check(`Recovery event ${index} description updates`, !/\p{Script=Han}/u.test(await page.locator('.lab-caption').innerText()));
      await englishContent(page, `Recovery event ${index}`);
      await layout(page, `Recovery event ${index} en`);
      if (index < 7) await page.getByLabel('Next simulated event', { exact: true }).click();
    }
    check('dynamic final verification translated', (await page.locator('.lab-results').innerText()).includes('Service and business verification passed'));
    await page.locator('.lab-evidence > summary').click();
    await page.locator('.lab-event-details > summary').click();
    const rawRecovery = await page.locator('.lab-event-details pre').textContent();
    await language(page, 'zh-CN');
    check('raw simulation event remains byte-identical', await page.locator('.lab-event-details pre').textContent() === rawRecovery);
    await language(page, 'en');

    await page.locator('header nav a[href="/agent"]').click();
    await page.locator('.live-toolbar select').selectOption('offline_fixture');
    await page.locator('.agent-evidence-chamber').waitFor();
    check('integrated Agent evidence chamber remains mounted', await page.locator('.agent-evidence-wires').count() === 1);
    for (let run = 0; run < 3; run++) {
      const runButton = page.locator('.live-run-list > button').nth(run);
      const runId = await runButton.getAttribute('title');
      await runButton.click();
      await page.waitForFunction(id => document.querySelector('.execution-explorer')?.getAttribute('data-run-id') === id, runId);
      const buttons = page.locator('.event-index');
      const count = await buttons.count();
      if (run === 0) {
        await buttons.nth(3).click();
        const selected = await page.locator('.evidence-content').getAttribute('data-event-id');
        await page.locator('.agent-evidence-signal').first().click();
        const originalSignal = await page.locator('.agent-inspected-evidence pre').textContent();
        await language(page, 'zh-CN');
        check('integrated chamber diagnosis switches to Chinese', (await page.locator('.agent-core-copy > p').innerText()) === '服务不可用');
        await language(page, 'en');
        check('memoized chamber diagnosis switches to English', (await page.locator('.agent-core-copy > p').innerText()) === 'Service unavailable');
        check('chamber selected event survives translation', await page.locator('.evidence-content').getAttribute('data-event-id') === selected);
        check('chamber original selected evidence survives translation', await page.locator('.agent-inspected-evidence pre').textContent() === originalSignal);
        check('chamber evidence disclosure remains open', await page.locator('.agent-evidence-disclosure').getAttribute('open') !== null);
        await page.locator('.agent-evidence-disclosure > summary').click();
      }
      for (let event = 0; event < count; event++) {
        await buttons.nth(event).click();
        const id = await page.locator('.evidence-content').getAttribute('data-event-id');
        await language(page, 'zh-CN');
        check(`Agent run ${run} event ${event} selection persists`, await page.locator('.evidence-content').getAttribute('data-event-id') === id);
        await language(page, 'en');
        check(`Agent run ${run} event ${event} controls update`, await page.getByLabel('Next historical event', { exact: true }).count() === 1);
      }
    }
    await page.locator('.agent-evidence-disclosure > summary').click();
    await page.locator('.full-record > summary').click();
    const rawAgent = await page.locator('.raw-evidence pre').first().textContent();
    await language(page, 'zh-CN');
    check('Agent raw event unchanged', await page.locator('.raw-evidence pre').first().textContent() === rawAgent);
    await page.locator('header nav a[href="/recovery"]').click();
    check('cached Recovery progress persists across navigation', await page.locator('.lab-progress:visible').getAttribute('aria-valuenow') === '8');
    await language(page, 'en');

    await goto(page, '/benchmark');
    for (let metric = 0; metric < 5; metric++) {
      await page.locator('.studio-metric-switch button').nth(metric).click();
      await page.locator('.studio-row[data-method="rule"]').click();
      await page.locator('.studio-chart-heading select').selectOption('ascending');
      await language(page, 'zh-CN');
      check(`Benchmark metric ${metric} selection persists`, await page.locator('.studio-row[data-method="rule"]').getAttribute('aria-pressed') === 'true');
      await language(page, 'en');
      check(`Benchmark metric ${metric} heading translated`, !/\p{Script=Han}/u.test(await page.locator('.studio-metric-heading').innerText()));
      await englishContent(page, `Benchmark metric ${metric}`);
    }
    await page.locator('.studio-status').waitFor();
    check('empty report translated', (await page.locator('.studio-status').innerText()).includes('No imported reports'));
    reportMode = 'error';
    await page.locator('.studio-data-source select').selectOption('real');
    await page.getByRole('alert').filter({ hasText: 'Unable to load the report list' }).waitFor();
    const reads = apiReads;
    await language(page, 'zh-CN');
    check('settled async report error retranslates', (await page.locator('.studio-status').innerText()).includes('只读服务暂不可用'));
    await language(page, 'en');
    check('switching report language does not reload data', apiReads === reads);
    reportMode = 'ready'; detailMode = 'delayed';
    await page.getByRole('button', { name: 'Retry', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.studio-status')?.textContent.includes('Loading metrics'));
    await language(page, 'zh-CN');
    check('pending async status retranslates', (await page.locator('.studio-status').innerText()).includes('读取指标中'));
    detailMode = 'ready'; pendingDetails.splice(0).forEach(resolve => resolve());
    await page.locator('.studio-report-detail').waitFor();
    check('late report uses currently selected language', (await page.locator('.studio-report-detail').innerText()).includes('评测范围'));
    await page.locator('.benchmark-evaluation-group > summary').first().click();
    await language(page, 'en');
    check('loaded metric labels translate', (await page.locator('.benchmark-evaluation-rates').innerText()).includes('Detection accuracy'));
    check('missing metric count translates', (await page.locator('.benchmark-evaluation-rates').innerText()).includes('1 missing/unknown items'));
    evidenceMode = 'ready';
    await page.getByRole('button', { name: 'Evidence review', exact: true }).click();
    await page.locator('.benchmark-evaluation-group').waitFor();
    await page.locator('.benchmark-evaluation-group > summary').click();
    check('evidence fallback is English', (await page.locator('.benchmark-evaluation-group').innerText()).includes('Not provided'));
    await language(page, 'zh-CN');
    check('evidence details retranslate', (await page.locator('.benchmark-evaluation-group').innerText()).includes('未提供'));
    check('evidence protocol codes preserved', (await page.locator('.benchmark-evaluation-group').textContent()).includes('reported_recovery_conflict'));

    // Baseline page geometry in both languages. Dynamic content was checked above.
    reportMode = 'empty'; evidenceMode = 'empty';
    for (const width of [1440, 768, 390, 320]) for (const locale of ['zh-CN', 'en']) {
      await page.setViewportSize({ width, height: width > 760 ? 1000 : 844 });
      await language(page, locale);
      for (const route of ['/', '/architecture', '/agent', '/recovery', '/benchmark']) {
        await goto(page, route);
        if (route === '/agent') {
          await page.locator('.live-toolbar select').selectOption('offline_fixture');
          await page.locator('.agent-evidence-chamber').waitFor();
        }
        const name = `${route.slice(1) || 'overview'}-${locale}-${width}`;
        await layout(page, name);
        if (locale === 'en') await englishContent(page, name);
        if (width === 1440 || width === 390) await page.screenshot({ path: path.join(output, name + '.png') });
        if (route === '/recovery') {
          await page.locator('.lab-inject').click();
          for (let event = 0; event < 8; event++) {
            await layout(page, `${name} event ${event}`);
            if (event < 7) await page.locator('.lab-playback button').last().click();
          }
          if (width === 1440 || width === 390) await page.screenshot({ path: path.join(output, name + '-complete.png') });
        }
      }
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await language(page, 'en');
    await page.locator('.menu-toggle').click();
    await language(page, 'zh-CN');
    check('mobile menu stays open during translation', await page.locator('.menu-toggle').getAttribute('aria-expanded') === 'true');
    await language(page, 'en');
    await page.locator('header nav a[href="/architecture"]').click();
    check('mobile navigation preserves English', await page.locator('html').getAttribute('lang') === 'en');
    await page.evaluate(() => localStorage.setItem('reops.locale', 'unsupported'));
    await page.reload();
    check('invalid saved preference falls back to Chinese', await page.locator('html').getAttribute('lang') === 'zh-CN');
    await goto(page, '/missing-page');
    check('404 is Chinese', (await page.locator('h1').innerText()) === '页面不存在');
    await language(page, 'en');
    check('404 switches to English', (await page.locator('h1').innerText()) === 'Page not found');
    const sibling = await context.newPage();
    await goto(sibling, '/architecture');
    await language(page, 'zh-CN');
    await sibling.waitForFunction(() => document.documentElement.lang === 'zh-CN');
    check('language synchronizes across tabs', true);

    const denied = await browser.newContext({ reducedMotion: 'reduce' });
    await denied.route('**/*', intercept);
    await denied.addInitScript(() => Object.defineProperty(window, 'localStorage', { get() { throw new Error('Storage denied'); } }));
    const blocked = await denied.newPage();
    blocked.on('pageerror', error => pageErrors.push(error.message));
    await goto(blocked, '/architecture');
    await language(blocked, 'en');
    check('blocked storage still permits immediate translation', (await blocked.locator('h1').innerText()).includes('Built to recover.'));
    const animated = await browser.newContext({ reducedMotion: 'no-preference', viewport: { width: 1440, height: 1000 } });
    await animated.route('**/*', intercept);
    const playing = await animated.newPage();
    playing.on('pageerror', error => pageErrors.push(error.message));
    await goto(playing, '/recovery');
    await playing.locator('.lab-workbench').scrollIntoViewIfNeeded();
    await playing.locator('.lab-inject').click();
    await playing.waitForFunction(() => Number(document.querySelector('.lab-progress')?.getAttribute('aria-valuenow')) > 0);
    const beforeSwitch = Number(await playing.locator('.lab-progress').getAttribute('aria-valuenow'));
    await language(playing, 'en');
    check('active Recovery playback does not reset on translation', Number(await playing.locator('.lab-progress').getAttribute('aria-valuenow')) >= beforeSwitch);
    await playing.waitForFunction(before => Number(document.querySelector('.lab-progress')?.getAttribute('aria-valuenow')) > before, beforeSwitch);
    check('active Recovery playback continues after translation', true);
    await playing.locator('header nav a[href="/agent"]').click();
    await playing.locator('.live-toolbar select').selectOption('offline_fixture');
    await playing.locator('.agent-evidence-chamber').waitFor();
    await playing.locator('.play-button').click();
    const playingEvent = await playing.locator('.evidence-content').getAttribute('data-event-id');
    await language(playing, 'zh-CN');
    check('Agent remains playing during translation', await playing.locator('.play-button').getAttribute('aria-label') === '暂停历史回放');
    await playing.waitForFunction(id => document.querySelector('.evidence-content')?.getAttribute('data-event-id') !== id, playingEvent);
    check('Agent playback advances after translation', true);
    check('no backend writes', writes.length === 0);
    check('no uncaught page errors', pageErrors.length === 0);
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ checks, issues, pageErrors, writes, apiReads }, null, 2));
    console.log(JSON.stringify({ checks: checks.length, issues, pageErrors, writes, apiReads }, null, 2));
    assert.deepEqual(issues, [], 'Unexpected text clipping or page overflow');
  } finally { await browser.close(); }
}
main().catch(error => {
  pendingDetails.splice(0).forEach(resolve => resolve());
  fs.writeFileSync(path.join(output, 'failure.json'), JSON.stringify({ error: error.message, checks, issues, pageErrors, writes }, null, 2));
  console.error(error); process.exitCode = 1;
});
