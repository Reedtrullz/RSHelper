import assert from 'node:assert/strict';
import vm from 'node:vm';
import test from 'node:test';
import { harness } from './browser_harness.mjs';

test('private review retries retain operation identity and free text stays out of URLs',async()=>{
  const calls=[];const {context,elements}=harness(async(url,options={})=>{
    calls.push({url,body:JSON.parse(options.body)});
    return new Response(JSON.stringify({error:'Synthetic failure'}),{status:500});
  });
  vm.runInContext("authenticated=true;accessReady=true;accessMode='owner';capabilities={features:['private-state']};reviewsState={can_write:true,revision:0};reviewLotUid='11111111-1111-4111-8111-111111111111'",context);
  for(const [id,value] of Object.entries({reviewHypothesis:'<private>',reviewPlan:'Target',reviewTags:'reversion',reviewOutcome:'Followed plan'}))elements.set(id,{value});
  await vm.runInContext('appendReview(false)',context);await vm.runInContext('appendReview(false)',context);
  assert.equal(calls.length,2);assert.equal(calls[0].url,'/api/reviews');
  assert.equal(calls[0].body.operation_id,calls[1].body.operation_id);
  assert.equal(calls[0].body.entry.hypothesis,'<private>');
  vm.runInContext('authenticated=false',context);await vm.runInContext('appendReview(false)',context);
  assert.equal(calls.length,2);
});

test('review filtering retains the editor draft and its original optimistic revision',async()=>{
  const {context,elements}=harness(async()=>new Response(JSON.stringify({can_write:true,revision:8,trades:[],open_lots:[]})));
  vm.runInContext("authenticated=true;accessReady=true;accessMode='owner';capabilities={features:['private-state']};view='reviews';reviewsState={can_write:true,revision:3};reviewLotUid='11111111-1111-4111-8111-111111111111'",context);
  elements.set('reviewHypothesis',{value:'Unsubmitted private draft'});
  context.document.getElementById('contextPanel').innerHTML='Editor stays here';
  await vm.runInContext('renderReviews(true)',context);
  assert.equal(context.document.getElementById('reviewHypothesis').value,'Unsubmitted private draft');
  assert.equal(context.document.getElementById('contextPanel').innerHTML,'Editor stays here');
  assert.equal(vm.runInContext('reviewsState.revision',context),3);
});

test('settings preview keeps private TOML local and ambiguous apply retries retain identity',async()=>{
  const calls=[];
  const {context,elements}=harness(async(url,options={})=>{
    calls.push({url,body:options.body?JSON.parse(options.body):null});
    return new Response(JSON.stringify({error:'Synthetic failure'}),{status:500});
  });
  vm.runInContext("accessMode='owner';authenticated=true;accessReady=true;capabilities={features:['private-state','daemon-control']};settingsState={can_apply:true,revision:'0:synthetic'};settingsPreviewCandidate='[trader]\\\\ncapital=2000'",context);
  elements.set('settingsDocument',{value:'[trader]\\ncapital=2000'});
  elements.set('settingsBackup',{value:'/synthetic/before.zip'});
  elements.set('settingsRestore',{value:''});
  await vm.runInContext("settingsAction('apply')",context);
  await vm.runInContext("settingsAction('apply')",context);
  assert.equal(calls.length,2);
  assert.equal(calls[0].url,'/api/settings');
  assert.equal(calls[0].body.operation_id,calls[1].body.operation_id);
  assert.equal(calls[0].body.candidate,'[trader]\\ncapital=2000');
  vm.runInContext('authenticated=false',context);
  await vm.runInContext("settingsAction('apply')",context);
  assert.equal(calls.length,2);
});

test('equity metrics retain unknown marks and disclose whole-profile scope',()=>{
  const {context}=harness(async()=>new Response('{}'));
  const html=vm.runInContext("equityMetricsHtml({initialized:true,available_cash:636,reserved_cash:0,marked_equity:null,equity_return_pct:null})",context);
  assert.match(html,/Whole-profile/);
  assert.match(html,/independent of trade filters/);
  assert.match(html,/Unknown/);
  assert.match(html,/636 gp/);
  const table=vm.runInContext("historyTablesHtml({strategy_eras:[{config_id:null,trade_count:1,profit:-22}],equity_curve:[{date:'2026-10-12T10:00:00Z',marked_equity:null,equity:{mark_coverage:{missing_cost_basis:300}}}]})",context);
  assert.match(table,/Unknown legacy entry/);
  assert.match(table,/300 gp missing marks/);
  assert.match(table,/-22 gp/);
});

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
test('owner reconnect preserves an item bookmark',()=>{
  const {context}=harness(async()=>new Response('{}'));
  context.window.location.hash='#view=market&item=4151';
  vm.runInContext('applyViewUrl()',context);
  assert.equal(context.window.location.hash,'#view=market&item=4151');
});
test('keyboard controls retain native activation',()=>{
  const {context,listeners}=harness(async()=>new Response('{}'));
  vm.runInContext("view='watchlist';viewRows=[{id:4151}];selectedId=4151",context);
  let prevented=false,rendered=false;
  context.renderDetail=()=>{rendered=true;};
  for(const tag of ['button','input','select','textarea','a','summary']){
    listeners.get('keydown')({key:'Enter',target:{closest(selector){return selector.includes(tag)&&selector!=='dialog'&&selector!=='[role="tab"]'?{}:null;}},preventDefault(){prevented=true;}});
    assert.equal(prevented,false);assert.equal(rendered,false);
  }
});
test('URL state rejects private content and invalid values while preserving owner gates',()=>{
  const {context}=harness(async()=>new Response('{}'));
  context.renderMarket=()=>{};context.renderContextEmpty=()=>{};
  assert.equal(vm.runInContext("parseViewUrl('view=market&item=4151').item",context),4151);
  for(const query of ['view=unknown','view=market&item=-1','view=bank&token=secret','view=market&view=ge','item=9007199254740992']){
    assert.equal(vm.runInContext('parseViewUrl('+JSON.stringify(query)+').view',context),'market');
    assert.equal(vm.runInContext('parseViewUrl('+JSON.stringify(query)+').item',context),null);
  }
  context.window.location.hash='#view=bank';vm.runInContext('applyViewUrl()',context);
  assert.equal(vm.runInContext('view',context),'market');
  vm.runInContext("selectedId=4151;writeViewUrl()",context);
  assert.equal(context.window.location.hash,'#view=market&item=4151');
});
test('saved scan preferences are bounded and isolated by authenticated profile UUID',()=>{
  const {context}=ownerContext(async()=>new Response('{}'));
  context.renderMarket=()=>{};
  context.document.getElementById('scanPresetName').value='<Synthetic preset>';
  vm.runInContext("meta={profile_uuid:'11111111-1111-4111-8111-111111111111'};loadScanPreferences();chip='m10';saveScanPreset()",context);
  assert.equal(vm.runInContext('scanPresets.length',context),1);
  vm.runInContext("meta={profile_uuid:'22222222-2222-4222-8222-222222222222'};loadScanPreferences()",context);
  assert.equal(vm.runInContext('chip',context),'all');assert.equal(vm.runInContext('scanPresets.length',context),0);
  vm.runInContext("meta={profile_uuid:'11111111-1111-4111-8111-111111111111'};loadScanPreferences()",context);
  assert.equal(vm.runInContext('chip',context),'m10');
  assert.match(vm.runInContext('scanPresetControls()',context),/&lt;Synthetic preset&gt;/);
  assert.equal(vm.runInContext('validScanState({chip:"all",density:"normal",marketMode:"flips",sortKeys:[{col:"name",dir:"asc"}],note:"private"})',context),false);
  vm.runInContext('resetScanPreferences()',context);
  assert.equal(vm.runInContext('scanPresets.length',context),0);
});
test('oversized, corrupt and unsupported saved preferences fail closed',()=>{
  const {context}=ownerContext(async()=>new Response('{}'));
  vm.runInContext("meta={profile_uuid:'11111111-1111-4111-8111-111111111111'}",context);
  const state={chip:'m10',density:'dense',marketMode:'flips',sortKeys:[{col:'volume',dir:'desc'}]};
  const valid={version:1,active:state,presets:[]};
  const bad=[null,[],{...valid,version:2},{...valid,active:{...state,chip:'unknown'}},
    {...valid,presets:Array.from({length:11},(_,i)=>({name:'Preset '+i,state}))},
    {...valid,presets:[{name:'x'.repeat(41),state}]},
    {...valid,presets:[{name:'same',state},{name:'same',state}]},
    {...valid,active:{...state,sortKeys:[]}},
    {...valid,active:{...state,sortKeys:[{col:'note',dir:'desc'}]}}];
  for(const raw of [...bad.map(value=>JSON.stringify(value)),'broken',' '.repeat(16385)]){
    context.window.localStorage.setItem('rshelper.scan.v1.11111111-1111-4111-8111-111111111111',raw);
    vm.runInContext('loadedPreferenceKey=null;loadScanPreferences()',context);
    assert.equal(vm.runInContext('chip',context),'all');
    assert.equal(vm.runInContext('scanPresets.length',context),0);
  }
});
test('returning to market restores its selected item inspector',()=>{
  const {context}=ownerContext(async()=>new Response('{}'));
  context.renderMarket=()=>{};let inspected=null;
  context.renderDetail=id=>{inspected=id;};
  vm.runInContext("view='watchlist';selectedId=4151;setView('market')",context);
  assert.equal(inspected,4151);
});
test('selected tab and panel relationships agree, including Grand Exchange',()=>{
  const {context}=ownerContext(async()=>new Response('{}'));
  context.renderGE=()=>{};context.renderMarket=()=>{};
  vm.runInContext("setView('ge')",context);
  assert.equal(context.document.getElementById('btnGE').getAttribute('aria-selected'),'true');
  assert.equal(context.document.getElementById('btnMarket').getAttribute('aria-selected'),'false');
  assert.equal(context.document.getElementById('listBody').getAttribute('aria-labelledby'),'btnGE');
  vm.runInContext("setView('market')",context);
  assert.equal(context.document.getElementById('btnMarket').getAttribute('tabindex'),'0');
  assert.equal(context.document.getElementById('btnGE').getAttribute('tabindex'),'-1');
});
test('bank item is a native action and chart data preserve unknown and escaped values',()=>{
  const {context}=harness(async()=>new Response('{}'));
  const bank=vm.runInContext("bankSlotHtml({item_id:1,name:'<Synthetic>',total_qty:1})",context);
  assert.match(bank,/<button type="button"/);assert.match(bank,/aria-label="Inspect &lt;Synthetic&gt;"/);
  const table=vm.runInContext("chartDataHtml(['UTC','Value'],[['<date>',null],['later',0]])",context);
  assert.match(table,/&lt;date&gt;/);assert.match(table,/Unknown/);assert.match(table,/<td>0<\/td>/);
  assert.match(table,/scope="col"/);
});
test('fractional alert threshold is rejected without truncation or network writes',async()=>{
  let calls=0;const {context}=ownerContext(async()=>{calls++;return new Response('{}');});
  for(const [id,value] of Object.entries({wlBelow:'',wlMode:'crossing',wlCooldown:'900',wlHysteresis:'0'}))context.document.getElementById(id).value=value;
  for(const value of ['1.5','-1','not a number']){
    context.document.getElementById('wlAbove').value=value;
    await vm.runInContext('saveWatchAlerts(1)',context);
    assert.equal(calls,0);assert.equal(context.document.getElementById('wlAbove').value,value);
  }
  assert.match(context.document.getElementById('statusText').textContent,/whole/);
});
test('scan displays use authoritative direction metrics and offer a first-use path',()=>{
  const {context}=harness(async()=>new Response('{}'));
  assert.equal(vm.runInContext('marginPct({buy_price:100,sell_price:110,explanation:{margin_pct:37}})',context),37);
  assert.equal(vm.runInContext('roiPct({buy_price:100,profit:8,explanation:{roi_pct:29}})',context),29);
  const guidance=vm.runInContext('workflowHelpHtml()',context);
  for(const text of ['Scan','Watch','Paper','Review','standing orders','Wiki','shared budget','collection'])assert.ok(guidance.includes(text),text);
});
test('catalog inspector uses server economics and escapes mapped metadata',()=>{
  const {context}=harness(async()=>new Response('{}'));
  const html=vm.runInContext("catalogDetailHtml({id:9,name:'<Synthetic>',buy_limit:null,members:null,quote:{usable:true,buy_price:100,sell_price:110,tax:7,net_profit:999,margin_pct:10,roi_pct:999},market_data:{latest:{source:'wiki',delivery:'network'}},exclusion_reasons:['<Excluded>'],scan_eligible:false})",context);
  assert.match(html,/&lt;Synthetic&gt;/);assert.doesNotMatch(html,/<Synthetic>/);
  assert.match(html,/999 gp/);assert.match(html,/7 gp/);assert.match(html,/Membership unknown/);
  assert.match(html,/&lt;Excluded&gt;/);
  const explanation=vm.runInContext("catalogDetailHtml({id:9,name:'Synthetic',quote:{usable:true,buy_price:100,sell_price:110,tax:2,net_profit:8},scan_economics:{direction:'traditional',buy_leg_price:110,sell_leg_price:100,tax:2,net_profit:-12,gp_per_hour:-300,throughput_constraint:'<Buy limit>'}})",context);
  assert.match(explanation,/traditional/);assert.match(explanation,/net -12 gp/);
  assert.match(explanation,/-300 GP\/hr/);assert.match(explanation,/&lt;Buy limit&gt;/);
  assert.match(explanation,/not a promised return/);
  const missing=vm.runInContext("catalogDetailHtml({id:9,name:'<Synthetic>',quote:{usable:false,reason:'<No quote>'}})",context);
  assert.match(missing,/&lt;No quote&gt;/);assert.match(missing,/Watching remains available/);
  assert.doesNotMatch(missing,/Instant net profit/);
});

test('catalog detail responses cannot overwrite a newer selection',async()=>{
  const first=deferred();
  const {context,elements}=harness(async url=>url.endsWith('=1')?first.promise:
    new Response(JSON.stringify({id:2,name:'New selection',quote:{usable:false,reason:'no quote'}})));
  vm.runInContext("accessMode='public-demo';accessReady=true;capabilities={features:['market']}",context);
  const stale=vm.runInContext('selectedId=1;renderDetail(1)',context);
  await vm.runInContext('selectedId=2;renderDetail(2)',context);
  first.resolve(new Response(JSON.stringify({id:1,name:'Old selection',quote:{usable:false,reason:'no quote'}})));
  await stale;
  assert.match(elements.get('contextPanel').innerHTML,/New selection/);
  assert.doesNotMatch(elements.get('contextPanel').innerHTML,/Old selection/);
});

test('catalog search caps requests and fences results after navigation',async()=>{
  const pending=deferred();let url;
  const {context,elements}=harness(async request=>{url=request;return pending.promise;});
  vm.runInContext("accessMode='public-demo';accessReady=true;capabilities={features:['market']}",context);
  vm.runInContext('showCatalogSearch()',context);elements.get('catalogQuery').value='Rune & sword';
  const request=vm.runInContext('searchCatalog()',context);
  vm.runInContext('viewEpoch++',context);
  pending.resolve(new Response(JSON.stringify({items:[{id:1,name:'<Stale>'}]})));await request;
  assert.equal(url,'/api/catalog?q=Rune%20%26%20sword&limit=50');
  assert.equal(elements.get('catalogResults').textContent,'Searching catalog...');
  assert.doesNotMatch(elements.get('catalogResults').innerHTML,/<Stale>/);
});

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
