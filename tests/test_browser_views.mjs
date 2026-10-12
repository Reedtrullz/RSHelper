import assert from 'node:assert/strict';
import vm from 'node:vm';
import { harness } from './browser_harness.mjs';

const calls = [];
let failed = true;
const { context, elements } = harness(async (url, options = {}) => {
  calls.push({ url, options });
  return new Response(JSON.stringify(failed ? { error: 'fixture rejected' } : { name: 'Synthetic', profit: 1 }),
    { status: failed ? 409 : 200 });
});
vm.runInContext("accessMode='owner';authenticated=true;accessReady=true;capabilities={features:['private-state','daemon-control']}", context);
context.confirm = () => true;
const rendered = [];
const views = { market: 'renderMarket', paper: 'renderPaper', signals: 'renderSignals',
  watchlist: 'renderWatchlist', ge: 'renderGE', bank: 'renderBank', process: 'renderProcess',
  overview: 'renderOverview', activity: 'renderActivity' };
for (const [view, render] of Object.entries(views)) context[render] = () => rendered.push(view);
context.renderContextEmpty = () => {};
for (const view of Object.keys(views)) {
  vm.runInContext(`setView('${view}')`, context);
  assert.equal(rendered.at(-1), view, `${view} routes to its own renderer`);
}
vm.runInContext("setView('activity');setStrategy('manual')", context);
assert.equal(rendered.at(-1), 'activity', 'Activity strategy changes keep the active view');
vm.runInContext("setView('paper');setStrategy('auto')", context);
assert.equal(rendered.at(-1), 'paper', 'Trading strategy changes keep the active view');

let refreshes = 0;
context.fetchData = () => { refreshes++; };
for (const [id, value] of Object.entries({ ptItem: 'Synthetic', ptQty: '2', ptAction: 'open' })) {
  context.document.getElementById(id).value = value;
}
await vm.runInContext('paperTrade()', context);
assert.equal(refreshes, 0, 'failed mutation retains the current data');
assert.match(elements.get('statusText').textContent, /fixture rejected/);
assert.equal(elements.get('ptItem').value, 'Synthetic', 'failure preserves the draft');
await vm.runInContext('closePosition(7)', context);
await vm.runInContext('closePosition(7)', context);
const failedCloses = calls.filter(c => c.url === '/api/positions').map(c => JSON.parse(c.options.body));
assert.equal(failedCloses[0].operation_id, failedCloses[1].operation_id, 'retry retains the close operation');
failed = false;
await vm.runInContext('closePosition(7)', context);
assert.equal(refreshes, 1, 'successful close refreshes once');
await vm.runInContext('deleteTrade(5)', context);
assert.equal(refreshes, 2, 'successful journal deletion refreshes once');
const before = calls.length;
elements.get('ptQty').value = '0';
await vm.runInContext('paperTrade()', context);
assert.equal(calls.length, before, 'invalid quantities never send mutations');
console.log('browser view and mutation contracts passed');
