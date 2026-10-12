import assert from 'node:assert/strict';
import vm from 'node:vm';
import { harness, source } from './browser_harness.mjs';

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

const rejectedForm = harness(async () => new Response(JSON.stringify({
  ok: false, code: 'invalid_request', message: 'alert_above must be an integer >= 0'
}), {status: 400, headers: {'Content-Type': 'application/json'}}));
vm.runInContext("authenticated=true;ownerToken='synthetic';accessMode='owner'", rejectedForm.context);
rejectedForm.context.document.getElementById('wlAbove').value = '-1';
rejectedForm.context.document.getElementById('wlBelow').value = '';
let removed = false;
rejectedForm.context.document.querySelectorAll = () => [{remove() {removed=true}}];
let errorMessage = '';
rejectedForm.context.setStatus = (message) => {errorMessage=message};
await rejectedForm.context.saveWatchAlerts(2);
assert.match(errorMessage, /invalid_request.*alert_above/, 'mutation error displays server code and message');
assert.equal(rejectedForm.context.document.getElementById('wlAbove').value, '-1', 'invalid input remains editable');
assert.equal(removed, false, 'validation error keeps the form open');

console.log('browser owner flow and mutation error regressions passed');

// One close action keeps a single operation id across ambiguous retries: the
// id is allocated on first click and only cleared by a successful response.
const closeHarness = harness(async (url, options = {}) => {
  closeCalls.push({ url: String(url), body: options.body ? JSON.parse(options.body) : null });
  if (String(url)==='/api/ge') return new Response(JSON.stringify({initialized:true,revision:5}),{status:200});
  if (closeCalls.filter(call=>call.body).length === 1) return new Response(JSON.stringify({ ok: false, code: 'network', message: 'lost' }), { status: 500, headers: { 'Content-Type': 'application/json' } });
  return new Response(JSON.stringify({ ok: true, name: 'Nature rune', profit: 436 }), { status: 200, headers: { 'Content-Type': 'application/json' } });
});
const closeCalls = [];
vm.runInContext("accessReady=true;accessMode='owner';authenticated=true;ownerToken='synthetic';meta={control:false};capabilities={mode:'owner',features:['market','private-state']}", closeHarness.context);
closeHarness.context.confirm = () => true;
closeHarness.context.fetchData = () => {};
closeHarness.context.setStatus = () => {};
await closeHarness.context.closePosition(7);
await closeHarness.context.closePosition(7);
const queuedCalls=closeCalls.filter(call=>call.body);
assert.equal(queuedCalls.length, 2, 'both retry clicks reached the mutation API');
assert.equal(queuedCalls[0].url, '/api/paper');
assert.equal(queuedCalls[0].body.action, 'queue-sale');
assert.equal(queuedCalls[0].body.expected_revision, 5);
assert.equal(queuedCalls[0].body.operation_id, queuedCalls[1].body.operation_id,
  'a retried close reuses the same operation id');
assert.match(queuedCalls[0].body.operation_id,
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  'close operation id is a canonical UUID4');
assert.equal(queuedCalls[1].body.operation_id, queuedCalls[0].body.operation_id);
// A successful close clears the id, so the next close is a distinct action.
assert.equal(vm.runInContext('Object.keys(pendingPaperOps).length', closeHarness.context),0,
  'success clears the retained operation id');
console.log('browser close retry operation-id reuse passed');

// Successful observations and failed attempts remain separate in the visible footer.
vm.runInContext("meta={market_data:{latest:{source:'wiki',delivery:'stale-cache',stale:true,last_success_at:100,last_attempt_at:200},'5m':{source:'ge-tracker',volume_kind:'standing-orders',stale:false}}};updateFooter()",ownerHarness.context);
assert.match(ownerHarness.context.document.getElementById('sourceBadge').textContent,/stale.*mixed sources/);
assert.match(ownerHarness.context.document.getElementById('kbdHint').textContent,/proxy.*fills unavailable/);
assert.match(ownerHarness.context.document.getElementById('lastUpdated').textContent,/Last success:/);
assert.match(ownerHarness.context.document.getElementById('lastUpdated').title,/Last attempt:/);
vm.runInContext("meta={market_data:{latest:{source:'unknown'},'5m':{volume_kind:'unknown'}}};updateFooter()",ownerHarness.context);
assert.equal(ownerHarness.context.document.getElementById('lastUpdated').textContent,'Last success unknown');
