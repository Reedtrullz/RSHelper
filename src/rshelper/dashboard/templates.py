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
.chart-title{font-size:13px;font-weight:700;color:var(--gold);margin:20px 0 8px}
.table-panel canvas{width:100%;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)}
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
  <button id="btnProgress" onclick="toggleProgress()">Progression</button>
  <button id="btnPaper" onclick="togglePaper()">Paper Trading</button>
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
let showTrades=false,showProgress=false,showPaper=false;
let paperOnly=false;
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
    if(showTrades)renderTrades();
    else if(showProgress)renderProgress();
    else if(showPaper)renderPaper();
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
  setView(showTrades?'none':'trades');
}

function toggleProgress(){
  setView(showProgress?'none':'progress');
}
function togglePaper(){
  setView(showPaper?'none':'paper');
}
function setView(name){
  showTrades=(name==='trades');
  showProgress=(name==='progress');
  showPaper=(name==='paper');
  document.getElementById('btnTrades').classList.toggle('active',showTrades);
  document.getElementById('btnProgress').classList.toggle('active',showProgress);
  document.getElementById('btnPaper').classList.toggle('active',showPaper);
  if(showTrades)renderTrades();
  else if(showProgress)renderProgress();
  else if(showPaper)renderPaper();
  else{selectedId=null;applyFilters()}
}
async function renderProgress(){
  const panel=document.getElementById('tablePanel');
  const detail=document.getElementById('detailPanel');
  panel.innerHTML='<div class="loading"><span class="spinner"></span>Loading progression...</div>';
  try{
    const r=await fetch('/api/history?paper='+(paperOnly?1:0));
    if(!r.ok)throw new Error('history API failed');
    const h=await r.json();
    const s=h.summary||{};
    detail.innerHTML='<div class="item-name" style="margin-bottom:12px">Progression</div>'+
      '<div class="metric-grid">'+
      metric('Total P&L',format(s.total_profit||0)+' gp',(s.total_profit||0)>0?'green':'red')+
      metric('Win Rate',(s.win_rate||0).toFixed(1)+'%','gold')+
      metric('ROI',(s.roi_pct||0).toFixed(2)+'%',(s.roi_pct||0)>0?'green':'')+
      metric('Trades',format(s.trade_count||0),'')+
      metric('Items',format(s.items_traded||0),'')+
      metric('Active Days',format(s.active_days||0),'')+
      '</div>';
    const buckets=h.buckets||[];
    let html=paperToggleHtml();
    if(buckets.length<2){
      html+='<div class="loading">Not enough days yet — log paper trades across a few days and tune config.toml between them.</div>';
    }else{
      html+='<h3 class="chart-title">Cumulative P&L with tuning changes</h3><canvas id="cumChart" height="220"></canvas>';
      html+='<h3 class="chart-title">Daily trades and win rate</h3><canvas id="dailyChart" height="220"></canvas>';
    }
    html+=historyTablesHtml(h);
    panel.innerHTML=html;
    if(buckets.length>=2){
      drawCumulative(document.getElementById('cumChart'),buckets);
      drawDaily(document.getElementById('dailyChart'),buckets);
    }
  }catch(e){
    panel.innerHTML='<div class="loading">Error loading progression: '+escHtml(e.message)+'</div>';
  }
}
function drawCumulative(cv,buckets){
  const dpr=window.devicePixelRatio||1,w=cv.clientWidth,h=220;
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
  buckets.forEach((b,i)=>{
    ctx.fillText(b.date.slice(5),x(i)-12,h-8);
  });
}
function drawDaily(cv,buckets){
  const dpr=window.devicePixelRatio||1,w=cv.clientWidth,h=220;
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

function paperToggleHtml(){
  return '<div style="display:flex;gap:8px;align-items:center;margin:14px 0">'+
    '<span style="font-size:12px;color:var(--text-dim)">Scope:</span>'+
    '<button class="'+(paperOnly?'active':'')+'" onclick="setPaperOnly(true)">Paper only</button>'+
    '<button class="'+(paperOnly?'':'active')+'" onclick="setPaperOnly(false)">All trades</button></div>';
}
function setPaperOnly(v){
  paperOnly=v;
  renderProgress();
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
        '<td>'+i.roi_pct.toFixed(2)+'</td><td>'+i.win_rate.toFixed(1)+'</td></tr>';
    });
    html+='</tbody></table>';
  }
  return html;
}

async function renderPaper(){
  const panel=document.getElementById('tablePanel');
  const detail=document.getElementById('detailPanel');
  panel.innerHTML='<div class="loading"><span class="spinner"></span>Loading paper trading...</div>';
  detail.innerHTML='<div class="loading"><span class="spinner"></span></div>';
  try{
    const [pr,tr,hr]=await Promise.all([
      fetch('/api/pnl'),fetch('/api/trades'),fetch('/api/history?paper=0')
    ]);
    if(!pr.ok||!tr.ok||!hr.ok)throw new Error('paper API failed');
    const pnl=await pr.json();
    const trades=(await tr.json()).trades||[];
    const h=await hr.json();
    const s=h.summary||{};
    detail.innerHTML='<div class="item-name" style="margin-bottom:12px">Paper Trading</div>'+
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
      '</div>';
    let html='';
    const traded=(h.items||[]).filter(i=>i.trade_count>0);
    html+='<h3 class="chart-title">Current status — live market on traded items</h3>';
    if(!traded.length){
      html+='<div class="loading">No trades yet — log one with trade paper &lt;item&gt; or the Trades tab.</div>';
    }else{
      let prices={};
      try{
        const ids=traded.map(i=>i.item_id).join(',');
        const pr=await fetch('/api/prices?ids='+ids);
        if(pr.ok)prices=(await pr.json()).prices||{};
      }catch(e){}
      html+='<table><thead><tr><th>Item</th><th>Trades</th><th>Qty</th><th>Realized P&L</th><th>Live Buy</th><th>Live Sell</th><th>Live Margin</th></tr></thead><tbody>';
      traded.forEach(i=>{
        const cur=prices[String(i.item_id)];
        const live=cur&&cur.usable;
        const liveBuy=live?cur.buy:null;
        const liveSell=live?cur.sell:null;
        const mp=(liveBuy>0)?((liveSell-liveBuy)/liveBuy*100):null;
        html+='<tr><td class="name">'+escHtml(i.name)+'</td><td>'+format(i.trade_count)+'</td><td>'+format(i.qty)+'</td>'+
          '<td class="margin '+(i.profit>0?'pos':i.profit<0?'neg':'neutral')+'">'+format(i.profit)+'</td>'+
          (live?'<td>'+format(liveBuy)+'</td><td>'+format(liveSell)+'</td>'+
            '<td class="margin '+(mp>2?'pos':mp<-2?'neg':'neutral')+'">'+mp.toFixed(1)+'%</td>'
            :'<td>-</td><td>-</td><td>-</td>')+
          '</tr>';
      });
      html+='</tbody></table>';
    }
    html+='<h3 class="chart-title">Recent trades</h3>';
    if(!trades.length){
      html+='<div class="loading">No trades logged.</div>';
    }else{
      html+='<table><thead><tr><th>Date</th><th>Item</th><th>Qty</th><th>Buy</th><th>Sell</th><th>Profit</th></tr></thead><tbody>';
      trades.slice(0,15).forEach(t=>{
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
    panel.innerHTML=html;
    if(buckets.length>=2){
      drawCumulative(document.getElementById('paperCum'),buckets);
      drawDaily(document.getElementById('paperDaily'),buckets);
    }
  }catch(e){
    panel.innerHTML='<div class="loading">Error loading paper trading: '+escHtml(e.message)+'</div>';
  }
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
