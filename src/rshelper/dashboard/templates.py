"""Dashboard HTML template — Command Center layout."""

# ponytail: inline template, no Jinja/Django. Add template engine when >=3 templates exist.

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RSHelper Dashboard</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0e17;--surface:#111827;--surface2:#1a2332;--surface3:#223047;
  --gold:#c9a84c;--gold-dim:#8b7233;
  --pos:#22c55e;--pos-hot:#4ade80;--neg:#f87171;--warn:#eab308;
  --blue:#60a5fa;--star:#facc15;
  --text:#e2e8f0;--text-dim:#94a3b8;--border:#1e293b;
  --radius:6px;--font:system-ui,-apple-system,sans-serif;
}
html{color-scheme:dark}
body{background:var(--bg);color:var(--text);font-family:var(--font);height:100vh;display:flex;flex-direction:column;overflow:hidden}
button{font-family:var(--font)}
.topbar{
  display:flex;align-items:center;gap:16px;padding:12px 20px;
  background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0;
}
.topbar h1{font-size:18px;font-weight:700;color:var(--gold);white-space:nowrap}
.topbar h1::before{content:'';display:inline-block;width:18px;height:18px;background:var(--gold);border-radius:50%;margin-right:8px;vertical-align:-3px}
.topbar .search{flex:1;max-width:380px}
.topbar .search input{
  width:100%;padding:7px 12px;background:var(--bg);border:1px solid var(--border);
  border-radius:var(--radius);color:var(--text);font-size:13px;outline:none
}
.topbar .search input:focus{border-color:var(--gold-dim)}
.stats{display:flex;align-items:center;gap:14px;margin-left:auto}
.stat{text-align:center}
.stat .val{font-size:18px;font-weight:700;font-variant-numeric:tabular-nums}
.stat .lbl{font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px}
.stat .val.green{color:var(--pos)}.stat .val.gold{color:var(--gold)}.stat .val.dim{color:var(--text-dim)}
.icon-btn{
  width:30px;height:30px;display:inline-flex;align-items:center;justify-content:center;
  background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);
  color:var(--text-dim);font-size:15px;cursor:pointer
}
.icon-btn:hover{color:var(--gold);border-color:var(--gold-dim)}
.navrow{
  display:flex;align-items:center;gap:6px;padding:8px 20px;
  background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0
}
.nav-btn{
  display:inline-flex;align-items:center;gap:6px;padding:6px 12px;
  background:transparent;border:1px solid transparent;border-radius:var(--radius);
  color:var(--text-dim);font-size:13px;font-weight:600;cursor:pointer
}
.nav-btn:hover{color:var(--text);background:var(--surface2)}
.nav-btn.active{background:var(--surface2);border-color:var(--gold);color:var(--gold)}
.nav-btn .badge{
  min-width:18px;padding:1px 5px;border-radius:9px;background:var(--surface3);
  color:var(--text-dim);font-size:10px;font-weight:700;text-align:center
}
.nav-btn.active .badge{background:var(--gold-dim);color:#0a0e17}
.main{display:flex;flex:1;overflow:hidden}
.list-panel{flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden}
.viewbar{
  display:flex;align-items:center;gap:8px;padding:8px 20px 0;flex-shrink:0
}
.viewbar .title{font-size:12px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-right:auto}
.chip,.toggle-btn{
  padding:4px 10px;background:var(--surface);border:1px solid var(--border);
  border-radius:12px;color:var(--text-dim);font-size:12px;cursor:pointer
}
.chip.active,.toggle-btn.active{background:var(--surface2);border-color:var(--gold);color:var(--gold)}
.viewbar input,.viewbar select{
  padding:4px 8px;background:var(--bg);border:1px solid var(--border);
  border-radius:var(--radius);color:var(--text);font-size:12px;outline:none
}
.viewbar input:focus,.viewbar select:focus{border-color:var(--gold-dim)}
.viewbar .act-btn{
  padding:4px 12px;background:var(--gold-dim);border:1px solid var(--gold);
  border-radius:var(--radius);color:#0a0e17;font-size:12px;font-weight:700;cursor:pointer
}
.viewbar .act-btn:hover{background:var(--gold)}
.list-body{flex:1;overflow-y:auto;padding:8px 20px 20px}
.list-body table{width:100%;border-collapse:separate;border-spacing:0;font-size:13px}
.list-body th{
  position:sticky;top:0;background:var(--bg);padding:9px 8px;
  text-align:right;font-weight:600;color:var(--text-dim);font-size:11px;
  text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border);z-index:1
}
.list-body th:first-child,.list-body td:first-child{text-align:left;padding-left:4px}
.th-sort{cursor:pointer;user-select:none}
.th-sort:hover{color:var(--gold)}
.th-sort .srt{display:inline-block;width:12px;color:var(--gold);font-size:10px}
.list-body td{padding:7px 8px;text-align:right;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums;white-space:nowrap}
.list-body tr{cursor:pointer;transition:background .08s}
.list-body tr:hover{background:var(--surface2)}
.list-body tr.selected{background:var(--surface2);outline:1px solid var(--gold-dim)}
.list-body .name{text-align:left;font-weight:500;max-width:260px;overflow:hidden;text-overflow:ellipsis}
.list-body .margin{font-weight:600}
.pos{color:var(--pos)}.pos-hot{color:var(--pos-hot)}.neg{color:var(--neg)}.neutral{color:var(--warn)}.dim{color:var(--text-dim)}
.list-body.dense td{padding:3px 8px;font-size:12.5px}
.list-body.dense th{padding:6px 8px}
.star{background:none;border:none;color:var(--text-dim);font-size:15px;cursor:pointer;padding:2px 4px;line-height:1}
.star:hover{color:var(--text)}
.star.on{color:var(--star)}
.sig-badge{display:inline-block;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.4px}
.sig-CRASH{background:rgba(248,113,113,.15);color:var(--neg);border:1px solid rgba(248,113,113,.35)}
.sig-DUMP{background:rgba(234,179,8,.12);color:var(--warn);border:1px solid rgba(234,179,8,.35)}
.sig-SURGE{background:rgba(96,165,250,.12);color:var(--blue);border:1px solid rgba(96,165,250,.35)}
.sig-FLIP{background:rgba(201,168,76,.12);color:var(--gold);border:1px solid rgba(201,168,76,.35)}
.sev-HIGH{color:var(--neg);font-weight:700}.sev-MEDIUM{color:var(--warn)}.sev-LOW{color:var(--text-dim)}
.context-panel{
  width:360px;flex-shrink:0;background:var(--surface);
  border-left:1px solid var(--border);padding:20px;overflow-y:auto;
  display:flex;flex-direction:column;gap:16px;
}
.context-panel .empty{color:var(--text-dim);text-align:center;margin-top:80px;font-size:14px}
.context-panel .item-name{font-size:20px;font-weight:700;color:var(--gold);display:flex;align-items:center;gap:10px;justify-content:space-between}
.context-panel .item-name .star{font-size:20px}
.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.metric{background:var(--bg);border-radius:var(--radius);padding:12px}
.metric .val{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums;word-break:break-word}
.metric .lbl{font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}
.metric .val.green{color:var(--pos)}.metric .val.red{color:var(--neg)}.metric .val.gold{color:var(--gold)}
.notice{
  padding:9px 11px;border-radius:var(--radius);font-size:12px;line-height:1.45;
  background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.3);color:var(--warn)
}
.notice.warn-red{background:rgba(248,113,113,.08);border-color:rgba(248,113,113,.35);color:var(--neg)}
#spark{width:100%;height:84px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);display:block}
.footer{
  display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:6px 20px;background:var(--surface);border-top:1px solid var(--border);
  font-size:11px;color:var(--text-dim);flex-shrink:0
}
.footer .dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:4px;vertical-align:middle}
.footer .dot.live{background:var(--pos)}.footer .dot.err{background:var(--neg)}
.source-badge{
  margin-left:10px;padding:1px 8px;border-radius:9px;font-size:10px;font-weight:700;
  background:var(--surface3);color:var(--text-dim);text-transform:uppercase;letter-spacing:.4px
}
.source-badge.wiki{color:var(--pos)}.source-badge.tracker{color:var(--gold)}.source-badge.none{color:var(--neg)}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:spin .6s linear infinite;vertical-align:-3px}
@keyframes spin{to{transform:rotate(360deg)}}
.loading{display:flex;align-items:center;gap:8px;padding:36px;color:var(--text-dim);justify-content:center}
.chart-title{font-size:13px;font-weight:700;color:var(--gold);margin:20px 0 8px}
.chart-title:first-child{margin-top:8px}
.list-body canvas{width:100%;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)}
.kbd{display:inline-block;padding:1px 5px;border:1px solid var(--border);border-bottom-width:2px;border-radius:4px;font-size:10px;color:var(--text-dim)}
:focus-visible{outline:2px solid var(--gold);outline-offset:-2px}
button:focus-visible{border-color:var(--gold)}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:var(--surface3);border-radius:5px}
::-webkit-scrollbar-track{background:transparent}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
.ge-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:3px;padding:12px;
  background:#3b3023;border:2px solid #5c4a32;border-radius:4px;
  background-image:linear-gradient(135deg,rgba(92,74,50,.08) 25%,transparent 25%),
    linear-gradient(225deg,rgba(92,74,50,.08) 25%,transparent 25%);
  background-size:8px 8px}
.ge-slot{background:#2a2215;border:1px solid #5c4a32;border-radius:3px;padding:8px;
  min-height:120px;display:flex;flex-direction:column;position:relative;
  cursor:pointer;transition:all .15s ease}
.ge-slot:hover{border-color:var(--gold);box-shadow:0 0 8px rgba(201,168,76,.3)}
.ge-slot.empty{opacity:.6;cursor:default;justify-content:center;align-items:center}
.ge-slot.empty:hover{border-color:#5c4a32;box-shadow:none}
.ge-offer-type{font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.5px;margin-bottom:4px}
.ge-offer-type.buy{color:#7cc950}.ge-offer-type.sell{color:#e8a230}
.ge-slot-icon{width:40px;height:40px;image-rendering:pixelated;margin:4px auto;
  object-fit:contain}
.ge-slot-name{font-size:11px;color:var(--text);text-align:center;margin:2px 0;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ge-fill-track{width:100%;height:12px;background:#1a1208;border:1px solid #5c4a32;
  border-radius:2px;overflow:hidden;margin:4px 0}
.ge-fill-bar{height:100%;border-radius:2px;transition:width .5s ease-out}
.ge-fill-bar.buy{background:linear-gradient(180deg,#4ade80,#16a34a)}
.ge-fill-bar.sell{background:linear-gradient(180deg,#fbbf24,#d97706)}
.ge-fill-bar.filled{animation:ge-pulse 1.5s ease-in-out infinite}
@keyframes ge-pulse{0%,100%{opacity:1}50%{opacity:.7}}
.ge-slot-price{font-size:11px;color:var(--text-dim);text-align:center;
  font-variant-numeric:tabular-nums}
.ge-collect-btn{margin-top:auto;padding:4px 8px;background:var(--gold-dim);
  border:1px solid var(--gold);border-radius:3px;color:#0a0e17;font-size:10px;
  font-weight:700;cursor:pointer;transition:all .2s ease;text-align:center;
  opacity:0;transform:scale(.9)}
.ge-collect-btn.visible{opacity:1;transform:scale(1)}
.ge-collect-btn:hover{background:var(--gold)}
.ge-history-overlay{position:fixed;top:0;left:0;right:0;bottom:0;
  background:rgba(0,0,0,.7);z-index:100;display:flex;justify-content:center;
  align-items:center}
.ge-history-panel{background:#2a2215;border:2px solid #5c4a32;border-radius:6px;
  width:600px;max-height:80vh;overflow-y:auto;padding:16px}
.ge-history-panel table{width:100%;border-collapse:collapse;font-size:12px}
.ge-history-panel th{color:var(--text-dim);text-align:right;padding:5px 6px;
  font-size:10px;text-transform:uppercase;letter-spacing:.5px;
  border-bottom:1px solid #5c4a32}
.ge-history-panel th:first-child,.ge-history-panel td:first-child{text-align:left}
.ge-history-panel td{padding:5px 6px;text-align:right;color:var(--text);
  font-variant-numeric:tabular-nums;border-bottom:1px solid #3d3525}
.ge-history-panel .act-btn{padding:5px 12px;background:var(--gold-dim);
  border:1px solid var(--gold);border-radius:var(--radius);color:#0a0e17;
  font-size:12px;font-weight:700;cursor:pointer}
.ge-history-panel .act-btn:hover{background:var(--gold)}
.bank-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(70px,1fr));
  gap:2px;padding:12px;background:#3b3023;border:2px solid #5c4a32;
  border-radius:4px}
.bank-slot{background:#2a2215;border:1px solid #3d3525;border-radius:2px;padding:4px;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  min-height:72px;position:relative;cursor:pointer;transition:all .15s ease}
.bank-slot:hover{border-color:var(--gold);transform:scale(1.05);z-index:1;
  box-shadow:0 2px 8px rgba(0,0,0,.4)}
.bank-slot-icon{width:40px;height:40px;image-rendering:pixelated;object-fit:contain}
.bank-slot-qty{position:absolute;top:2px;right:4px;font-size:11px;font-weight:700;
  color:var(--gold);text-shadow:1px 1px 0 #000;font-variant-numeric:tabular-nums}
.bank-tooltip{position:absolute;bottom:calc(100% + 8px);left:50%;
  transform:translateX(-50%);background:#1a1208;border:1px solid #5c4a32;
  border-radius:4px;padding:8px 10px;font-size:11px;white-space:nowrap;z-index:10;
  pointer-events:none;opacity:0;transition:opacity .15s ease}
.bank-slot:hover .bank-tooltip{opacity:1}
.bank-footer{display:flex;justify-content:space-between;padding:8px 12px;
  background:var(--surface);border-top:1px solid var(--border);font-size:12px;
  color:var(--text-dim)}
.gold{color:var(--gold)}
</style>
</head>
<body>
<div class="topbar">
  <h1>RSHelper</h1>
  <div class="search"><input type="text" id="search" placeholder="Filter current list..." oninput="applySearch()" aria-label="Filter items"></div>
  <div class="stats">
    <div class="stat"><div class="val dim" id="statCount">-</div><div class="lbl">Flips</div></div>
    <div class="stat"><div class="val green" id="statBest">-</div><div class="lbl">Best Margin</div></div>
    <div class="stat"><div class="val gold" id="statRefresh">-</div><div class="lbl">Refresh</div></div>
    <button class="icon-btn" id="btnRefresh" onclick="fetchData()" aria-label="Refresh now" title="Refresh now">&#x21bb;</button>
  </div>
</div>
<div class="navrow" role="tablist" aria-label="Views">
  <button class="nav-btn active" id="btnMarket" role="tab" onclick="setView('market')">Market <span class="badge" id="badgeMarket">-</span></button>
  <button class="nav-btn" id="btnPaper" role="tab" onclick="setView('paper')">Paper Trading <span class="badge" id="badgePaper">-</span></button>
  <button class="nav-btn" id="btnSignals" role="tab" onclick="setView('signals')">Signals <span class="badge" id="badgeSignals">-</span></button>
  <button class="nav-btn" id="btnWatchlist" role="tab" onclick="setView('watchlist')">Watchlist <span class="badge" id="badgeWatchlist">-</span></button>
  <button class="nav-btn" id="btnGE" role="tab" onclick="setView('ge')">Grand Exchange <span class="badge" id="badgeGE">-</span></button>
  <button class="nav-btn" id="btnBank" role="tab" onclick="setView('bank')">Bank <span class="badge" id="badgeBank">-</span></button>
  <button class="nav-btn" id="btnProcess" role="tab" onclick="setView('process')">Materials <span class="badge" id="badgeProcess">-</span></button>
</div>
<div class="main">
  <div class="list-panel">
    <div class="viewbar" id="viewbar"></div>
    <div class="list-body" id="listBody" tabindex="0" aria-label="Items list">
      <div class="loading"><span class="spinner"></span>Loading market data...</div>
    </div>
  </div>
  <div class="context-panel" id="contextPanel">
    <div class="empty">&#8592; Select an item to inspect</div>
  </div>
</div>
<div class="footer">
  <span><span class="dot" id="statusDot"></span><span id="statusText">Connected</span><span class="source-badge none" id="sourceBadge">-</span></span>
  <span><span class="kbd" id="kbdHint">&#8593;&#8595; move</span> <span id="lastUpdated">Last updated: --</span></span>
</div>
<script>
const refreshSecs=60;
let allItems=[],signalsMap={},meta={},watchIds=new Set();
let selectedId=null,view='market';
let sortKeys=[{col:'gp_per_hour',dir:'desc'}];
let chip='all',density='normal',strategy='';
let viewRows=[];
let geData=null,bankData=null;
let sparkSeq=0;
let countdown=refreshSecs;

function marginPct(item){
  if(!item||item.buy_price<=0)return 0;
  return ((item.sell_price-item.buy_price)/item.buy_price*100);
}
function roiPct(item){
  if(!item||item.buy_price<=0)return 0;
  return ((item.profit||0)/item.buy_price*100);
}
function taxOf(sell){return Math.min(5000000,Math.floor((sell||0)*0.02))}
function format(n){return (n||0).toLocaleString()}
function gp(n){
  n=n||0;
  if(Math.abs(n)>=1e9)return (n/1e9).toFixed(2).replace(/\.?0+$/,'')+'B';
  if(Math.abs(n)>=1e6)return (n/1e6).toFixed(2).replace(/\.?0+$/,'')+'M';
  if(Math.abs(n)>=1e3)return (n/1e3).toFixed(1).replace(/\.?0$/,'')+'K';
  return String(n);
}
function marginClass(v){
  if(v>=10)return 'pos-hot';
  if(v>=2)return 'pos';
  if(v<=-2)return 'neg';
  if(v>0)return 'neutral';
  return 'dim';
}
function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function metric(label,val,valClass){
  const vc=valClass?' '+valClass:'';
  return '<div class="metric"><div class="lbl">'+label+'</div><div class="val'+vc+'">'+val+'</div></div>';
}

function valueOf(item,col){
  if(col==='margin')return marginPct(item);
  if(col==='roi')return roiPct(item);
  return item[col]||0;
}
function marketRows(){
  const q=(document.getElementById('search').value||'').toLowerCase();
  let list=q?allItems.filter(i=>i.name.toLowerCase().includes(q)):[...allItems];
  if(chip==='m2')list=list.filter(i=>marginPct(i)>=2);
  else if(chip==='m10')list=list.filter(i=>marginPct(i)>=10);
  else if(chip==='v100')list=list.filter(i=>i.volume>=100);
  list.sort((a,b)=>{
    for(const k of sortKeys){
      const va=valueOf(a,k.col),vb=valueOf(b,k.col);
      let cmp;
      if(k.col==='name')cmp=String(a.name).localeCompare(String(b.name));
      else cmp=(va>vb?1:va<vb?-1:0);
      if(cmp!==0)return k.dir==='desc'?-cmp:cmp;
    }
    return 0;
  });
  return list;
}
function sortBy(col,ev){
  if(ev&&ev.shiftKey){
    const i=sortKeys.findIndex(k=>k.col===col);
    if(i>=0)sortKeys.splice(i,1);
    if(sortKeys.length<2)sortKeys.push({col,dir:'desc'});
  }else{
    if(sortKeys.length===1&&sortKeys[0].col===col){
      sortKeys[0].dir=sortKeys[0].dir==='desc'?'asc':'desc';
    }else{
      sortKeys=[{col,dir:'desc'}];
    }
  }
  renderMarket();
}

function setView(v){
  view=v;
  document.getElementById('btnMarket').classList.toggle('active',v==='market');
  document.getElementById('btnPaper').classList.toggle('active',v==='paper');
  document.getElementById('btnSignals').classList.toggle('active',v==='signals');
  document.getElementById('btnWatchlist').classList.toggle('active',v==='watchlist');
  document.getElementById('btnGE').classList.toggle('active',v==='ge');
  document.getElementById('btnBank').classList.toggle('active',v==='bank');
  document.getElementById('btnProcess').classList.toggle('active',v==='process');
  if(v==='market')renderMarket();
  else if(v==='paper')renderPaper();
  else if(v==='signals')renderSignals();
  else if(v==='watchlist')renderWatchlist();
  else if(v==='ge')renderGE();
  else if(v==='bank')renderBank();
  else if(v==='process')renderProcess();
  if(v==='market'&&selectedId==null)renderContextEmpty();
}
function applySearch(){if(view==='market')renderMarket();else if(view==='signals')renderSignals();else if(view==='watchlist')renderWatchlist()}

function setChip(c){
  chip=c;
  document.querySelectorAll('.chip').forEach(b=>b.classList.toggle('active',b.dataset.chip===c));
  renderMarket();
}
function setDensity(){
  density=density==='normal'?'dense':'normal';
  document.getElementById('listBody').classList.toggle('dense',density==='dense');
  document.getElementById('btnDensity').classList.toggle('active',density==='dense');
}
function setStrategy(v){
  strategy=v;
  document.querySelectorAll('[data-strategy]').forEach(b=>b.classList.toggle('active',b.dataset.strategy===strategy));
  renderPaper();
}

async function paperTrade(){
  const item=document.getElementById('ptItem').value.trim();
  const qty=parseInt(document.getElementById('ptQty').value,10);
  const action=document.getElementById('ptAction').value;
  if(!item||!qty||qty<=0){
    document.getElementById('statusText').textContent='Enter an item and a positive quantity';
    document.getElementById('statusDot').className='dot err';
    return;
  }
  try{
    const r=await fetch('/api/paper',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action,item,qty})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.message||('HTTP '+r.status));
    document.getElementById('statusText').textContent=action==='open'?'Position opened':'Paper trade logged';
    document.getElementById('statusDot').className='dot live';
    fetchData();
  }catch(e){
    document.getElementById('statusText').textContent='Error: '+e.message;
    document.getElementById('statusDot').className='dot err';
  }
}

async function fetchData(){
  document.getElementById('statusText').textContent='Fetching...';
  document.getElementById('statusDot').className='dot';
  try{
    const [r,m,s]=await Promise.all([fetch('/api/scan'),fetch('/api/meta'),fetch('/api/signals')]);
    if(!r.ok||!m.ok||!s.ok)throw new Error('api error');
    allItems=(await r.json()).items||[];
    meta=await m.json();
    signalsMap={};
    (await s.json()).signals.forEach(x=>{signalsMap[x.item_id]=x});
    watchIds=new Set(meta.watch_ids||[]);
    document.getElementById('statusText').textContent='Connected';
    document.getElementById('statusDot').className='dot live';
    updateTop();
    updateBadges();
    updateFooter();
    if(view==='market')renderMarket();
    else if(view==='paper')renderPaper();
    else if(view==='signals')renderSignals();
    else if(view==='watchlist')renderWatchlist();
    else if(view==='ge')renderGE();
    else if(view==='bank')renderBank();
    else if(view==='process')renderProcess();
    if(view==='market'&&selectedId!=null)renderDetail(selectedId);
    countdown=refreshSecs;
  }catch(e){
    document.getElementById('statusText').textContent='Error: '+e.message;
    document.getElementById('statusDot').className='dot err';
  }
}
function updateTop(){
  document.getElementById('statCount').textContent=allItems.length;
  let best=0;
  allItems.forEach(i=>{const m=marginPct(i);if(m>best)best=m});
  document.getElementById('statBest').textContent=best>0?best.toFixed(1)+'%':'-';
}
function updateBadges(){
  document.getElementById('badgeMarket').textContent=meta.flips||0;
  document.getElementById('badgePaper').textContent=meta.trades||0;
  document.getElementById('badgeSignals').textContent=meta.signals||0;
  document.getElementById('badgeWatchlist').textContent=meta.watchlist||0;
}
function updateFooter(){
  const src=meta.source||'none';
  const el=document.getElementById('sourceBadge');
  el.textContent=src==='ge_tracker'?'GE Tracker fallback':src==='wiki'?'OSRS Wiki':'-';
  el.className='source-badge '+(src==='wiki'?'wiki':src==='ge_tracker'?'tracker':'none');
  if(meta.last_fetch){
    document.getElementById('lastUpdated').textContent='Last updated: '+new Date(meta.last_fetch*1000).toLocaleTimeString();
  }
  if(src==='ge_tracker'){
    document.getElementById('kbdHint').textContent='signals limited on fallback';
  }else{
    document.getElementById('kbdHint').innerHTML='&#8593;&#8595; move';
  }
}

function starHtml(id){
  return '<button class="star '+(watchIds.has(id)?'on':'')+'" onclick="starItem('+id+',event)" aria-label="Toggle watchlist" title="'+(watchIds.has(id)?'Unwatch':'Watch')+'">'+(watchIds.has(id)?'&#9733;':'&#9734;')+'</button>';
}
async function starItem(id,ev){
  if(ev)ev.stopPropagation();
  const action=watchIds.has(id)?'remove':'add';
  try{
    const r=await fetch('/api/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,item_id:id})});
    if(!r.ok)throw new Error('watchlist update failed');
    const d=await r.json();
    watchIds=new Set(d.items.map(i=>i.id));
    meta.watchlist=d.items.length;
    updateBadges();
    if(view==='market')renderMarket();
    else if(view==='watchlist')renderWatchlist();
    if(selectedId===id)renderDetail(id);
  }catch(e){
    document.getElementById('statusText').textContent='Error: '+e.message;
    document.getElementById('statusDot').className='dot err';
  }
}

function sigBadge(item){
  const s=signalsMap[item.id];
  if(!s)return '<span class="dim">-</span>';
  return '<span class="sig-badge sig-'+escHtml(s.type)+'" title="'+escHtml(s.message)+'">'+escHtml(s.type)+'</span>';
}

function viewbarHtml(){
  if(view==='market'){
    return '<div class="viewbar"><span class="title">Market scan</span>'+
      '<button class="chip'+(chip==='all'?' active':'')+'" data-chip="all" onclick="setChip(\'all\')">All</button>'+
      '<button class="chip'+(chip==='m2'?' active':'')+'" data-chip="m2" onclick="setChip(\'m2\')">Margin &ge;2%</button>'+
      '<button class="chip'+(chip==='m10'?' active':'')+'" data-chip="m10" onclick="setChip(\'m10\')">Margin &ge;10%</button>'+
      '<button class="chip'+(chip==='v100'?' active':'')+'" data-chip="v100" onclick="setChip(\'v100\')">Vol &ge;100</button>'+
      '<button class="toggle-btn" id="btnDensity" onclick="setDensity()">Compact</button></div>';
  }
  if(view==='paper'){
    return '<div class="viewbar"><span class="title">Paper trading</span>'+
      '<button class="toggle-btn'+(strategy===''?' active':'')+'" data-strategy="" onclick="setStrategy(\'\')">All trades</button>'+
      '<button class="toggle-btn'+(strategy==='auto'?' active':'')+'" data-strategy="auto" onclick="setStrategy(\'auto\')">Auto-trader</button>'+
      '<button class="toggle-btn'+(strategy==='manual'?' active':'')+'" data-strategy="manual" onclick="setStrategy(\'manual\')">Manual</button>'+
      '<input id="ptItem" list="ptItems" placeholder="Item name" aria-label="Item name" style="width:150px">'+
      '<datalist id="ptItems">'+allItems.map(i=>'<option value="'+escHtml(i.name)+'">').join('')+'</datalist>'+
      '<input id="ptQty" type="number" min="1" placeholder="Qty" aria-label="Quantity" style="width:64px">'+
      '<select id="ptAction" aria-label="Trade action"><option value="open">Open position</option><option value="instant">Instant trade</option></select>'+
      '<button class="act-btn" onclick="paperTrade()">Trade</button></div>';
  }
  if(view==='ge'){
    return '<div class="viewbar"><span class="title">Grand Exchange</span>'+
      '<button class="toggle-btn" onclick="showGEHistory()">History</button></div>';
  }
  if(view==='bank'){
    return '<div class="viewbar"><span class="title">Bank of RuneScape</span></div>';
  }
  if(view==='process'){
    return '<div class="viewbar"><span class="title">Materials Processing</span>'+
      '<select id="processSkill" aria-label="Skill filter" onchange="renderProcess()" style="margin-left:8px">'+
      '<option value="">All skills</option>'+
      '<option value="smithing">Smithing</option>'+
      '<option value="fletching">Fletching</option>'+
      '<option value="crafting">Crafting</option>'+
      '<option value="cooking">Cooking</option>'+
      '<option value="herblore">Herblore</option>'+
      '<option value="construction">Construction</option>'+
      '<option value="runecrafting">Runecrafting</option>'+
      '<option value="magic">Magic</option>'+
      '</select></div>';
  }
  return '<div class="viewbar"><span class="title">'+view.charAt(0).toUpperCase()+view.slice(1)+'</span></div>';
}

function selectId(id,scroll){
  selectedId=id;
  if(view==='market')renderMarket();
  else if(view==='watchlist'||view==='signals'){
    document.querySelectorAll('tr.selected').forEach(r=>r.classList.remove('selected'));
    const row=document.querySelector('tr[data-id="'+id+'"]');
    if(row)row.classList.add('selected');
  }
  renderDetail(id);
  if(scroll){
    const row=document.querySelector('tr[data-id="'+id+'"]');
    if(row)row.scrollIntoView({block:'nearest'});
  }
}

document.addEventListener('keydown',e=>{
  if(view!=='market'&&view!=='watchlist'&&view!=='signals')return;
  if(!viewRows.length)return;
  let idx=viewRows.findIndex(r=>r.id===selectedId);
  if(e.key==='ArrowDown'){e.preventDefault();idx=Math.min(viewRows.length-1,Math.max(0,idx+1));selectId(viewRows[idx].id,true)}
  else if(e.key==='ArrowUp'){e.preventDefault();idx=Math.max(0,idx-1);selectId(viewRows[idx].id,true)}
  else if(e.key==='Enter'&&selectedId!=null){e.preventDefault();renderDetail(selectedId)}
  else if(e.key==='Escape'){selectedId=null;if(view==='market')renderMarket();else if(view==='watchlist')renderWatchlist();renderContextEmpty()}
});

function renderMarket(){
  const bar=document.getElementById('viewbar');
  bar.innerHTML=viewbarHtml();
  if(density==='dense')document.getElementById('listBody').classList.add('dense');
  const rows=marketRows();
  viewRows=rows;
  const body=document.getElementById('listBody');
  if(!rows.length){
    body.innerHTML='<div class="loading">No items match the current filters</div>';
    return;
  }
  let h='<table><thead><tr>';
  const cols=[['name','Item'],['buy_price','Buy'],['sell_price','Sell'],['margin','Margin'],['roi','ROI'],['gp_per_hour','GP/hr'],['volume','Vol'],['sig','Signal'],['star','']];
  cols.forEach(c=>{
    const isSort=c[1]!==''&&c[0]!=='sig'&&c[0]!=='star';
    let arrow='';
    if(isSort){
      const i=sortKeys.findIndex(k=>k.col===c[0]);
      if(i===0)arrow=sortKeys[0].dir==='desc'?'&#9660;':'&#9650;';
      else if(i===1)arrow='&#9679;';
    }
    h+='<th'+(isSort?' class="th-sort" onclick="sortBy(\''+c[0]+'\',event)"':'')+'>'+
      (c[1]?c[1]+' <span class="srt">'+arrow+'</span>':'')+'</th>';
  });
  h+='</tr></thead><tbody>';
  rows.forEach((item,i)=>{
    const mp=marginPct(item),rp=roiPct(item);
    const cls=marginClass(mp);
    const sel=item.id===selectedId?' selected':'';
    h+='<tr class="'+sel+'" data-id="'+item.id+'" onclick="selectId('+item.id+',false)">'+
      '<td class="name" title="'+escHtml(item.name)+'">'+escHtml(item.name)+'</td>'+
      '<td>'+gp(item.buy_price)+'</td><td>'+gp(item.sell_price)+'</td>'+
      '<td class="margin '+cls+'">'+mp.toFixed(1)+'%</td>'+
      '<td class="'+marginClass(rp)+'">'+rp.toFixed(1)+'%</td>'+
      '<td>'+gp(item.gp_per_hour)+'</td>'+
      '<td>'+gp(item.volume)+'</td>'+
      '<td>'+sigBadge(item)+'</td>'+
      '<td>'+starHtml(item.id)+'</td></tr>';
  });
  h+='</tbody></table>';
  body.innerHTML=h;
}

async function renderSignals(){
  const bar=document.getElementById('viewbar');
  bar.innerHTML=viewbarHtml();
  const body=document.getElementById('listBody');
  viewRows=[];
  const q=(document.getElementById('search').value||'').toLowerCase();
  let signals=Object.values(signalsMap);
  if(q)signals=signals.filter(s=>s.name.toLowerCase().includes(q));
  const order={HIGH:0,MEDIUM:1,LOW:2};
  signals.sort((a,b)=>(order[a.severity]||3)-(order[b.severity]||3)||String(a.type).localeCompare(String(b.type)));
  viewRows=signals.map(s=>({id:s.item_id,name:s.name}));
  if(!signals.length){
    const note=meta.source==='ge_tracker'
      ?'No active signals. The GE Tracker fallback carries only offer quantities, so signals are disabled by design on this source.'
      :'No active signals — the market is calm right now.';
    body.innerHTML='<div class="loading">'+note+'</div>';
    renderContextEmpty();
    return;
  }
  let h='<table><thead><tr><th class="th-sort">Type</th><th>Sev</th><th>Item</th><th>Price</th><th>Deviation</th><th class="name">Message</th></tr></thead><tbody>';
  signals.forEach(s=>{
    const sel=s.item_id===selectedId?' selected':'';
    const dev=Number(s.deviation)||0;
    const devTxt=s.type==='SURGE'?dev+'x':(dev>0?'+':'')+dev+'%';
    h+='<tr class="'+sel+'" data-id="'+s.item_id+'" onclick="selectId('+s.item_id+',false)">'+
      '<td><span class="sig-badge sig-'+escHtml(s.type)+'">'+escHtml(s.type)+'</span></td>'+
      '<td class="sev-'+escHtml(s.severity)+'">'+escHtml(s.severity)+'</td>'+
      '<td class="name">'+escHtml(s.name)+'</td>'+
      '<td>'+format(s.current_price)+'</td>'+
      '<td class="'+(dev>0?'pos':'neg')+'">'+devTxt+'</td>'+
      '<td class="name">'+escHtml(s.message)+'</td></tr>';
  });
  h+='</tbody></table>';
  body.innerHTML=h;
  if(selectedId!=null)renderDetail(selectedId);
  else renderContextEmpty();
}

async function renderWatchlist(){
  const bar=document.getElementById('viewbar');
  bar.innerHTML=viewbarHtml();
  const body=document.getElementById('listBody');
  viewRows=[];
  let items;
  try{
    const r=await fetch('/api/watchlist');
    items=(await r.json()).items||[];
  }catch(e){
    body.innerHTML='<div class="loading">Error loading watchlist: '+escHtml(e.message)+'</div>';
    return;
  }
  watchIds=new Set(items.map(i=>i.id));
  const q=(document.getElementById('search').value||'').toLowerCase();
  const shown=q?items.filter(i=>i.name.toLowerCase().includes(q)):items;
  viewRows=shown;
  if(!items.length){
    body.innerHTML='<div class="loading">No watched items — click the &#9734; star on any Market row to track it.</div>';
    renderContextEmpty();
    return;
  }
  if(!shown.length){
    body.innerHTML='<div class="loading">No watched items match the filter.</div>';
    if(selectedId!=null)renderDetail(selectedId);
    else renderContextEmpty();
    return;
  }
  let h='<table><thead><tr><th></th><th>Item</th><th>Buy</th><th>Sell</th><th>Margin</th><th>Profit</th><th>Alerts</th></tr></thead><tbody>';
  shown.forEach(i=>{
    const sel=i.id===selectedId?' selected':'';
    const mp=i.usable?((i.sell-i.buy)/i.buy*100):null;
    const profit=i.usable?(i.sell-i.buy-taxOf(i.sell)):null;
    const alert=(i.alert_above!=null?'above '+gp(i.alert_above)+' ':'')+(i.alert_below!=null?'below '+gp(i.alert_below):'')||'-';
    h+='<tr class="'+sel+'" data-id="'+i.id+'" onclick="selectId('+i.id+',false)">'+
      '<td>'+starHtml(i.id)+'</td>'+
      '<td class="name">'+escHtml(i.name)+'</td>'+
      (i.usable
        ?'<td>'+gp(i.buy)+'</td><td>'+gp(i.sell)+'</td>'+
         '<td class="margin '+marginClass(mp)+'">'+mp.toFixed(1)+'%</td>'+
         '<td class="'+(profit>0?'pos':profit<0?'neg':'dim')+'">'+gp(profit)+'</td>'
        :'<td class="dim" colspan="4">'+escHtml(i.reason||'no data')+'</td>')+
      '<td class="dim">'+escHtml(alert)+'</td></tr>';
  });
  h+='</tbody></table>';
  body.innerHTML=h;
  if(selectedId!=null)renderDetail(selectedId);
  else renderContextEmpty();
}

async function renderGE(){
  const bar=document.getElementById('viewbar');
  bar.innerHTML=viewbarHtml();
  const body=document.getElementById('listBody');
  const context=document.getElementById('contextPanel');
  body.innerHTML='<div class="loading"><span class="spinner"></span>Loading Grand Exchange...</div>';
  context.innerHTML='<div class="loading"><span class="spinner"></span></div>';
  try{
    const r=await fetch('/api/ge');
    if(!r.ok)throw new Error('GE API failed');
    geData=await r.json();
    document.getElementById('badgeGE').textContent=geData.slots.length||0;
    const slots=geData.slots||[];
    let h='<div class="ge-grid">';
    slots.forEach(s=>{h+=geSlotHtml(s)});
    for(let i=slots.length;i<8;i++)h+=geEmptySlotHtml();
    h+='</div>';
    if(!slots.length){
      h+='<div class="loading">No active offers — open a position with <code>trade open &lt;item&gt;</code> or the Paper Trading tab.</div>';
    }
    body.innerHTML=h;
    context.innerHTML='<div class="item-name" style="margin-bottom:12px">Grand Exchange</div>'+
      '<div class="metric-grid">'+
      metric('Active Offers',format(slots.length)+' / 8','gold')+
      metric('Open Value',format(geData.total_value||0)+' coins','')+
      metric('Empty Slots',format(geData.empty_count||0),'')+
      '</div>'+
      '<div class="notice" style="border-color:var(--border);color:var(--text-dim);background:var(--surface)">'+
      'Fill progress is simulated from 5-minute trade volume — high-volume items fill faster. Click Collect when an offer reaches 100%.</div>';
  }catch(e){
    body.innerHTML='<div class="loading">Error loading Grand Exchange: '+escHtml(e.message)+'</div>';
    context.innerHTML='';
  }
}
function geSlotHtml(slot){
  const pct=Math.max(0,Math.min(100,Math.round((slot.fill_pct||0)*100)));
  const buy=slot.offer_type==='buy';
  const filled=pct>=100;
  // Auto-trader positions close themselves (ge_fill) — show status, no
  // manual Collect button. Manual paper positions keep the Collect button.
  let action='';
  if(filled){
    action=slot.auto
      ?'<div class="ge-collect-btn visible" style="background:#2a4a2a;border-color:#4ecca3;color:#4ecca3;cursor:default">Auto</div>'
      :'<button class="ge-collect-btn visible" onclick="collectOffer('+slot.position_id+',event)">Collect</button>';
  }
  return '<div class="ge-slot" onclick="geSlotClick('+slot.position_id+')">'+
    '<div class="ge-offer-type '+(buy?'buy':'sell')+'">'+(buy?'Buy':'Sell')+'</div>'+
    '<img class="ge-slot-icon" src="'+escHtml(slot.icon_url_detail||'')+'" alt="" loading="lazy" onerror="this.style.display=\'none\'">'+
    '<div class="ge-slot-name" title="'+escHtml(slot.name)+'">'+escHtml(slot.name)+'</div>'+
    '<div class="ge-fill-track"><div class="ge-fill-bar '+(buy?'buy':'sell')+(filled?' filled':'')+'" style="width:'+pct+'%"></div></div>'+
    '<div class="ge-slot-price">'+format(slot.price)+' coins</div>'+
    action+
    '</div>';
}
function geEmptySlotHtml(){
  return '<div class="ge-slot empty"><div style="font-size:26px">&#127892;</div><div class="dim" style="font-size:10px">Empty</div></div>';
}
async function collectOffer(positionId,ev){
  if(ev)ev.stopPropagation();
  const btn=ev&&ev.target;
  if(btn)btn.textContent='Collecting...';
  try{
    const r=await fetch('/api/ge/collect',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({position_id:positionId})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.message||('HTTP '+r.status));
    document.getElementById('statusText').textContent='Collected '+d.name+': '+(d.profit>0?'+':'')+format(d.profit)+' gp';
    document.getElementById('statusDot').className='dot live';
    fetchData();
  }catch(e){
    document.getElementById('statusText').textContent='Error: '+e.message;
    document.getElementById('statusDot').className='dot err';
    if(btn)btn.textContent='Collect';
  }
}
function geSlotClick(positionId){
  const s=(geData&&geData.slots||[]).find(x=>x.position_id===positionId);
  if(!s)return;
  const pnl=s.unrealized;
  const pnlHtml=pnl!=null&&pnl!==0?'<span class="val '+(pnl>0?'green':'red')+'">'+(pnl>0?'+':'')+format(pnl)+' gp</span>':'<span class="val dim">-</span>';
  const curHtml=s.current_price!=null?format(s.current_price)+' gp':'<span class="dim">-</span>';
  const spreadHtml=s.spread_pct!=null?s.spread_pct.toFixed(2)+'%':'<span class="dim">-</span>';
  const entryOfferHtml=s.entry_offer!=null?format(s.entry_offer)+' gp':'<span class="dim">-</span>';
  const entrySellHtml=s.entry_sell!=null?format(s.entry_sell)+' gp':'<span class="dim">-</span>';
  document.getElementById('contextPanel').innerHTML=
    '<div class="item-name">'+escHtml(s.name)+'</div>'+
    '<div class="metric-grid">'+
    metric('Offer',s.offer_type==='buy'?'Buy':'Sell','')+
    metric('Quantity',format(s.qty),'')+
    metric('Buy Price',format(s.buy_price)+' gp','')+
    metric('Fill',Math.round((s.fill_pct||0)*100)+'%','gold')+
    metric('Total Value',format(s.price)+' coins','')+
    metric('Current Price',curHtml,'')+
    metric('Unrealized',pnlHtml,'')+
    metric('Age',fmtAge((s.age_minutes||0)*60),'')+
    metric('Status',escHtml(s.status||'pending'),'')+
    metric('Entry Bid',entrySellHtml,'')+
    metric('Entry Offer',entryOfferHtml,'')+
    metric('Entry Spread',spreadHtml,'')+
    (s.auto?metric('Managed','Auto (trader)','gold'):'')+
    '</div>';
}
async function showGEHistory(){
  const overlay=document.createElement('div');
  overlay.className='ge-history-overlay';
  overlay.innerHTML='<div class="ge-history-panel"><div class="item-name" style="margin-bottom:12px">Grand Exchange History</div>'+
    '<div class="loading"><span class="spinner"></span>Loading...</div></div>';
  document.body.appendChild(overlay);
  overlay.addEventListener('click',e=>{if(e.target===overlay)overlay.remove()});
  try{
    const r=await fetch('/api/trades');
    const d=await r.json();
    const trades=(d.trades||[]).filter(t=>t.strategy==='auto'||t.strategy==='ge_collect').slice(0,20);
    let h='<table><thead><tr><th>Date</th><th>Item</th><th>Qty</th><th>Buy</th><th>Sell</th><th>Profit</th></tr></thead><tbody>';
    trades.forEach(t=>{
      const p=t.profit||0;
      h+='<tr><td>'+escHtml(String(t.timestamp||'').slice(0,16))+'</td><td class="name">'+escHtml(t.name||'')+'</td>'+
        '<td>'+format(t.qty||0)+'</td><td>'+format(t.buy_price||0)+'</td><td>'+format(t.sell_price||0)+'</td>'+
        '<td class="margin '+(p>0?'pos':p<0?'neg':'neutral')+'">'+format(p)+'</td></tr>';
    });
    h+='</tbody></table>';
    if(!trades.length)h='<div class="loading">No collected offers yet — fill an offer and click Collect.</div>';
    h+='<div style="text-align:right;margin-top:12px"><button class="act-btn" onclick="closeGEHistory(this)">Close</button></div>';
    overlay.querySelector('.ge-history-panel').innerHTML=
      '<div class="item-name" style="margin-bottom:12px">Grand Exchange History</div>'+h;
  }catch(e){
    overlay.querySelector('.ge-history-panel').innerHTML=
      '<div class="item-name" style="margin-bottom:12px">Grand Exchange History</div>'+
      '<div class="loading">Error: '+escHtml(e.message)+'</div>';
  }
}
function closeGEHistory(btn){
  const ov=btn.closest('.ge-history-overlay');
  if(ov)ov.remove();
}
async function renderBank(){
  const bar=document.getElementById('viewbar');
  bar.innerHTML=viewbarHtml();
  const body=document.getElementById('listBody');
  const context=document.getElementById('contextPanel');
  body.innerHTML='<div class="loading"><span class="spinner"></span>Loading bank...</div>';
  context.innerHTML='<div class="loading"><span class="spinner"></span></div>';
  try{
    const r=await fetch('/api/bank');
    if(!r.ok)throw new Error('Bank API failed');
    bankData=await r.json();
    document.getElementById('badgeBank').textContent=bankData.slot_count||0;
    const items=bankData.items||[];
    const pnl=bankData.unrealized_pnl||0;
    const pnlHtml=pnl!==0?'<span class="val '+(pnl>0?'green':'red')+'">'+(pnl>0?'+':'')+format(pnl)+' gp</span>':'<span class="val dim">0 gp</span>';
    let h='<div class="bank-grid">';
    items.forEach(it=>{h+=bankSlotHtml(it)});
    h+='</div>';
    if(!items.length){
      h='<div class="loading">The bank is empty — open positions with <code>trade open &lt;item&gt;</code> or the Paper Trading tab.</div>';
    }
    h+='<div class="bank-footer"><span>Total holdings: <span class="gold">'+format(bankData.total_value||0)+' gp</span></span>'+
      '<span>Unrealized P&amp;L: <span class="'+(pnl>0?'pos':pnl<0?'neg':'dim')+'">'+(pnl>0?'+':'')+format(pnl)+' gp</span></span>'+
      '<span>'+format(bankData.slot_count||0)+' item stacks</span></div>';
    body.innerHTML=h;
    context.innerHTML='<div class="item-name" style="margin-bottom:12px">Bank of RuneScape</div>'+
      '<div class="metric-grid">'+
      metric('Total Holdings',format(bankData.total_value||0)+' gp','gold')+
      metric('Unrealized P&L',pnlHtml,'')+
      metric('Cost Basis',format(bankData.cost_basis||0)+' gp','')+
      metric('Item Stacks',format(bankData.slot_count||0),'')+
      '</div>';
  }catch(e){
    body.innerHTML='<div class="loading">Error loading bank: '+escHtml(e.message)+'</div>';
    context.innerHTML='';
  }
}
function bankSlotHtml(it){
  const qtyTxt=it.total_qty>=10000?gp(it.total_qty):format(it.total_qty);
  const pnl=it.unrealized_pnl;
  const pnlTxt=pnl!=null&&pnl!==0?'<span class="'+(pnl>0?'pos':'neg')+'">'+(pnl>0?'+':'')+format(pnl)+' gp</span>':'<span class="dim">-</span>';
  return '<div class="bank-slot" onclick="bankSlotClick('+it.item_id+')">'+
    '<img class="bank-slot-icon" src="'+escHtml(it.icon_url||'')+'" alt="" loading="lazy" onerror="this.style.display=\'none\'">'+
    '<div class="bank-slot-qty">'+qtyTxt+'</div>'+
    '<div class="bank-tooltip"><b>'+escHtml(it.name)+'</b><br>Qty: '+format(it.total_qty)+
    '<br>Avg buy: '+format(it.avg_buy_price)+' gp'+
    '<br>Current: '+(it.current_price!=null?format(it.current_price)+' gp':'<span class="dim">-</span>')+
    '<br>P&amp;L: '+pnlTxt+'</div></div>';
}
function bankSlotClick(itemId){
  const it=(bankData&&bankData.items||[]).find(x=>x.item_id===itemId);
  if(!it)return;
  const pnl=it.unrealized_pnl;
  const pnlHtml=pnl!=null&&pnl!==0?'<span class="val '+(pnl>0?'green':'red')+'">'+(pnl>0?'+':'')+format(pnl)+' gp</span>':'<span class="val dim">-</span>';
  const pctHtml=it.unrealized_pct!=null?(it.unrealized_pct>0?'+':'')+it.unrealized_pct.toFixed(2)+'%':'-';
  document.getElementById('contextPanel').innerHTML=
    '<div class="item-name">'+escHtml(it.name)+'</div>'+
    '<div class="metric-grid">'+
    metric('Quantity',format(it.total_qty),'')+
    metric('Avg Buy Price',format(it.avg_buy_price)+' gp','')+
    metric('Current Price',it.current_price!=null?format(it.current_price)+' gp':'<span class="dim">-</span>','')+
    metric('Total Value',format(it.total_value)+' gp','gold')+
    metric('Cost Basis',format(it.cost_basis)+' gp','')+
    metric('Unrealized',pnlHtml,'')+
    metric('Unrealized %',pctHtml,pnl!=null&&pnl>0?'green':pnl!=null&&pnl<0?'red':'')+
    metric('Positions',format(it.position_count),'')+
    '</div>';
}

async function renderProcess(){
  const bar=document.getElementById('viewbar');
  bar.innerHTML=viewbarHtml();
  const body=document.getElementById('listBody');
  const context=document.getElementById('contextPanel');
  body.innerHTML='<div class="loading"><span class="spinner"></span>Loading materials...</div>';
  context.innerHTML='<div class="loading"><span class="spinner"></span></div>';
  try{
    const r=await fetch('/api/process');
    if(!r.ok)throw new Error('Process API failed');
    const data=await r.json();
    let recipes=data.recipes||[];
    const sel=document.getElementById('processSkill');
    if(sel&&sel.value)recipes=recipes.filter(x=>x.skill===sel.value);
    document.getElementById('badgeProcess').textContent=recipes.length;
    let h='<table><thead><tr><th>Skill</th><th>Output</th><th>Inputs</th><th>Profit</th><th>ROI%</th><th>GP/hr</th></tr></thead><tbody>';
    recipes.forEach(x=>{
      const roi=x.roi_pct!=null?x.roi_pct.toFixed(1):'-';
      const inputs=(x.inputs||[]).map(i=>escHtml(i.name)+' &times;'+i.qty).join(', ')||'-';
      h+='<tr><td class="dim">'+escHtml(x.skill||'')+'</td>'+
        '<td class="name">'+escHtml(x.name)+'</td>'+
        '<td class="dim">'+inputs+'</td>'+
        '<td class="margin pos">'+format(x.profit)+' gp</td>'+
        '<td>'+roi+'%</td>'+
        '<td class="margin pos">'+format(x.gp_per_hour)+'</td></tr>';
    });
    h+='</tbody></table>';
    if(!recipes.length)h='<div class="loading">No profitable processing recipes right now — buy inputs cheap, sell output dear.</div>';
    body.innerHTML=h;
    context.innerHTML='<div class="item-name" style="margin-bottom:12px">Materials Processing</div>'+
      '<div class="metric-grid">'+
      metric('Recipes',format(recipes.length),'gold')+
      metric('Best GP/hr',recipes.length?format(recipes[0].gp_per_hour):'-','gold')+
      metric('Best ROI',recipes.length?(recipes[0].roi_pct||0).toFixed(1)+'%':'','')+
      '</div>'+
      '<div class="notice" style="border-color:var(--border);color:var(--text-dim);background:var(--surface)">'+
      'Buys inputs at instant-buy, sells the processed output at instant-sell (2% GE tax on the sale). '+
      'GP/hr is capped by action rate, the output buy limit, and the limiting input feed.</div>';
  }catch(e){
    body.innerHTML='<div class="loading">Error loading materials: '+escHtml(e.message)+'</div>';
    context.innerHTML='';
  }
}

function renderContextEmpty(){
  document.getElementById('contextPanel').innerHTML='<div class="empty">&#8592; Select an item to inspect</div>';
}

function renderDetail(id){
  const item=allItems.find(i=>i.id===id)||watchDetail(id);
  if(!item){
    renderContextEmpty();
    return;
  }
  if(item.unusable){
    document.getElementById('contextPanel').innerHTML=
      '<div class="item-name">'+escHtml(item.name)+'</div>'+
      '<div class="notice warn-red">No usable price data ('+escHtml(item.reason||'unknown')+').</div>';
    return;
  }
  const mp=marginPct(item),rp=roiPct(item);
  const tax=taxOf(item.sell_price);
  const net=(item.profit!=null)?item.profit:(item.sell_price-item.buy_price-tax);
  let notice='';
  if(item.buy_price>0&&mp>500)notice='<div class="notice warn-red">Extreme spread ('+mp.toFixed(0)+'%). Confirm real trade volume before acting.</div>';
  else if(item.buy_price>0&&mp>50&&(item.volume||0)<50)notice='<div class="notice">Wide spread with low volume — treat with caution.</div>';
  document.getElementById('contextPanel').innerHTML=
    '<div class="item-name">'+escHtml(item.name)+starHtml(item.id)+'</div>'+
    '<div class="metric-grid">'+
    metric('Buy',format(item.buy_price)+' gp','')+
    metric('Sell',format(item.sell_price)+' gp','')+
    metric('Margin','<span class="val '+marginClass(mp)+'">'+mp.toFixed(1)+'%</span>','')+
    metric('Net Profit',format(net)+' gp',net>0?'green':net<0?'red':'')+
    metric('Tax','<span class="val dim">'+format(tax)+' gp</span>','')+
    metric('ROI',rp.toFixed(1)+'%',rp>0?'green':'')+
    metric('GP / Hour',format(item.gp_per_hour||0)+' gp','gold')+
    metric('RS Score',(item.rs_score||0).toFixed(0),'gold')+
    metric('Volume (5m)',format(item.volume||0),'')+
    metric('Buy Limit',format(item.buy_limit||0),'')+
    metric('Alch Value',format(item.alch_value||0)+' gp','')+
    metric('Members','<span class="val '+(item.members?'gold':'dim')+'">'+(item.members?'Yes':'No')+'</span>','')+
    '</div>'+notice+
    '<div class="chart-title">Price history (8h, 5m)</div><canvas id="spark" height="84"></canvas>';
  drawSpark(id);
}
function watchDetail(id){
  const w=viewRows.find(r=>r.id===id);
  if(!w)return null;
  if(!w.usable)return {id:w.id,name:w.name,unusable:true,reason:w.reason};
  return {id:w.id,name:w.name,buy_price:w.buy,sell_price:w.sell,volume:0,
          buy_limit:0,alch_value:0,members:false,profit:w.sell-w.buy-taxOf(w.sell),gp_per_hour:0,rs_score:0};
}
async function drawSpark(id){
  const cv=document.getElementById('spark');
  if(!cv)return;
  const seq=++sparkSeq;
  let pts=[];
  try{
    const r=await fetch('/api/timeseries?id='+id);
    pts=(await r.json()).points||[];
  }catch(e){}
  if(pts.length<2){
    if(seq!==sparkSeq)return;
    cv.style.display='none';
    const note=document.createElement('div');
    note.className='loading';
    note.textContent='No recent trade history for this item.';
    cv.parentNode.appendChild(note);
    return;
  }
  const draw=()=>{
    if(seq!==sparkSeq)return;
    const dpr=window.devicePixelRatio||1,w=cv.clientWidth;
    if(!w){requestAnimationFrame(draw);return}
    const h=84;
    cv.width=w*dpr;cv.height=h*dpr;cv.style.height=h+'px';
    const ctx=cv.getContext('2d');ctx.scale(dpr,dpr);
    const highs=pts.map(p=>p.avgHigh),lows=pts.map(p=>p.avgLow);
    const all=highs.concat(lows);
    const lo=Math.min(...all),hi=Math.max(...all),span=Math.max(hi-lo,1);
    const x=i=>i/(pts.length-1)*w;
    const y=v=>h-4-(h-12)*(v-lo)/span;
    ctx.strokeStyle='#1e293b';ctx.fillStyle='#94a3b8';ctx.font='10px system-ui';
    for(let g=0;g<=3;g++){
      const v=lo+span*g/3,gy=y(v);
      ctx.beginPath();ctx.moveTo(0,gy);ctx.lineTo(w,gy);ctx.stroke();
      ctx.fillText(Math.round(v).toLocaleString(),3,gy-2);
    }
    const line=(vals,color)=>{
      ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.beginPath();
      vals.forEach((v,i)=>{i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v))});
      ctx.stroke();
    };
    line(highs,'#22c55e');
    line(lows,'#60a5fa');
    ctx.lineWidth=1;
  };
  draw();
}

function traderNoticeHtml(trader){
  if(!trader.running){
    const last=trader.last_cycle_iso;
    const stale=last?'<div class="dim" style="margin-top:4px">Last known cycle: '+escHtml(String(last).slice(0,16))+' (state may be stale)</div>':'';
    return '<div class="notice" style="border-color:var(--border);color:var(--text-dim);background:var(--surface)">'+
      'Auto-trader not running'+(trader.local===false?' on this machine (synced state)':'')+
      ' — start it with <code>rshelper auto-trade</code>.'+stale+'</div>';
  }
  const last=trader.last_result||{};
  // The journal is the authoritative ledger (the state counter resets on
  // every daemon start), so prefer journal_realized_pnl when present.
  const tpnl=trader.journal_realized_pnl!=null?trader.journal_realized_pnl:(trader.realized_pnl||0);
  const cycles=trader.cycles||0;
  const errors=trader.errors||0;
  const where=trader.local?'this machine':'the Mac';
  const age=trader.last_cycle_age_sec;
  const ageTxt=age!=null?fmtAge(age):'unknown';
  const stale=trader.stale?' <span class="neg">(stale — '+ageTxt+' old; sync may be behind)</span>':'';
  let html='<div class="notice">Auto-trader running on '+where;
  html+='<div class="dim" style="margin-top:4px">Last cycle: '+escHtml(String(trader.last_cycle_iso||'-').slice(0,16))+
    ' ('+ageTxt+' ago)'+stale+
    ' — cycles '+format(cycles)+', errors '+format(errors)+
    ', realized P&L '+format(tpnl)+' gp'+
    (last.opened&&last.opened.length?' — opened '+last.opened.length+' this cycle':'')+
    (last.closed&&last.closed.length?' — closed '+last.closed.length+' this cycle':'')+
    (last.error?' — last error: '+escHtml(String(last.error).slice(0,120)):'')+
    '</div></div>';
  return html;
}

function fmtAge(sec){
  if(sec<60)return Math.round(sec)+'s';
  if(sec<3600)return Math.round(sec/60)+'m';
  return (sec/3600).toFixed(1)+'h';
}

function traderPerfHtml(trader,trades){
  const autoTrades=trades.filter(t=>t.strategy==='auto');
  if(!autoTrades.length)return '';
  let html='<h3 class="chart-title">Auto-trader performance</h3>';
  const byReason={};
  let wins=0,holdSum=0,holdN=0,slippageSum=0,slippageN=0,capSum=0,capN=0;
  let gapSum=0,gapN=0;
  autoTrades.forEach(t=>{
    const r=byReason[t.exit_reason||'other']||(byReason[t.exit_reason||'other']={count:0,profit:0,wins:0});
    r.count++;r.profit+=t.profit||0;
    if(t.profit>0)r.wins++;
    if(t.profit>0)wins++;
    if(typeof t.hold_minutes==='number'){holdSum+=t.hold_minutes;holdN++;}
    if(typeof t.quote_sell==='number'&&typeof t.sell_price==='number'&&t.quote_sell>t.sell_price){
      slippageSum+=t.quote_sell-t.sell_price;slippageN++;
    }
    // Stop-loss damage beyond the designed exit (stop -2% x 0.97 fill slip):
    // the excess is cycle-latency gap on crash trades and should trend down
    // as the poll interval shrinks.
    if(t.exit_reason==='stop_loss'&&typeof t.sell_price==='number'){
      const design=(t.buy_price||0)*0.98*0.97;
      if(t.sell_price<design){gapSum+=(design-t.sell_price)/(t.buy_price||1)*100;gapN++;}
    }
    const cost=(t.buy_price||0)*(t.qty||0);
    const hold=t.hold_minutes||0;
    if(cost>0&&hold>0){capSum+=(t.profit||0)/cost/hold;capN++;}
  });
  const total=autoTrades.length;
  html+='<div class="metric-grid">'+
    metric('Auto Trades',format(total),'')+
    metric('Auto Win Rate',(wins/total*100).toFixed(1)+'%','gold')+
    metric('Avg Hold',holdN?(holdSum/holdN).toFixed(0)+' min':'-','')+
    metric('Capital Eff. (bps/min)',capN?(capSum/capN*10000).toFixed(1):'-','')+
    metric('Avg Stop Slippage',slippageN?format(Math.round(slippageSum/slippageN))+' gp':'-','')+
    metric('Avg Stop Gap',gapN?(gapSum/gapN).toFixed(1)+'%':'-','')+
    '</div>';
  // Win rate by hold bucket: fast wins = spread capture, slow wins = hold edge.
  const buckets={quick:{n:0,w:0},medium:{n:0,w:0},long:{n:0,w:0}};
  autoTrades.forEach(t=>{
    const h=t.hold_minutes||0;
    const b=h<=5?buckets.quick:h<=60?buckets.medium:buckets.long;
    b.n++;if(t.profit>0)b.w++;
  });
  html+='<table><thead><tr><th>Hold</th><th>#</th><th>Win%</th></tr></thead><tbody>'+
    '<tr><td>&le;5 min (spread capture)</td><td>'+format(buckets.quick.n)+'</td><td>'+
      (buckets.quick.n?(buckets.quick.w/buckets.quick.n*100).toFixed(0):'0')+'%</td></tr>'+
    '<tr><td>5-60 min</td><td>'+format(buckets.medium.n)+'</td><td>'+
      (buckets.medium.n?(buckets.medium.w/buckets.medium.n*100).toFixed(0):'0')+'%</td></tr>'+
    '<tr><td>&gt;60 min</td><td>'+format(buckets.long.n)+'</td><td>'+
      (buckets.long.n?(buckets.long.w/buckets.long.n*100).toFixed(0):'0')+'%</td></tr>'+
    '</tbody></table>';
  html+='<table><thead><tr><th>Exit</th><th>#</th><th>P&L</th><th>Win%</th></tr></thead><tbody>';
  Object.keys(byReason).sort().forEach(r=>{
    const row=byReason[r];
    html+='<tr><td>'+escHtml(r)+'</td><td>'+format(row.count)+'</td>'+
      '<td class="margin '+(row.profit>0?'pos':row.profit<0?'neg':'neutral')+'">'+format(row.profit)+'</td>'+
      '<td>'+(row.count?(row.wins/row.count*100).toFixed(0):'0')+'%</td></tr>';
  });
  html+='</tbody></table>';
  return html;
}

async function renderPaper(){
  const bar=document.getElementById('viewbar');
  bar.innerHTML=viewbarHtml();
  const body=document.getElementById('listBody');
  const context=document.getElementById('contextPanel');
  body.innerHTML='<div class="loading"><span class="spinner"></span>Loading paper trading...</div>';
  context.innerHTML='<div class="loading"><span class="spinner"></span></div>';
  const stratParam=strategy?'?strategy='+strategy:'';
  try{
    const [pr,tr,hr,posr,trr]=await Promise.all([
      fetch('/api/pnl'+stratParam),fetch('/api/trades'+stratParam),
      fetch('/api/history?paper=1'+(strategy?'&strategy='+strategy:'')),fetch('/api/positions'),
      fetch('/api/trader')
    ]);
    if(!pr.ok||!tr.ok||!hr.ok||!posr.ok||!trr.ok)throw new Error('paper API failed');
    const pnl=await pr.json();
    const trades=(await tr.json()).trades||[];
    const h=await hr.json();
    const pos=(await posr.json())||{positions:[]};
    const trader=(await trr.json())||{running:false};
    const s=h.summary||{};
    context.innerHTML='<div class="item-name" style="margin-bottom:12px">Paper Trading</div>'+
      '<div class="metric-grid">'+
      metric('Total P&L',format(pnl.total_profit||0)+' gp',(pnl.total_profit||0)>0?'green':(pnl.total_profit||0)<0?'red':'')+
      metric('ROI',(pnl.roi_pct||0).toFixed(2)+'%',(pnl.roi_pct||0)>0?'green':'')+
      metric('Win Rate',(pnl.win_rate||0).toFixed(1)+'%','gold')+
      metric('Trades',format(pnl.trade_count||0),'')+
      metric('Items',format(pnl.items_traded||0),'')+
      metric('Active Days',format(s.active_days||0),'')+
      metric('Tax Paid',format(pnl.total_tax_paid||0)+' gp','')+
      metric('Cost Basis',format(pnl.total_cost_basis||0)+' gp','')+
      metric('Best','<span class="val green">'+format(pnl.best_trade||0)+'</span>','')+
      metric('Worst','<span class="val red">'+format(pnl.worst_trade||0)+'</span>','')+
      metric('Active GP/hr',format(pnl.active_gp_per_hour||0)+' gp','gold')+
      metric('Profit Factor',pnl.profit_factor!=null?format(pnl.profit_factor):'-','gold')+
      metric('Max Drawdown',format(pnl.max_drawdown||0)+' gp',(pnl.max_drawdown||0)>0?'red':'')+
      metric('Open Positions',format((pos.positions||[]).length),'')+
      metric('Unrealized',format(pos.unrealized||0)+' gp',(pos.unrealized||0)>0?'green':(pos.unrealized||0)<0?'red':'')+
      '</div>';
    let html='';
    const openPos=pos.positions||[];
    html+=traderNoticeHtml(trader);
    html+=traderPerfHtml(trader,trades);
    html+='<h3 class="chart-title">Open positions</h3>';
    if(!openPos.length){
      html+='<div class="loading">No open positions — open one with <code>trade open &lt;item&gt;</code>.</div>';
    }else{
      html+='<table><thead><tr><th>Item</th><th>Qty</th><th>Buy</th><th>Current</th><th>Unrealized</th><th>Opened</th></tr></thead><tbody>';
      openPos.forEach(p=>{
        const unreal=p.unrealized;
        const cur=p.usable?p.current:null;
        html+='<tr><td class="name">'+escHtml(p.name)+'</td><td>'+format(p.qty)+'</td>'+
          '<td>'+format(p.buy_price)+'</td>'+
          (cur!=null?'<td>'+format(cur)+'</td>':'<td class="dim">-</td>')+
          '<td class="margin '+(unreal!=null?(unreal>0?'pos':unreal<0?'neg':'neutral'):'dim')+'">'+
          (unreal!=null?format(unreal):'-')+'</td>'+
          '<td>'+escHtml(String(p.opened_at||'').slice(0,10))+'</td></tr>';
      });
      html+='</tbody></table>';
    }
    const traded=(h.items||[]).filter(i=>i.trade_count>0);
    html+='<h3 class="chart-title">Current status — live market on traded items</h3>';
    if(!traded.length){
      html+='<div class="loading">No trades yet — log one with <code>trade paper &lt;item&gt;</code> or the Trades tab.</div>';
    }else{
      let prices={};
      try{
        const ids=traded.map(i=>i.item_id).join(',');
        const pr2=await fetch('/api/prices?ids='+ids);
        if(pr2.ok)prices=(await pr2.json()).prices||{};
      }catch(e){}
      html+='<table><thead><tr><th>Item</th><th>Trades</th><th>Qty</th><th>Realized P&L</th><th>Live Buy</th><th>Live Sell</th><th>Live Margin</th></tr></thead><tbody>';
      traded.forEach(i=>{
        const cur=prices[String(i.item_id)];
        const live=cur&&cur.usable;
        const liveBuy=live?cur.buy:null,liveSell=live?cur.sell:null;
        const mp=(liveBuy>0)?((liveSell-liveBuy)/liveBuy*100):null;
        html+='<tr><td class="name">'+escHtml(i.name)+'</td><td>'+format(i.trade_count)+'</td><td>'+format(i.qty)+'</td>'+
          '<td class="margin '+(i.profit>0?'pos':i.profit<0?'neg':'neutral')+'">'+format(i.profit)+'</td>'+
          (live?'<td>'+format(liveBuy)+'</td><td>'+format(liveSell)+'</td>'+
            '<td class="margin '+marginClass(mp)+'">'+mp.toFixed(1)+'%</td>'
            :'<td>-</td><td>-</td><td>-</td>')+
          '</tr>';
      });
      html+='</tbody></table>';
    }
    html+='<h3 class="chart-title">Trades by item</h3>';
    if(!trades.length){
      html+='<div class="loading">No trades yet — open one with <code>trade open &lt;item&gt;</code> or <code>trade paper &lt;item&gt;</code>.</div>';
    }else{
      const byItem={};
      trades.forEach(t=>{
        const k=t.item_id||t.name||'?';
        const g=byItem[k]||(byItem[k]={name:t.name||'?',count:0,qty:0,profit:0,wins:0,last:''});
        g.count++;g.qty+=t.qty||0;g.profit+=t.profit||0;
        if(t.profit>0)g.wins++;
        if(!g.last||t.timestamp>g.last)g.last=t.timestamp||'';
      });
      const grouped=Object.values(byItem).sort((a,b)=>b.profit-a.profit);
      html+='<table><thead><tr><th>Item</th><th># Trades</th><th>Total Qty</th><th>Total P&L</th><th>Win Rate</th><th>Last Trade</th></tr></thead><tbody>';
      grouped.forEach(g=>{
        const wr=g.count?g.wins/g.count*100:0;
        html+='<tr><td class="name">'+escHtml(g.name)+'</td><td>'+format(g.count)+'</td><td>'+format(g.qty)+'</td>'+
          '<td class="margin '+(g.profit>0?'pos':g.profit<0?'neg':'neutral')+'">'+format(g.profit)+'</td>'+
          '<td>'+wr.toFixed(0)+'%</td><td>'+escHtml(String(g.last).slice(0,10))+'</td></tr>';
      });
      html+='</tbody></table>';
      html+='<h3 class="chart-title">Recent trades</h3><table><thead><tr><th>Date</th><th>Item</th><th>Qty</th><th>Buy</th><th>Sell</th><th>Profit</th></tr></thead><tbody>';
      trades.slice(0,10).forEach(t=>{
        const p=t.profit||0;
        html+='<tr><td>'+escHtml(String(t.timestamp||'').slice(0,16))+'</td><td class="name">'+escHtml(t.name||'')+'</td>'+
          '<td>'+format(t.qty||0)+'</td><td>'+format(t.buy_price||0)+'</td><td>'+format(t.sell_price||0)+'</td>'+
          '<td class="margin '+(p>0?'pos':p<0?'neg':'neutral')+'">'+format(p)+'</td></tr>';
      });
      html+='</tbody></table>';
    }
    const buckets=h.buckets||[];
    if(buckets.length>=2){
      html+='<h3 class="chart-title">Historical results — cumulative P&L</h3><canvas id="paperCum" height="220"></canvas>';
      html+='<h3 class="chart-title">Historical results — daily trades and win rate</h3><canvas id="paperDaily" height="220"></canvas>';
    }else if(buckets.length===1){
      html+='<h3 class="chart-title">Historical results</h3><div class="loading">One active day so far — cumulative charts appear from the second day.</div>';
    }
    html+=historyTablesHtml(h);
    body.innerHTML=html;
    if(buckets.length>=2){
      drawCumulative(document.getElementById('paperCum'),buckets);
      drawDaily(document.getElementById('paperDaily'),buckets);
    }
  }catch(e){
    body.innerHTML='<div class="loading">Error loading paper trading: '+escHtml(e.message)+'</div>';
    context.innerHTML='';
  }
}

function historyTablesHtml(h){
  const eras=h.eras||[],items=h.items||[];
  let html='';
  if(eras.length){
    html+='<h3 class="chart-title">Tuning eras</h3><table><thead><tr><th>Start</th><th>End</th><th>Changed</th><th>Trades</th><th>Profit</th><th>Win%</th><th>ROI%</th><th>/day</th></tr></thead><tbody>';
    let prev=null;
    eras.forEach(e=>{
      const c=e.config||{};
      const changed=prev?Object.keys(c).filter(k=>JSON.stringify(c[k])!==JSON.stringify(prev[k])).join(', ')||'(none)':'(initial)';
      prev=c;
      html+='<tr><td>'+escHtml(e.start)+'</td><td>'+escHtml(e.end)+'</td><td class="name">'+escHtml(changed)+'</td>'+
        '<td>'+format(e.trade_count||0)+'</td><td class="margin '+(e.profit>0?'pos':e.profit<0?'neg':'neutral')+'">'+format(e.profit||0)+'</td>'+
        '<td>'+(e.win_rate==null?'-':e.win_rate.toFixed(1))+'</td><td>'+(e.roi_pct==null?'-':e.roi_pct.toFixed(2))+'</td><td>'+(e.trades_per_day||0)+'</td></tr>';
    });
    html+='</tbody></table>';
  }
  if(items.length){
    html+='<h3 class="chart-title">Per-item P&L</h3><table><thead><tr><th>Item</th><th>Trades</th><th>Qty</th><th>Cost</th><th>Profit</th><th>ROI%</th><th>Win%</th></tr></thead><tbody>';
    items.forEach(i=>{
      html+='<tr><td class="name">'+escHtml(i.name)+'</td><td>'+format(i.trade_count)+'</td><td>'+format(i.qty)+'</td>'+
        '<td>'+format(i.cost_basis)+'</td><td class="margin '+(i.profit>0?'pos':i.profit<0?'neg':'neutral')+'">'+format(i.profit)+'</td>'+
        '<td>'+(i.roi_pct==null?'-':i.roi_pct.toFixed(2))+'</td>'+
        '<td>'+(i.win_rate==null?'-':i.win_rate.toFixed(1))+'</td></tr>';
    });
    html+='</tbody></table>';
  }
  return html;
}

function drawCumulative(cv,buckets){
  if(!buckets||buckets.length<2)return;
  const dpr=window.devicePixelRatio||1,w=cv.clientWidth;
  if(!w){requestAnimationFrame(()=>drawCumulative(cv,buckets));return}
  const h=220;
  cv.width=w*dpr;cv.height=h*dpr;cv.style.height=h+'px';
  const ctx=cv.getContext('2d');ctx.scale(dpr,dpr);
  const pad={l:64,r:12,t:14,b:24};
  const vals=buckets.map(b=>b.cumulative_profit||0);
  const lo=Math.min(0,...vals),hi=Math.max(0,...vals),span=Math.max(hi-lo,1);
  const x=i=>pad.l+(w-pad.l-pad.r)*i/(buckets.length-1);
  const y=v=>pad.t+(h-pad.t-pad.b)*(hi-v)/span;
  ctx.strokeStyle='#1e293b';ctx.fillStyle='#94a3b8';ctx.font='11px system-ui';
  for(let g=0;g<=4;g++){
    const v=lo+span*g/4,gy=y(v);
    ctx.beginPath();ctx.moveTo(pad.l,gy);ctx.lineTo(w-pad.r,gy);ctx.stroke();
    ctx.fillText(Math.round(v).toLocaleString(),4,gy+3);
  }
  let prevChanged=null;
  buckets.forEach((b,i)=>{
    if(b.config_changed){
      const cx=x(i);
      ctx.strokeStyle='#c9a84c';ctx.setLineDash([4,4]);
      ctx.beginPath();ctx.moveTo(cx,pad.t);ctx.lineTo(cx,h-pad.b);ctx.stroke();
      ctx.setLineDash([]);
      if(prevChanged!=null){
        ctx.fillStyle='rgba(201,168,76,.06)';
        ctx.fillRect(x(prevChanged),pad.t,x(i)-x(prevChanged),h-pad.t-pad.b);
      }
      prevChanged=i;
    }
  });
  ctx.strokeStyle='#22c55e';ctx.lineWidth=2;ctx.beginPath();
  buckets.forEach((b,i)=>{
    const px=x(i),py=y(b.cumulative_profit||0);
    i?ctx.lineTo(px,py):ctx.moveTo(px,py);
  });
  ctx.stroke();ctx.lineWidth=1;
  ctx.fillStyle='#e2e8f0';
  buckets.forEach((b,i)=>{ctx.fillText(b.date.slice(5),x(i)-12,h-8)});
}
function drawDaily(cv,buckets){
  const dpr=window.devicePixelRatio||1,w=cv.clientWidth;
  if(!w){requestAnimationFrame(()=>drawDaily(cv,buckets));return}
  const h=220;
  cv.width=w*dpr;cv.height=h*dpr;cv.style.height=h+'px';
  const ctx=cv.getContext('2d');ctx.scale(dpr,dpr);
  const pad={l:64,r:12,t:14,b:24};
  const maxTrades=Math.max(1,...buckets.map(b=>b.trade_count||0));
  const x=i=>pad.l+(w-pad.l-pad.r)*(i+0.5)/buckets.length;
  const bw=(w-pad.l-pad.r)/buckets.length*0.6;
  const by=v=>pad.t+(h-pad.t-pad.b)*(maxTrades-v)/maxTrades;
  const y2=v=>pad.t+(h-pad.t-pad.b)*(100-(v==null?0:v))/100;
  ctx.fillStyle='#94a3b8';ctx.font='11px system-ui';
  for(let g=0;g<=4;g++){
    const gy=by(maxTrades*g/4);
    ctx.strokeStyle='#1e293b';ctx.beginPath();ctx.moveTo(pad.l,gy);ctx.lineTo(w-pad.r,gy);ctx.stroke();
    ctx.fillText(Math.round(maxTrades*g/4),4,gy+3);
  }
  buckets.forEach((b,i)=>{
    ctx.fillStyle=b.config_changed?'#c9a84c':'#1a2332';
    ctx.fillRect(x(i)-bw/2,by(b.trade_count||0),bw,h-pad.b-by(b.trade_count||0));
    ctx.fillStyle='#94a3b8';ctx.fillText(b.date.slice(5),x(i)-12,h-8);
  });
  ctx.strokeStyle='#60a5fa';ctx.lineWidth=2;ctx.beginPath();
  buckets.forEach((b,i)=>{
    const px=x(i),py=y2(b.win_rate);
    i?ctx.lineTo(px,py):ctx.moveTo(px,py);
  });
  ctx.stroke();ctx.lineWidth=1;
  ctx.fillStyle='#60a5fa';ctx.fillText('win %',w-46,pad.t+4);
}

function tick(){
  countdown--;
  if(countdown<=0){fetchData();countdown=refreshSecs}
  document.getElementById('statRefresh').textContent=countdown+'s';
}

fetchData();
setInterval(tick,1000);
</script>
</body>
</html>"""
