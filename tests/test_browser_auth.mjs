import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/rshelper/dashboard/scripts.py', import.meta.url), 'utf8');
const scripts = ['SCRIPT_CORE', 'SCRIPT_CHARTS', 'SCRIPT_VIEWS'].map(name => {
  const match = source.match(new RegExp(`${name} = r"""([\\s\\S]*?)"""`));
  assert.ok(match, `${name} exists`);
  return match[1];
});
const bundle = scripts.join('\n').replace(
  /initializeAccess\(\)\.then\(\(\)=>\{fetchData\(\);if\(authenticated\)subscribeSSE\(\);\}\);\s*setInterval\(tick,1000\);\s*$/,
  '');

function harness(fetchImpl) {
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, { id, textContent: '', className: '', innerHTML: '', style: {},
        classList: { toggle() {} }, remove() {}, appendChild() {}, addEventListener() {} });
      return elements.get(id);
    },
    createElement(tag) { return { tag, style: {}, classList: { add() {}, remove() {} }, appendChild() {} }; },
    body: { appendChild() {}, insertBefore() {}, replaceChildren() {}, firstChild: null },
    addEventListener() {},
    querySelectorAll() { return []; },
  };
  const window = { location: { reload() {} } };
  const context = vm.createContext({ document, window, fetch: fetchImpl, AbortController, AbortSignal,
    Date, URLSearchParams, setTimeout, clearTimeout, setInterval() {}, console, JSON, Math, String, Object,
    Promise, Error, TypeError, DOMException, Headers, Response });
  vm.runInContext(bundle, context, { filename: 'dashboard.js' });
  return { context, elements };
}

const calls = [];
const publicHarness = harness(async (url, options = {}) => {
  calls.push({ url: String(url), options });
  const body = String(url) === '/api/capabilities'
    ? { mode: 'public-demo', features: ['market', 'static', 'health'] }
    : { items: [] };
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
});
assert.equal(typeof publicHarness.context.apiFetch, 'function', 'all dashboard requests use apiFetch');
assert.equal(typeof publicHarness.context.initializeAccess, 'function', 'browser starts from capabilities');
assert.equal(typeof publicHarness.context.connectOwner, 'function', 'owner can connect with a token');
assert.equal(typeof publicHarness.context.disconnectOwner, 'function', 'owner can disconnect');
assert.equal(typeof publicHarness.context.apiFetch, 'function', 'all dashboard requests use apiFetch');

await vm.runInContext('initializeAccess()', publicHarness.context);
assert.equal(publicHarness.context.document.getElementById('btnGE').style.display, 'none',
  'the existing uppercase GE navigation ID is hidden in public mode');
assert.equal(calls[0].url, '/api/capabilities');
assert.equal(calls[0].options.headers?.Authorization, undefined);
await vm.runInContext('fetchData()', publicHarness.context);
assert.ok(calls.some(c => c.url === '/api/scan'), 'public market scan still loads');
assert.ok(!calls.some(c => ['/api/meta', '/api/signals'].includes(c.url)),
  'public mode never requests private metadata or signals');
vm.runInContext('sseLastEvent=Date.now()-90001;tick()', publicHarness.context);
assert.equal(vm.runInContext('sseOk', publicHarness.context), false,
  'public polling never claims a private SSE connection after the retry interval');
assert.ok(!calls.some(c => c.url === '/api/events'), 'public polling never subscribes to private SSE');
publicHarness.context.renderMarket = () => {};
publicHarness.context.renderContextEmpty = () => {};
vm.runInContext("setView('watchlist')", publicHarness.context);
assert.equal(vm.runInContext('view', publicHarness.context), 'market', 'public mode cannot enter private views');

const ownerCalls = [];
let slowSignal;
const ownerHarness = harness(async (url, options = {}) => {
  ownerCalls.push({ url: String(url), options });
  if (String(url) === '/api/trades/slow') return new Promise((resolve, reject) => {
    slowSignal = options.signal;
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
  });
  const body = String(url) === '/api/capabilities'
    ? { mode: 'owner', features: ['market', 'static', 'health', 'private-state'] }
    : { watch_ids: [], unread_alerts: 0 };
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
});
await vm.runInContext('initializeAccess()', ownerHarness.context);
await vm.runInContext('fetchData()', ownerHarness.context);
assert.deepEqual(ownerCalls.map(c => c.url), ['/api/capabilities'],
  'disconnected owner mode asks for a token without probing protected market APIs');
await vm.runInContext("connectOwner('private-test-token')", ownerHarness.context);
assert.deepEqual(ownerCalls.slice(0, 2).map(c => c.url), ['/api/capabilities', '/api/meta']);
assert.equal(ownerCalls[1].options.headers.get('Authorization'), 'Bearer private-test-token');
assert.equal(ownerCalls[1].url.includes('private-test-token'), false, 'credentials never enter URLs');
assert.ok(ownerCalls.slice(2).filter(c => c.url.startsWith('/api/')).every(c =>
  c.options.headers.get('Authorization') === 'Bearer private-test-token'), 'owner API requests carry Authorization');
ownerHarness.context.meta = { control: true };
assert.equal(ownerHarness.context.traderControlHtml({ running: false }), '',
  'daemon controls stay hidden unless capabilities advertise them');
const pending = ownerHarness.context.apiFetch('/api/trades/slow').catch(() => {});
await Promise.resolve();
vm.runInContext("viewRows=[{id:'private-row'}]", ownerHarness.context);
ownerHarness.context.disconnectOwner();
await pending;
assert.equal(slowSignal.aborted, true, 'disconnect aborts requests from the owner session');
assert.equal(vm.runInContext('ownerToken', ownerHarness.context), '', 'disconnect clears the in-memory token');
assert.equal(vm.runInContext('viewRows.length', ownerHarness.context), 0, 'disconnect clears private view rows');
await assert.rejects(vm.runInContext("apiFetch('/api/meta')", publicHarness.context), /Owner connection required/);
assert.equal(calls.filter(c => c.url === '/api/meta').length, 0, 'public mode blocks accidental private fetches');
assert.ok(!source.includes('new EventSource('), 'authenticated SSE uses fetch streaming');

console.log('browser owner flow regressions passed');
