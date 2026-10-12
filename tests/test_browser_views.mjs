import assert from 'node:assert/strict';
import vm from 'node:vm';
import test from 'node:test';
import { harness } from './browser_harness.mjs';

test('entry stance is separate from daemon liveness and mutation retries retain identity',async()=>{
  const requests=[];let fail=true;
  const {context}=harness(async(url,options={})=>{
    requests.push({url,body:JSON.parse(options.body)});
    return new Response(JSON.stringify(fail?{error:'Synthetic failure'}:{mode:'entries-paused'}),{status:fail?500:200});
  });
  vm.runInContext("accessMode='owner';authenticated=true;capabilities={features:['daemon-control','private-state']};meta={control:true}",context);
  context.window.prompt=()=> 'Synthetic reason';
  context.fetchData=()=>Promise.resolve();
  const notice=vm.runInContext("traderNoticeHtml({running:true,trading_mode:{mode:'entries-paused',reason:'<Synthetic>'}})",context);
  assert.match(notice,/New entries paused/);
  assert.match(notice,/Auto-trader running/);
  assert.match(notice,/&lt;Synthetic&gt;/);
  await vm.runInContext("tradingModeControl('entries-paused',0)",context);
  fail=false;
  await vm.runInContext("tradingModeControl('entries-paused',0)",context);
  assert.equal(requests.length,2);
  assert.equal(requests[0].body.operation_id,requests[1].body.operation_id);
  assert.equal(requests[0].body.expected_revision,0);
  assert.equal(requests[0].body.reason,'Synthetic reason');
  vm.runInContext('authenticated=false',context);
  await vm.runInContext("tradingModeControl('running',1)",context);
  assert.equal(requests.length,2);
});

const calls = [];
let failed = true;
const { context, elements } = harness(async (url, options = {}) => {
  calls.push({ url, options });
  if(url==='/api/ge')return new Response(JSON.stringify({initialized:true,revision:5}),{status:200});
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
const failedCloses = calls.filter(c => c.url === '/api/paper' && JSON.parse(c.options.body).action==='queue-sale').map(c => JSON.parse(c.options.body));
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
test('processing displays unknown evidence without claiming verified hourly profit',async()=>{
  const {context}=ownerContext(async()=>new Response(JSON.stringify({recipes:[{
    name:'Synthetic',skill:'smithing',inputs:[],model_profit:20,model_gp_per_hour:100,
    profit:null,gp_per_hour:null,eligibility:'unknown',recipe_economics:{
      requirements:null,evidence_gaps:['rate unverified <script>'],outputs_per_run:1,
      success_probability:null,reviewed_on:null,source_url:null}}]})));
  vm.runInContext("view='process'",context);
  await vm.runInContext('renderProcess()',context);
  const content=context.document.getElementById('listBody').innerHTML;
  assert.match(content,/Illustrative GP\/hr/);
  assert.match(content,/unknown/);
  assert.match(content,/rate unverified &lt;script&gt;/);
  assert.match(content,/success unknown/);
});
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
test('confidence discloses unavailable history and displays a valid zero score',async()=>{
  let row={available:false,reason:'Wiki history unavailable <script>'};
  const {context}=ownerContext(async()=>new Response(JSON.stringify({'1':row})));
  context.document.getElementById('contextPanel').contains=()=>true;
  vm.runInContext('selectedId=1;loadConfidence(1)',context);
  await new Promise(resolve=>setImmediate(resolve));
  const tile=context.document.getElementById('confTile');
  assert.match(tile.innerHTML,/Confidence unavailable/);
  assert.match(tile.innerHTML,/&lt;script&gt;/);
  row={confidence:0,datapoints:8,window_hours:1};
  vm.runInContext('loadConfidence(1)',context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(tile.innerHTML,/0%/);
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
test('Activity retrieves one bounded snapshot and preserves its page on refresh',async()=>{
  const urls=[];
  const {context}=ownerContext(async url=>{
    urls.push(url);
    return new Response(JSON.stringify({revision:'same',total_count:123,filtered_count:123,
      trades:[{id:1,name:'Synthetic page row',qty:1,buy_price:100,sell_price:120,profit:18}],
      next_cursor:'next-cursor',pnl:{},history:{buckets:[],eras:[],items:[]}}));
  });
  vm.runInContext("view='activity';activityCursor='current-cursor'",context);
  await vm.runInContext('renderActivity()',context);
  assert.equal(urls.length,1);
  assert.match(urls[0],/^\/api\/activity\?/);
  assert.match(urls[0],/cursor=current-cursor/);
  assert.match(context.document.getElementById('listBody').innerHTML,/Synthetic page row/);
  assert.match(context.document.getElementById('listBody').innerHTML,/next-cursor/);
  assert.equal(vm.runInContext('activityCursor',context),'current-cursor');
});
test('Activity changed-revision response asks for explicit restart',async()=>{
  const {context}=ownerContext(async()=>new Response(JSON.stringify({restart:true,revision:'changed',trades:[]})));
  vm.runInContext("view='activity';activityCursor='old-cursor'",context);
  context.document.getElementById('listBody').innerHTML='previous page';
  await vm.runInContext('renderActivity()',context);
  assert.match(context.document.getElementById('listBody').innerHTML,/Restart Activity/);
  assert.match(context.document.getElementById('listBody').innerHTML,/previous page/);
  assert.equal(vm.runInContext('activityCursor',context),'old-cursor');
});
test('Activity applying UTC dates resets continuation and preserves filters',async()=>{
  const urls=[];
  const {context}=ownerContext(async url=>{
    urls.push(url);
    return new Response(JSON.stringify({trades:[],pnl:{},history:{buckets:[],items:[],eras:[]}}));
  });
  vm.runInContext("view='activity';activityCursor='old'",context);
  context.document.getElementById('activitySince').value='2026-10-11';
  context.document.getElementById('activityUntil').value='2026-10-12';
  vm.runInContext('applyActivityFilters()',context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(urls[0],/since=2026-10-11/);
  assert.match(urls[0],/until=2026-10-12/);
  assert.doesNotMatch(urls[0],/cursor=/);
});
test('Activity strategy changes reset the cursor and retain unapplied date drafts',async()=>{
  const {context}=ownerContext(async()=>new Response('{}'));
  vm.runInContext("view='activity';activityCursor='old'",context);
  const bar=context.document.getElementById('viewbar');
  const date=context.document.getElementById('activitySince');date.value='2026-10-11';
  bar.querySelectorAll=()=>[date];
  let content='';
  Object.defineProperty(bar,'innerHTML',{get(){return content;},set(value){content=value;date.value='';}});
  vm.runInContext("setStrategy('auto')",context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(vm.runInContext('activityCursor',context),null);
  assert.equal(date.value,'2026-10-11');
});
test('watch alert editor submits explicit crossing policy and keeps draft on failure',async()=>{
  let sent;
  const {context}=ownerContext(async(url,options)=>{
    sent=JSON.parse(options.body);
    return new Response(JSON.stringify({error:'fixture rejected'}),{status:400});
  });
  for(const [id,value] of Object.entries({wlAbove:'100',wlBelow:'',wlMode:'reminder',wlCooldown:'900',wlHysteresis:'10'}))
    context.document.getElementById(id).value=value;
  await vm.runInContext('saveWatchAlerts(561)',context);
  assert.deepEqual(sent.alert_policy,{mode:'reminder',cooldown_sec:900,hysteresis_gp:10});
  assert.equal(context.document.getElementById('wlAbove').value,'100');
  assert.match(context.document.getElementById('statusText').textContent,/fixture rejected/);
});
