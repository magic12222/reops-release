/* Real temporary file lifecycle plus filesystem failures; no phone/network/credential. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const studio = process.env.REOPS_DEVECO_HOME || 'D:/DevTools/Huawei/DevEcoStudio';
const ts = require(path.join(studio, 'tools/hvigor/hvigor/node_modules/typescript'));
const output = path.resolve(__dirname, '../artifacts');
fs.mkdirSync(output, { recursive: true });
const directory = fs.mkdtempSync(path.join(output, 'cache-probe-'));
const actual = path.join(directory, 'reops-local-probe-v1.txt');
const virtual = '/app-private-cache/reops-local-probe-v1.txt';
let failUnlink = false, failWrite = false, failRead = false, mismatch = false, partial = false;
function target(value) { assert.equal(value, virtual); return actual; }
const native = {
  OpenMode: { READ_WRITE: 1, CREATE: 2, TRUNC: 4 },
  accessSync: value => fs.existsSync(target(value)),
  readTextSync: value => {
    if (failRead) throw new Error('read denied');
    const text = fs.readFileSync(target(value), 'utf8');
    return mismatch ? text + 'changed' : text;
  },
  openSync: (value, mode) => { assert.equal(mode, 7); return { fd: fs.openSync(target(value), 'w+') }; },
  writeSync: (fd, value) => { if (failWrite) throw new Error('write denied'); return fs.writeSync(fd, partial ? value.slice(0, -1) : value); },
  fsyncSync: fd => fs.fsyncSync(fd),
  closeSync: file => fs.closeSync(file.fd),
  unlinkSync: value => { if (failUnlink) throw new Error('unlink denied'); fs.unlinkSync(target(value)); }
};
const moduleValue = { exports: {} };
const source = fs.readFileSync(path.resolve(__dirname, '../entry/src/main/ets/services/LocalCacheProbe.ets'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } }).outputText;
new Function('require', 'module', 'exports', compiled)(name => {
  assert.equal(name, '@kit.CoreFileKit'); return { fileIo: native };
}, moduleValue, moduleValue.exports);
const { LocalCacheProbe } = moduleValue.exports;
const probe = new LocalCacheProbe('/app-private-cache');
let passed = 0;
function test(name, fn) { fn(); passed++; console.log('PASS ' + name); }
test('missing file is never healthy and check never creates it', () => {
  assert.equal(probe.check().status, 'missing'); assert.equal(fs.existsSync(actual), false);
});
test('real write/fsync/readback is healthy', () => {
  assert.equal(probe.rebuild().status, 'healthy'); assert.ok(fs.statSync(actual).size > 0);
  assert.equal(new LocalCacheProbe('/app-private-cache').check().status, 'healthy');
});
test('fault deletes the actual dedicated file; repeated probes stay failed', () => {
  assert.equal(probe.injectMissing().status, 'missing'); assert.equal(fs.existsSync(actual), false);
  assert.equal(probe.check().status, 'missing'); assert.equal(probe.check().status, 'missing');
});
test('rebuild restores the actual file and readback', () => {
  assert.equal(probe.rebuild().status, 'healthy'); assert.equal(probe.check().status, 'healthy');
});
test('failed deletion cannot fabricate a missing-file fault', () => {
  failUnlink = true; assert.equal(probe.injectMissing().status, 'healthy'); failUnlink = false;
  assert.equal(fs.existsSync(actual), true);
});
test('write failure, partial write and readback mismatch cannot confirm recovery', () => {
  failWrite = true; assert.equal(probe.rebuild().status, 'unavailable'); failWrite = false;
  partial = true; assert.equal(probe.rebuild().status, 'unavailable'); partial = false;
  assert.equal(probe.check().status, 'invalid');
  assert.equal(new LocalCacheProbe('/app-private-cache').check().status, 'invalid');
  mismatch = true; assert.equal(probe.rebuild().status, 'invalid'); mismatch = false;
});
test('read errors and malformed contents cannot become healthy', () => {
  failRead = true; assert.equal(probe.check().status, 'unavailable'); failRead = false;
  fs.writeFileSync(actual, 'invalid data'); assert.equal(probe.check().status, 'invalid');
});
test('no caller-selected file name; unavailable cache root fails closed', () => {
  assert.throws(() => new LocalCacheProbe('')); assert.throws(() => new LocalCacheProbe('../'));
  assert.equal(probe.rebuild().status, 'healthy');
});
console.log(`${passed} passed; real temporary file IO with injected failure cases, not a device result.`);
