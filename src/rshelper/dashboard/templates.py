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
  --bg:#0a0e17;--surface:#111827;--surface2:#1a2332;
  --gold:#c9a84c;--gold-dim:#8b7233;--green:#22c55e;--red:#ef4444;
  --yellow:#eab308;--text:#e2e8f0;--text-dim:#94a3b8;--border:#1e293b;
  --radius:6px;--font:system-ui,-apple-system,sans-serif;
}
body{background:var(--bg);color:var(--text);font-family:var(--font);height:100vh;display:flex;flex-direction:column;overflow:hidden}
.topbar{
  display:flex;align-items:center;gap:16px;padding:12px 20px;
  background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0;
}
.topbar h1{font-size:18px;font-weight:700;color:var(--gold);white-space:nowrap}
.topbar h1::before{content:'';display:inline-block;width:18px;height:18px;background:var(--gold);border-radius:50%;margin-right:8px;vertical-align:-3px}
.topbar .search{flex:1;max-width:360px}
.topbar .search input{
  width:100%;padding:7px 12px;background:var(--bg);border:1px solid var(--border);
  border-radius:var(--radius);color:var(--text);font-size:13px;outline:none
}
.topbar .search input:focus{border-color:var(--gold-dim)}
.stats{display:flex;gap:16px;margin-left:auto}
.stat{text-align:center}
.stat .val{font-size:18px;font-weight:700}
.stat .lbl{font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px}
.stat .val.green{color:var(--green)}.stat .val.gold{color:var(--gold)}.stat .val.dim{color:var(--text-dim)}
.controls{
  display:flex;align-items:center;gap:12px;padding:8px 20px;
  background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0
}
.controls select,.controls button{
  padding:5px 10px;background:var(--bg);border:1px solid var(--border);
  border-radius:var(--radius);color:var(--text);font-size:12px;cursor:pointer
}
.controls select:focus,.controls button:focus{outline:none;border-color:var(--gold-dim)}
.controls button.active{background:var(--surface2);border-color:var(--gold);color:var(--gold)}
.controls .count{font-size:12px;color:var(--text-dim);margin-left:auto}
.main{display:flex;flex:1;overflow:hidden}
.table-panel{flex:1;overflow-y:auto;padding:0 20px 20px;}
.table-panel table{width:100%;border-collapse:collapse;font-size:13px}
.table-panel th{
  position:sticky;top:0;background:var(--bg);padding:10px 8px;
  text-align:right;font-weight:600;color:var(--text-dim);font-size:11px;
  text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border);z-index:1
}
.table-panel th:first-child,.table-panel td:first-child{text-align:left;padding-left:0}
.table-panel td{padding:8px;text-align:right;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}
.table-panel tr{cursor:pointer;transition:background .1s}
.table-panel tr:hover{background:var(--surface2)}
.table-panel tr.selected{background:var(--surface2);outline:1px solid var(--gold-dim)}
.table-panel .name{text-align:left;font-weight:500}
.table-panel .margin{font-weight:600}
.table-panel .margin.pos{color:var(--green)}.table-panel .margin.neg{color:var(--red)}.table-panel .margin.neutral{color:var(--yellow)}
.table-panel .rank{color:var(--text-dim);font-size:12px;text-align:center}
.detail-panel{
  width:340px;flex-shrink:0;background:var(--surface);
  border-left:1px solid var(--border);padding:20px;overflow-y:auto;
  display:flex;flex-direction:column;gap:16px;
}
.detail-panel .empty{color:var(--text-dim);text-align:center;margin-top:60px;font-size:14px}
.detail-panel .item-name{font-size:20px;font-weight:700;color:var(--gold)}
.detail-panel .metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.detail-panel .metric{background:var(--bg);border-radius:var(--radius);padding:12px;}
.detail-panel .metric .val{font-size:16px;font-weight:700;font-variant-numeric:tabular-nums}
.detail-panel .metric .lbl{font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}
.detail-panel .metric .val.green{color:var(--green)}.detail-panel .metric .val.red{color:var(--red)}.detail-panel .metric .val.gold{color:var(--gold)}
.footer{
  display:flex;align-items:center;justify-content:space-between;
  padding:6px 20px;background:var(--surface);border-top:1px solid var(--border);
  font-size:11px;color:var(--text-dim);flex-shrink:0
}
.footer .dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:4px;vertical-align:middle}
.footer .dot.live{background:var(--green)}.footer .dot.err{background:var(--red)}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.loading{display:flex;align-items:center;justify-content:center;padding:40px;gap:8px;color:var(--text-dim)}
</style>
</head>
<body>
<div class="topbar">
  <h1>RSHelper</h1>
  <div class="search"><input type="text" id="search" placeholder="Filter items..." oninput="applyFilters()"></div>
  <div class="stats">
    <div class="stat"><div class="val dim" id="statCount">-</div><div class="lbl">Items</div></div>
    <div class="stat"><div class="val green" id="statBest">-</div><div class="lbl">Best Margin</div></div>
    <div class="stat"><div class="val gold" id="statRefresh">-</div><div class="lbl">Refresh</div></div>
  </div>
</div>
<div class="controls">
  <span style="font-size:12px;color:var(--text-dim)">Sort:</span>
  <select id="sortBy" onchange="applyFilters()">
    <option value="margin">Margin %</option>
    <option value="profit">Profit (gp)</option>
    <option value="volume">Volume</option>
    <option value="buy_price">Buy Price</option>
    <option value="sell_price">Sell Price</option>
    <option value="rs_score">RS Score</option>
  </select>
  <button id="btnDir" onclick="toggleDirection()" class="active">Desc</button>
  <button id="btnTrades" onclick="toggleTrades()">Trades</button>
  <span class="count" id="filterCount"></span>
</div>
<div class="main">
  <div class="table-panel" id="tablePanel">
    <div class="loading"><span class="spinner"></span>Loading scan data...</div>
  </div>
  <div class="detail-panel" id="detailPanel">
    <div class="empty">Select an item to see details</div>
  </div>
</div>
<div class="footer">
  <span><span class="dot live" id="statusDot"></span><span id="statusText">Connected</span></span>
  <span id="lastUpdated">Last updated: --</span>
</div>
<script>
let allItems=[];
let selectedId=null;
let sortCol='margin',sortDir='desc';
let showTrades=false;
const refreshSecs=60;
let countdown=refreshSecs;

function marginPct(item){
  if(item.buy_price<=0)return 0;
  return ((item.sell_price-item.buy_price)/item.buy_price*100);
}
function format(n){return n.toLocaleString()}

async function fetchData(){
  document.getElementById('statusText').textContent='Fetching...';
  document.getElementById('statusDot').className='dot';
  try{
    const r=await fetch('/api/scan');
    if(!r.ok)throw new Error(r.status);
    const d=await r.json();
    allItems=d.items||[];
    document.getElementById('statusText').textContent='Connected';
    document.getElementById('statusDot').className='dot live';
    applyFilters();
    updateStats();
    updateTime();
    if(selectedId!=null)reselectItem();
    countdown=refreshSecs;
  }catch(e){
    document.getElementById('statusText').textContent='Error: '+e.message;
    document.getElementById('statusDot').className='dot err';
  }
}

function updateStats(){
  document.getElementById('statCount').textContent=allItems.length;
  if(allItems.length){
    let best=allItems.reduce((a,b)=>marginPct(a)>marginPct(b)?a:b);
    document.getElementById('statBest').textContent=marginPct(best).toFixed(1)+'%';
  }
}

function updateTime(){
  const now=new Date();
  document.getElementById('lastUpdated').textContent='Last updated: '+now.toLocaleTimeString();
  document.getElementById('statRefresh').textContent=countdown+'s';
}

function applyFilters(){
  const q=(document.getElementById('search').value||'').toLowerCase();
  const col=document.getElementById('sortBy').value;
  sortCol=col;
  let filtered=q?allItems.filter(i=>i.name.toLowerCase().includes(q)):[...allItems];
  filtered.sort((a,b)=>{
    let va,vb;
    if(col==='margin'){va=marginPct(a);vb=marginPct(b)}
    else if(col==='profit'){va=a.profit||0;vb=b.profit||0}
    else{va=a[col]||0;vb=b[col]||0}
    return sortDir==='desc'?vb-va:va-vb;
  });
  document.getElementById('filterCount').textContent=filtered.length+'/'+allItems.length+' items';
  renderTable(filtered);
}

function toggleDirection(){
  sortDir=sortDir==='desc'?'asc':'desc';
  document.getElementById('btnDir').textContent=sortDir==='desc'?'Desc':'Asc';
  applyFilters();
}

function toggleTrades(){
  showTrades=!showTrades;
  document.getElementById('btnTrades').classList.toggle('active',showTrades);
  if(showTrades) renderTrades();
  else applyFilters();
}

async function renderTrades(){
  const panel=document.getElementById('tablePanel');
  const detail=document.getElementById('detailPanel');
  panel.innerHTML='<div class="loading"><span class="spinner"></span>Loading trades...</div>';
  try{
    const [pr,tr]=await Promise.all([fetch('/api/pnl'),fetch('/api/trades')]);
    if(!pr.ok||!tr.ok)throw new Error('trades API failed');
    const pnl=await pr.json();
    const trades=(await tr.json()).trades||[];
    const h='<div class="item-name" style="margin-bottom:12px">P&L Summary</div>'+
      '<div class="metric-grid">'+
      metric('Total Profit',format(pnl.total_profit||0)+' gp',(pnl.total_profit||0)>0?'green':'red')+
      metric('ROI',(pnl.roi_pct||0).toFixed(2)+'%',(pnl.roi_pct||0)>0?'green':'')+
      metric('Win Rate',(pnl.win_rate||0).toFixed(1)+'%','gold')+
      metric('Trades',format(pnl.trade_count||0),'')+
      metric('Tax Paid',format(pnl.total_tax_paid||0)+' gp','')+
      metric('Cost Basis',format(pnl.total_cost_basis||0)+' gp','')+
      metric('Best','<span class="val green">'+format(pnl.best_trade||0)+'</span>','')+
      metric('Worst','<span class="val red">'+format(pnl.worst_trade||0)+'</span>','')+
      metric('Items',format(pnl.items_traded||0),'')+
      metric('Active GP/hr',format(pnl.active_gp_per_hour||0)+' gp','gold')+
      '</div>';
    detail.innerHTML=h;
    if(!trades.length){
      panel.innerHTML='<div class="loading">No trades logged</div>';
      return;
    }
    let th='<table><thead><tr>';
    th+='<th>Date</th><th>Item</th><th>Qty</th><th>Buy</th><th>Sell</th><th>Profit</th>';
    th+='</tr></thead><tbody>';
    trades.slice(0,50).forEach(t=>{
      const p=t.profit||0;
      th+='<tr><td>'+escHtml(String(t.timestamp||'').slice(0,16))+'</td>';
      th+='<td class="name">'+escHtml(t.name||'')+'</td>';
      th+='<td>'+format(t.qty||0)+'</td>';
      th+='<td>'+format(t.buy_price||0)+'</td>';
      th+='<td>'+format(t.sell_price||0)+'</td>';
      th+='<td class="margin '+(p>0?'pos':p<0?'neg':'neutral')+'">'+format(p)+'</td></tr>';
    });
    th+='</tbody></table>';
    panel.innerHTML=th;
  }catch(e){
    panel.innerHTML='<div class="loading">Error loading trades: '+escHtml(e.message)+'</div>';
  }
}

function renderTable(items){
  const panel=document.getElementById('tablePanel');
  if(!items.length){panel.innerHTML='<div class="loading">No items match</div>';return}
  let h='<table><thead><tr>';
  h+='<th class="rank">#</th><th>Item</th><th>Buy</th><th>Sell</th><th>Margin</th><th>Profit</th><th>RS</th><th>GP/hr</th><th>Vol</th><th>Limit</th>';
  h+='</tr></thead><tbody>';
  items.forEach((item,i)=>{
    const mp=marginPct(item);
    const cls=mp>2?'pos':mp<-2?'neg':'neutral';
    const sel=item.id===selectedId?' selected':'';
    h+='<tr class="'+sel+'" data-id="'+item.id+'" onclick="selectItem('+item.id+')">';
    h+='<td class="rank">'+(i+1)+'</td>';
    h+='<td class="name">'+escHtml(item.name)+'</td>';
    h+='<td>'+format(item.buy_price||0)+'</td>';
    h+='<td>'+format(item.sell_price||0)+'</td>';
    h+='<td class="margin '+cls+'">'+mp.toFixed(1)+'%</td>';
    h+='<td>'+format(item.profit||0)+'</td>';
    h+='<td>'+(item.rs_score||0).toFixed(0)+'</td>';
    h+='<td>'+format(item.gp_per_hour||0)+'</td>';
    h+='<td>'+format(item.volume||0)+'</td>';
    h+='<td>'+format(item.buy_limit||0)+'</td>';
    h+='</tr>';
  });
  h+='</tbody></table>';
  panel.innerHTML=h;
}

function selectItem(id){
  selectedId=id;
  const item=allItems.find(i=>i.id===id);
  if(!item)return;
  document.querySelectorAll('tr.selected').forEach(r=>r.classList.remove('selected'));
  const row=document.querySelector('tr[data-id="'+id+'"]');
  if(row)row.classList.add('selected');
  const mp=marginPct(item);
  const cls=mp>2?'green':mp<-2?'red':'gold';
  document.getElementById('detailPanel').innerHTML=''+
    '<div class="item-name">'+escHtml(item.name)+'</div>'+
    '<div class="metric-grid">'+
    metric('Buy Price',format(item.buy_price)+' gp','')+
    metric('Sell Price',format(item.sell_price)+' gp','')+
    metric('Margin %','<span class="val '+cls+'">'+mp.toFixed(1)+'%</span>','')+
    metric('Profit',format(item.profit||0)+' gp',(item.profit||0)>0?'green':'')+
    metric('GP / Hour',format(item.gp_per_hour||0)+' gp','gold')+
    metric('RS Score',(item.rs_score||0).toFixed(0),'gold')+
    metric('Volume (5m)',format(item.volume),'')+
    metric('Buy Limit',format(item.buy_limit),'')+
    metric('Members','<span class="val '+(item.members?'gold':'dim')+'">'+(item.members?'Yes':'No')+'</span>','')+
    '</div>';
}

function reselectItem(){
  if(selectedId!=null)selectItem(selectedId);
}

function metric(label,val,valClass){
  const vc=valClass?' '+valClass:'';
  return '<div class="metric"><div class="lbl">'+label+'</div><div class="val'+vc+'">'+val+'</div></div>';
}

function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

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
