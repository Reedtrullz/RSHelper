import assert from 'node:assert/strict';
import vm from 'node:vm';
import test from 'node:test';
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

function ownerContext(fetchImpl){
  const fixture=harness(fetchImpl);
  vm.runInContext("accessMode='owner';authenticated=true;accessReady=true;capabilities={features:['private-state','market']}",fixture.context);
  return fixture;
}
function deferred(){
  let resolve;
  const promise=new Promise(r=>{resolve=r;});
  return {promise,resolve};
}
test('late watchlist response cannot replace the newly selected market view',async()=>{
  const response=deferred();
  const {context,elements}=ownerContext(()=>response.promise);
  context.renderMarket=()=>{context.document.getElementById('listBody').innerHTML='current market';};
  context.renderContextEmpty=()=>{};
  vm.runInContext("view='watchlist'",context);
  const pending=vm.runInContext('renderWatchlist()',context);
  vm.runInContext("setView('market')",context);
  response.resolve(new Response(JSON.stringify({items:[]})));
  await pending;
  assert.equal(elements.get('listBody').innerHTML,'current market');
});
test('older bank request cannot replace a newer dataset',async()=>{
  const responses=[deferred(),deferred()];let index=0;
  const {context}=ownerContext(()=>responses[index++].promise);
  vm.runInContext("view='bank'",context);
  const older=vm.runInContext('renderBank()',context),newer=vm.runInContext('renderBank()',context);
  responses[1].resolve(new Response(JSON.stringify({items:[],total_value:200})));
  await newer;
  responses[0].resolve(new Response(JSON.stringify({items:[],total_value:100})));
  await older;
  assert.equal(vm.runInContext('bankData.total_value',context),200);
});
test('late confidence response cannot write the next selected item tile',async()=>{
  const response=deferred();
  const {context}=ownerContext(()=>response.promise);
  const panel=context.document.getElementById('contextPanel');panel.contains=()=>true;
  context.document.getElementById('confTile').innerHTML='current item';
  vm.runInContext("selectedId=1;loadConfidence(1);selectedId=2",context);
  response.resolve(new Response(JSON.stringify({'1':{confidence:.5,datapoints:1,window_hours:1}})));
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(context.document.getElementById('confTile').innerHTML,'current item');
});
test('overlapping refresh calls coalesce network acquisition',async()=>{
  const response=deferred();let requests=0;
  const {context}=ownerContext(async()=>{requests++;await response.promise;return new Response(JSON.stringify({items:[],signals:[],watch_ids:[]}));});
  context.renderMarket=()=>{};context.renderTopbar=()=>{};context.updateBadges=()=>{};context.updateFooter=()=>{};
  const first=vm.runInContext('fetchData()',context),second=vm.runInContext('fetchData()',context);
  assert.equal(requests,3,'only one scan/meta/signals flight may run');
  response.resolve();await Promise.all([first,second]);
});
test('refresh retains trade form values, focus and selection across replacement',async()=>{
  const {context,elements}=ownerContext(async()=>new Response('{}'));
  vm.runInContext("view='paper'",context);
  const bar=context.document.getElementById('viewbar');
  const ids=['ptItem','ptQty','ptAction'];
  let focused=null;
  function field(id,value){return {id,value,checked:false,selectionStart:2,selectionEnd:4,
    focus(){focused=this;},setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}};}
  for(const [id,value] of [['ptItem','Synthetic draft'],['ptQty','7'],['ptAction','instant']])elements.set(id,field(id,value));
  context.document.activeElement=elements.get('ptItem');
  bar.querySelectorAll=()=>ids.map(id=>elements.get(id));
  Object.defineProperty(bar,'innerHTML',{set(){for(const id of ids)elements.set(id,field(id,''));},get(){return '';}});
  await vm.runInContext('renderPaper()',context);
  assert.equal(elements.get('ptItem').value,'Synthetic draft');
  assert.equal(elements.get('ptQty').value,'7');
  assert.equal(elements.get('ptAction').value,'instant');
  assert.equal(focused,elements.get('ptItem'));
  assert.equal(focused.selectionStart,2);assert.equal(focused.selectionEnd,4);
});
test('late failed view request cannot replace another view with its error',async()=>{
  const response=deferred();
  const {context,elements}=ownerContext(()=>response.promise);
  context.renderMarket=()=>{context.document.getElementById('listBody').innerHTML='current market';};
  context.renderContextEmpty=()=>{};
  vm.runInContext("view='ge'",context);
  const pending=vm.runInContext('renderGE()',context);
  vm.runInContext("setView('market')",context);
  response.resolve(new Response('{}',{status:500}));await pending;
  assert.equal(elements.get('listBody').innerHTML,'current market');
});
test('owner disconnect prevents a pending bank render from restoring private data',async()=>{
  const response=deferred();
  const {context,elements}=ownerContext(()=>response.promise);
  vm.runInContext("view='bank'",context);
  const pending=vm.runInContext('renderBank()',context);
  vm.runInContext('disconnectOwner()',context);
  const disconnected=elements.get('listBody').innerHTML;
  response.resolve(new Response(JSON.stringify({items:[],total_value:123456})));
  await pending;
  assert.equal(elements.get('listBody').innerHTML,disconnected);
  assert.equal(vm.runInContext('bankData',context),null);
});
test('a failed bank refresh keeps good content and panel scroll',async()=>{
  const {context,elements}=ownerContext(async()=>new Response('{}',{status:500}));
  vm.runInContext("view='bank'",context);
  const body=context.document.getElementById('listBody');body.innerHTML='good bank data';body.scrollTop=230;
  let content=body.innerHTML;
  Object.defineProperty(body,'innerHTML',{get(){return content;},set(value){content=value;body.scrollTop=0;}});
  const panel=context.document.getElementById('contextPanel');panel.innerHTML='good bank summary';panel.scrollTop=70;
  await vm.runInContext('renderBank()',context);
  assert.equal(elements.get('listBody').innerHTML,'good bank data');
  assert.equal(panel.innerHTML,'good bank summary');
  assert.equal(body.scrollTop,230);assert.equal(panel.scrollTop,70);
  assert.match(elements.get('statusText').textContent,/Bank API failed/);
});
test('successful bank refresh restores panel scroll after DOM replacement',async()=>{
  const {context}=ownerContext(async()=>new Response(JSON.stringify({items:[],total_value:200})));
  vm.runInContext("view='bank'",context);
  const body=context.document.getElementById('listBody');body.scrollTop=230;
  let content='previous bank';
  Object.defineProperty(body,'innerHTML',{get(){return content;},set(value){content=value;body.scrollTop=0;}});
  await vm.runInContext('renderBank()',context);
  assert.equal(vm.runInContext('bankData.total_value',context),200);
  assert.equal(body.scrollTop,230);
});
test('price and margin charts share the current item without cancelling one another',async()=>{
  const {context}=ownerContext(async()=>new Response(JSON.stringify({points:[]})));
  const notes=[];
  for(const id of ['spark','marginChart'])context.document.getElementById(id).parentNode={appendChild(node){notes.push(id);}};
  vm.runInContext('selectedId=1;drawSpark(1);drawMargin(1)',context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(notes.sort(),['marginChart','spark']);
});
test('public market refresh parses only the scan response',async()=>{
  const urls=[];
  const {context}=harness(async url=>{urls.push(url);return new Response(JSON.stringify({items:[],market_data:{}}));});
  vm.runInContext("accessMode='public-demo';accessReady=true;capabilities={features:['market']}",context);
  context.renderMarket=()=>{};context.renderTopbar=()=>{};context.updateBadges=()=>{};context.updateFooter=()=>{};
  await vm.runInContext('fetchData()',context);
  assert.deepEqual(urls,['/api/scan']);
  assert.equal(context.document.getElementById('statusText').textContent,'Connected');
});
