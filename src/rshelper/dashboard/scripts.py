"""Dashboard client-side JavaScript, split into named constants.

Kept separate from templates.py (which holds the HTML shell + CSS) so the
~1,100 lines of JS are navigable. The bundle is inlined into INDEX_HTML in
dependency order: core -> charts -> views.
"""

SCRIPT_CORE = r"""
const refreshSecs=60;
let allItems=[],signalsMap={},meta={},watchIds=new Set();
let selectedId=null,view='market';
let sortKeys=[{col:'gp_per_hour',dir:'desc'}];
let chip='all',density='normal',strategy='';
let viewRows=[];
let geData=null,bankData=null,alertsData={alerts:[],unread:0},alchItems=[];
let sparkSeq=0;
let countdown=refreshSecs;
let sseOk=false,sseLastEvent=Date.now();

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
function fmtAge(sec){
  if(sec==null)return '-';
  if(sec<60)return Math.round(sec)+'s';
  if(sec<3600)return Math.round(sec/60)+'m';
  return (sec/3600).toFixed(1)+'h';
}
function alertBadgeHtml(){
  const n=alertsData.unread||0;
  return '<button class="icon-btn bell" id="btnBell" aria-label="Alerts" title="Alerts" onclick="toggleAlerts()">&#128276;'+
    (n?'<span class="bell-badge">'+(n>99?'99+':n)+'</span>':'')+'</button>';
}
function toggleAlerts(){
  const dd=document.getElementById('alertDropdown');
  if(dd){dd.remove();return}
  const div=document.createElement('div');
  div.id='alertDropdown';
  div.className='alert-dropdown';
  const items=(alertsData.alerts||[]).slice(0,15);
  let h='<div class="alert-dd-head"><span>Alerts</span>'+
    '<button class="alert-dd-clear" onclick="markAllRead()">Mark all read</button></div>';
  if(!items.length)h+='<div class="loading">No alerts yet.</div>';
  h+='<div class="alert-dd-list">';
  items.forEach(a=>{
    h+='<div class="alert-dd-item'+(a.read?' read':'')+'" title="'+escHtml(a.message)+'">'+
      '<span class="alert-sev sev-'+escHtml(a.severity)+'">'+escHtml(a.severity)+'</span> '+
      '<span class="alert-type">'+escHtml(a.type)+'</span> '+
      '<span class="alert-title">'+escHtml(a.title)+'</span> '+
      '<span class="alert-msg">'+escHtml(a.message)+'</span> '+
      '<span class="alert-ts">'+new Date(a.ts*1000).toLocaleTimeString()+'</span></div>';
  });
  h+='</div>';
  div.innerHTML=h;
  document.body.appendChild(div);
}
async function markAllRead(){
  try{
    const r=await fetch('/api/alerts/read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({all:true})});
    if(r.ok){alertsData.unread=0;(alertsData.alerts||[]).forEach(a=>a.read=true);}
  }catch(e){}
  const dd=document.getElementById('alertDropdown');
  if(dd){dd.remove();toggleAlerts();}
  renderTopbar();
}
function updateTopbarBell(){
  const bell=document.getElementById('bellSlot');
  if(bell)bell.innerHTML=alertBadgeHtml();
}
function renderTopbar(){
  const stats=document.getElementById('statsSlot');
  if(!stats)return;
  stats.innerHTML=
    '<div class="stat"><div class="val dim" id="statCount">'+format((allItems||[]).length)+'</div><div class="lbl">Flips</div></div>'+
    '<div class="stat"><div class="val green" id="statBest">'+bestMargin()+'</div><div class="lbl">Best Margin</div></div>'+
    '<div class="stat"><div class="val gold" id="statRefresh">'+countdown+'s</div><div class="lbl">Refresh</div></div>'+
    '<span id="bellSlot">'+alertBadgeHtml()+'</span>'+
    '<button class="icon-btn" id="btnRefresh" onclick="fetchData()" aria-label="Refresh now" title="Refresh now">&#x21bb;</button>';
  updateTopbarBell();
  document.getElementById('search')||null;
}
function bestMargin(){
  let best=0;
  (allItems||[]).forEach(i=>{const m=marginPct(i);if(m>best)best=m});
  return best>0?best.toFixed(1)+'%':'-';
}
function updateBadges(){
  document.getElementById('badgeMarket').textContent=meta.flips||0;
  document.getElementById('badgePaper').textContent=meta.trades||0;
  document.getElementById('badgeSignals').textContent=meta.signals||0;
  document.getElementById('badgeWatchlist').textContent=meta.watchlist||0;
  document.getElementById('badgeOverview').textContent=alertsData.unread||0;
  updateTopbarBell();
}
function updateFooter(){
  const src=meta.source||'none';
  const el=document.getElementById('sourceBadge');
  el.textContent=src==='ge_tracker'?'GE Tracker fallback':src==='wiki'?'OSRS Wiki':'-';
  el.className='source-badge '+(src==='wiki'?'wiki':src==='ge_tracker'?'tracker':'none');
  if(meta.last_fetch){
    document.getElementById('lastUpdated').textContent='Last updated: '+new Date(meta.last_fetch*1000).toLocaleTimeString();
  }
  const kbd=document.getElementById('kbdHint');
  if(src==='ge_tracker')kbd.textContent='signals limited on fallback';
  else if(!sseOk)kbd.textContent='polling '+refreshSecs+'s';
  else kbd.textContent='live via SSE';
}
function subscribeSSE(){
  try{
    const es=new EventSource('/api/events');
    es.addEventListener('refresh',()=>{sseLastEvent=Date.now();fetchData();});
    es.addEventListener('alert',(ev)=>{
      sseLastEvent=Date.now();
      try{const d=JSON.parse(ev.data||'{}');if(d&&d.alert){alertsData.unread=(alertsData.unread||0)+1;updateTopbarBell();}}
      catch(e){}
    });
    es.onopen=()=>{sseOk=true;updateFooter();};
    es.onerror=()=>{sseOk=false;updateFooter();};
  }catch(e){sseOk=false;}
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
    setStatus('Error: '+e.message,true);
  }
}
function setStatus(msg,isErr){
  document.getElementById('statusText').textContent=msg;
  document.getElementById('statusDot').className=isErr?'dot err':'dot live';
}
function sigBadge(item){
  const s=signalsMap[item.id];
  if(!s)return '<span class="dim">-</span>';
  return '<span class="sig-badge sig-'+escHtml(s.type)+'" title="'+escHtml(s.message)+'">'+escHtml(s.type)+'</span>';
}
function setView(v){
  view=v;
  const names=['market','paper','signals','watchlist','ge','bank','process','overview','activity'];
  names.forEach(n=>{
    const btn=document.getElementById('btn'+n.charAt(0).toUpperCase()+n.slice(1));
    if(btn)btn.classList.toggle('active',v===n);
  });
  if(v==='market')renderMarket();
  else if(v==='paper')renderPaper();
  else if(v==='signals')renderSignals();
  else if(v==='watchlist')renderWatchlist();
  else if(v==='ge')renderGE();
  else if(v==='bank')renderBank();
  else if(v==='process')renderProcess();
  else if(v==='overview')renderOverview();
  else if(v==='activity')renderActivity();
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
    setStatus('Enter an item and a positive quantity',true);
    return;
  }
  try{
    const r=await fetch('/api/paper',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action,item,qty})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.message||('HTTP '+r.status));
    setStatus(action==='open'?'Position opened':'Paper trade logged',false);
    fetchData();
  }catch(e){
    setStatus('Error: '+e.message,true);
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
    setStatus('Connected',false);
    renderTopbar();
    updateBadges();
    updateFooter();
    if(view==='market')renderMarket();
    else if(view==='paper')renderPaper();
    else if(view==='signals')renderSignals();
    else if(view==='watchlist')renderWatchlist();
    else if(view==='ge')renderGE();
    else if(view==='bank')renderBank();
    else if(view==='process')renderProcess();
    else if(view==='overview')renderOverview();
    else if(view==='activity')renderActivity();
    if(view==='market'&&selectedId!=null)renderDetail(selectedId);
    countdown=refreshSecs;
  }catch(e){
    setStatus('Error: '+e.message,true);
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
function tick(){
  countdown--;
  if(countdown<=0){fetchData();countdown=refreshSecs}
  const el=document.getElementById('statRefresh');
  if(el)el.textContent=countdown+'s';
  if(!sseOk&&Date.now()-sseLastEvent>90000){sseOk=true;sseLastEvent=Date.now();subscribeSSE();}
}
function viewbarHtml(){
  if(view==='market'){
    return '<div class="viewbar"><span class="title">Market scan</span>'+
      '<button class="chip'+(chip==='all'?' active':'')+'" data-chip="all" onclick="setChip(\'all\')">All</button>'+
      '<button class="chip'+(chip==='m2'?' active':'')+'" data-chip="m2" onclick="setChip(\'m2\')">Margin &ge;2%</button>'+
      '<button class="chip'+(chip==='m10'?' active':'')+'" data-chip="m10" onclick="setChip(\'m10\')">Margin &ge;10%</button>'+
      '<button class="chip'+(chip==='v100'?' active':'')+'" data-chip="v100" onclick="setChip(\'v100\')">Vol &ge;100</button>'+
      '<button class="toggle-btn'+(marketMode==='flips'?' active':'')+'" onclick="setMarketMode(\'flips\')">Flips</button>'+
      '<button class="toggle-btn'+(marketMode==='alch'?' active':'')+'" onclick="setMarketMode(\'alch\')">Alchemy</button>'+
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
    return '<div class="viewbar"><span class="title">Grand Exchange</span></div>';
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
  if(view==='overview'){
    return '<div class="viewbar"><span class="title">Overview</span></div>';
  }
  if(view==='activity'){
    return '<div class="viewbar"><span class="title">Activity</span>'+
      '<button class="toggle-btn'+(strategy===''?' active':'')+'" data-strategy="" onclick="setStrategy(\'\')">All</button>'+
      '<button class="toggle-btn'+(strategy==='auto'?' active':'')+'" data-strategy="auto" onclick="setStrategy(\'auto\')">Auto</button>'+
      '<button class="toggle-btn'+(strategy==='manual'?' active':'')+'" data-strategy="manual" onclick="setStrategy(\'manual\')">Manual</button></div>';
  }
  return '<div class="viewbar"><span class="title">'+view.charAt(0).toUpperCase()+view.slice(1)+'</span></div>';
}
"""

SCRIPT_CHARTS = r"""
function drawSpark(id){
  const cv=document.getElementById('spark');
  if(!cv)return;
  const seq=++sparkSeq;
  let pts=[];
  (async()=>{
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
  })();
}
function drawMargin(id){
  const cv=document.getElementById('marginChart');
  if(!cv)return;
  const seq=++sparkSeq;
  (async()=>{
    let pts=[];
    try{
      const r=await fetch('/api/timeseries?id='+id+'&step=1h&points=192');
      pts=(await r.json()).points||[];
    }catch(e){}
    if(pts.length<2){
      if(seq!==sparkSeq)return;
      cv.style.display='none';
      const note=document.createElement('div');
      note.className='loading';
      note.textContent='No hourly history for a margin chart.';
      cv.parentNode.appendChild(note);
      return;
    }
    const margins=pts.map(p=>((p.avgLow||0)-(p.avgHigh||0))-taxOf(p.avgLow||0));
    const draw=()=>{
      if(seq!==sparkSeq)return;
      const dpr=window.devicePixelRatio||1,w=cv.clientWidth;
      if(!w){requestAnimationFrame(draw);return}
      const h=120;
      cv.width=w*dpr;cv.height=h*dpr;cv.style.height=h+'px';
      const ctx=cv.getContext('2d');ctx.scale(dpr,dpr);
      const lo=Math.min(0,...margins),hi=Math.max(0,...margins),span=Math.max(hi-lo,1);
      const x=i=>i/(margins.length-1)*w;
      const y=v=>h-6-(h-14)*(v-lo)/span;
      ctx.strokeStyle='#1e293b';ctx.fillStyle='#94a3b8';ctx.font='10px system-ui';
      for(let g=0;g<=3;g++){
        const v=lo+span*g/3,gy=y(v);
        ctx.beginPath();ctx.moveTo(0,gy);ctx.lineTo(w,gy);ctx.stroke();
        ctx.fillText(Math.round(v).toLocaleString(),3,gy-2);
      }
      ctx.strokeStyle='#eab308';ctx.lineWidth=1.5;ctx.beginPath();
      margins.forEach((v,i)=>{i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v))});
      ctx.stroke();ctx.lineWidth=1;
    };
    draw();
  })();
}
function drawCumulative(cv,buckets){
  if(!cv||!buckets||buckets.length<2)return;
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
  if(!cv||!buckets||buckets.length<2)return;
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
"""

SCRIPT_VIEWS = r"""
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
    '<div class="chart-title">Price history (8h, 5m)</div><canvas id="spark" height="84"></canvas>'+
    '<div class="chart-title">Margin history (24h, 1h)</div><canvas id="marginChart" height="120"></canvas>';
  drawSpark(id);
  drawMargin(id);
}
function watchDetail(id){
  const w=viewRows.find(r=>r.id===id);
  if(!w)return null;
  if(!w.usable)return {id:w.id,name:w.name,unusable:true,reason:w.reason};
  return {id:w.id,name:w.name,buy_price:w.buy,sell_price:w.sell,volume:0,
          buy_limit:0,alch_value:0,members:false,profit:w.sell-w.buy-taxOf(w.sell),gp_per_hour:0,rs_score:0};
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
let marketMode='flips';
function setMarketMode(m){
  marketMode=m;
  renderMarket();
}
function renderMarket(){
  const bar=document.getElementById('viewbar');
  bar.innerHTML=viewbarHtml();
  if(density==='dense')document.getElementById('listBody').classList.add('dense');
  const body=document.getElementById('listBody');
  if(marketMode==='alch'){
    renderAlch();
    return;
  }
  const rows=marketRows();
  viewRows=rows;
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
async function renderAlch(){
  const body=document.getElementById('listBody');
  body.innerHTML='<div class="loading"><span class="spinner"></span>Loading alchemy...</div>';
  let items=[];
  try{
    const r=await fetch('/api/alch');
    if(!r.ok)throw new Error('alch api');
    items=(await r.json()).items||[];
  }catch(e){
    body.innerHTML='<div class="loading">Error loading alchemy: '+escHtml(e.message)+'</div>';
    return;
  }
  viewRows=items;
  if(!items.length){
    body.innerHTML='<div class="loading">No profitable alchs right now.</div>';
    renderContextEmpty();
    return;
  }
  let h='<table><thead><tr><th>Item</th><th>Buy</th><th>Alch</th><th>Profit</th><th>GP/hr</th><th>Limit</th><th>Vol</th></tr></thead><tbody>';
  items.forEach(it=>{
    const sel=it.id===selectedId?' selected':'';
    h+='<tr class="'+sel+'" data-id="'+it.id+'" onclick="selectId('+it.id+',false)">'+
      '<td class="name">'+escHtml(it.name)+'</td>'+
      '<td>'+format(it.buy_price)+'</td><td>'+format(it.alch_value)+'</td>'+
      '<td class="margin pos">'+format(it.profit)+'</td>'+
      '<td>'+format(it.gp_per_hour)+'</td>'+
      '<td>'+format(it.buy_limit)+'</td>'+
      '<td>'+gp(it.volume)+'</td></tr>';
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
  let h='<table><thead><tr><th></th><th>Item</th><th>Buy</th><th>Sell</th><th>Margin</th><th>Profit</th><th>Alerts</th><th></th></tr></thead><tbody>';
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
      '<td class="dim">'+escHtml(alert)+'</td>'+
      '<td><button class="alert-edit" onclick="editWatchAlerts('+i.id+',event)" title="Set alert thresholds">&#9998;</button></td></tr>';
  });
  h+='</tbody></table>';
  body.innerHTML=h;
  if(selectedId!=null)renderDetail(selectedId);
  else renderContextEmpty();
}
function editWatchAlerts(id,ev){
  if(ev)ev.stopPropagation();
  const item=viewRows.find(r=>r.id===id);
  if(!item)return;
  const above=item.alert_above!=null?item.alert_above:'';
  const below=item.alert_below!=null?item.alert_below:'';
  const overlay=document.createElement('div');
  overlay.className='ge-history-overlay';
  overlay.innerHTML='<div class="ge-history-panel"><div class="item-name" style="margin-bottom:12px">Alert thresholds — '+escHtml(item.name)+'</div>'+
    '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">'+
    '<label style="font-size:12px;color:var(--text-dim)">Above (gp): <input id="wlAbove" type="number" min="0" style="width:110px" value="'+above+'"></label>'+
    '<label style="font-size:12px;color:var(--text-dim)">Below (gp): <input id="wlBelow" type="number" min="0" style="width:110px" value="'+below+'"></label>'+
    '</div>'+
    '<div style="text-align:right;margin-top:14px">'+
    '<button class="act-btn" style="margin-right:8px" onclick="saveWatchAlerts('+id+')">Save</button>'+
    '<button class="act-btn" onclick="closeGEHistory(this)">Cancel</button></div></div>';
  document.body.appendChild(overlay);
}
async function saveWatchAlerts(id){
  const aboveRaw=document.getElementById('wlAbove').value;
  const belowRaw=document.getElementById('wlBelow').value;
  const alert_above=aboveRaw===''?null:parseInt(aboveRaw,10);
  const alert_below=belowRaw===''?null:parseInt(belowRaw,10);
  try{
    const r=await fetch('/api/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'alerts',item_id:id,alert_above,alert_below})});
    if(!r.ok)throw new Error('save failed');
    document.querySelectorAll('.ge-history-overlay').forEach(o=>o.remove());
    renderWatchlist();
  }catch(e){
    setStatus('Error: '+e.message,true);
  }
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
      h+='<div class="loading">No active offers — open a position with <code>trade open &lt;item&gt;</code> or the Trading tab.</div>';
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
    setStatus('Collected '+d.name+': '+(d.profit>0?'+':'')+format(d.profit)+' gp',false);
    fetchData();
  }catch(e){
    setStatus('Error: '+e.message,true);
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
      h='<div class="loading">The bank is empty — open positions with <code>trade open &lt;item&gt;</code> or the Trading tab.</div>';
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
function traderNoticeHtml(trader){
  if(!trader.running){
    const last=trader.last_cycle_iso;
    const stale=last?'<div class="dim" style="margin-top:4px">Last known cycle: '+escHtml(String(last).slice(0,16))+' (state may be stale)</div>':'';
    return '<div class="notice" style="border-color:var(--border);color:var(--text-dim);background:var(--surface)">'+
      'Auto-trader not running'+(trader.local===false?' on this machine (synced state)':'')+
      ' — start it with <code>rshelper auto-trade</code>.'+stale+'</div>';
  }
  const last=trader.last_result||{};
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
  const buckets={quick:{n:0,w:0},medium:{n:0,w:0},long:{n:0,w:0}};
  autoTrades.forEach(t=>{
    const hh=t.hold_minutes||0;
    const b=hh<=5?buckets.quick:hh<=60?buckets.medium:buckets.long;
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
function traderControlHtml(trader){
  if(!meta.control)return '';
  const running=!!trader.running;
  return '<div style="display:flex;gap:8px;margin-top:8px">'+
    (running
      ?'<button class="act-btn" onclick="traderControl(\'stop\')" style="background:#7f1d1d;border-color:#f87171;color:#f87171">Stop auto-trader</button>'
      :'<button class="act-btn" onclick="traderControl(\'start\')">Start auto-trader</button>')+
    '</div>';
}
function monitorControlHtml(mon){
  if(!meta.control)return '';
  const running=!!mon.running;
  return '<div style="display:flex;gap:8px;margin-top:8px">'+
    (running
      ?'<button class="act-btn" onclick="monitorControl(\'stop\')" style="background:#7f1d1d;border-color:#f87171;color:#f87171">Stop monitor</button>'
      :'<button class="act-btn" onclick="monitorControl(\'start\')">Start monitor</button>')+
    '</div>';
}
async function traderControl(action){
  try{
    const r=await fetch('/api/trader',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.message||('HTTP '+r.status));
    setStatus(action==='start'?'Auto-trader starting...':'Auto-trader stop requested',false);
    setTimeout(fetchData,1500);
  }catch(e){setStatus('Error: '+e.message,true);}
}
async function monitorControl(action){
  try{
    const r=await fetch('/api/monitor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.message||('HTTP '+r.status));
    setStatus(action==='start'?'Monitor starting...':'Monitor stop requested',false);
    setTimeout(fetchData,1500);
  }catch(e){setStatus('Error: '+e.message,true);}
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
    html+=traderControlHtml(trader);
    html+=traderPerfHtml(trader,trades);
    html+='<h3 class="chart-title">Open positions</h3>';
    if(!openPos.length){
      html+='<div class="loading">No open positions — open one with <code>trade open &lt;item&gt;</code>.</div>';
    }else{
      html+='<table><thead><tr><th>Item</th><th>Qty</th><th>Buy</th><th>Current</th><th>Unrealized</th><th>Opened</th><th></th></tr></thead><tbody>';
      openPos.forEach(p=>{
        const unreal=p.unrealized;
        const cur=p.usable?p.current:null;
        const closeBtn=p.auto?'<span class="dim" title="Auto-trader closes this">Auto</span>'
          :'<button class="act-btn" style="padding:2px 8px" onclick="closePosition('+p.id+',event)">Close</button>';
        html+='<tr><td class="name">'+escHtml(p.name)+'</td><td>'+format(p.qty)+'</td>'+
          '<td>'+format(p.buy_price)+'</td>'+
          (cur!=null?'<td>'+format(cur)+'</td>':'<td class="dim">-</td>')+
          '<td class="margin '+(unreal!=null?(unreal>0?'pos':unreal<0?'neg':'neutral'):'dim')+'">'+
          (unreal!=null?format(unreal):'-')+'</td>'+
          '<td>'+escHtml(String(p.opened_at||'').slice(0,10))+'</td>'+
          '<td>'+closeBtn+'</td></tr>';
      });
      html+='</tbody></table>';
    }
    const traded=(h.items||[]).filter(i=>i.trade_count>0);
    html+='<h3 class="chart-title">Current status — live market on traded items</h3>';
    if(!traded.length){
      html+='<div class="loading">No trades yet — open one with <code>trade open &lt;item&gt;</code> or <code>trade paper &lt;item&gt;</code>.</div>';
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
async function closePosition(positionId,ev){
  if(ev)ev.stopPropagation();
  if(!confirm('Close this position at the current market price?'))return;
  try{
    const r=await fetch('/api/positions',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'close',position_id:positionId})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.message||('HTTP '+r.status));
    setStatus('Closed '+d.name+': '+(d.profit>0?'+':'')+format(d.profit)+' gp',false);
    fetchData();
  }catch(e){setStatus('Error: '+e.message,true);}
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
async function renderOverview(){
  const bar=document.getElementById('viewbar');
  bar.innerHTML=viewbarHtml();
  const body=document.getElementById('listBody');
  const context=document.getElementById('contextPanel');
  body.innerHTML='<div class="loading"><span class="spinner"></span>Loading overview...</div>';
  context.innerHTML='<div class="loading"><span class="spinner"></span></div>';
  try{
    const [pr,posr,trr,mr,hr,alr]=await Promise.all([
      fetch('/api/pnl'),fetch('/api/positions'),fetch('/api/trader'),fetch('/api/monitor'),
      fetch('/api/history?paper=1'),fetch('/api/alerts?limit=15')
    ]);
    const pnl=await pr.json();
    const pos=(await posr.json())||{positions:[]};
    const trader=(await trr.json())||{running:false};
    const mon=(await mr.json())||{running:false};
    const h=await hr.json();
    const al=await alr.json();
    alertsData={alerts:al.alerts||[],unread:al.unread||0};
    const buckets=h.buckets||[];
    context.innerHTML='<div class="item-name" style="margin-bottom:12px">Overview</div>'+
      '<div class="metric-grid">'+
      metric('Realized P&L',format(pnl.total_profit||0)+' gp',(pnl.total_profit||0)>0?'green':(pnl.total_profit||0)<0?'red':'')+
      metric('Unrealized',format(pos.unrealized||0)+' gp',(pos.unrealized||0)>0?'green':(pos.unrealized||0)<0?'red':'')+
      metric('Open Exposure',format((pos.positions||[]).reduce((a,p)=>a+(p.buy_price||0)*(p.qty||0),0))+' gp','')+
      metric('ROI',(pnl.roi_pct||0).toFixed(2)+'%',(pnl.roi_pct||0)>0?'green':'')+
      metric('Win Rate',(pnl.win_rate||0).toFixed(1)+'%','gold')+
      metric('Active GP/hr',format(pnl.active_gp_per_hour||0)+' gp','gold')+
      metric('Trades',format(pnl.trade_count||0),'')+
      metric('Unread Alerts',format(al.unread||0),al.unread?'gold':'')+
      '</div>'+
      '<div class="notice" style="margin-top:4px">'+(trader.running?'<span class="pos">&#9679; Trader running</span>':'<span class="neg">&#9679; Trader not running</span>')+
      (trader.running?' — '+format(trader.journal_realized_pnl||trader.realized_pnl||0)+' gp realized':'')+
      ' &nbsp; '+(mon.running?'<span class="pos">&#9679; Monitor running</span>':'<span class="neg">&#9679; Monitor not running</span>')+'</div>';
    let html='<h3 class="chart-title">Alert feed</h3>';
    const items=al.alerts||[];
    if(!items.length)html+='<div class="loading">No alerts yet — signals, watch triggers, and trader exits will appear here.</div>';
    else{
      html+='<table><thead><tr><th>Time</th><th>Sev</th><th>Type</th><th>Item</th><th>Message</th></tr></thead><tbody>';
      items.forEach(a=>{
        html+='<tr'+(a.read?' class="dim"':'')+'><td>'+new Date(a.ts*1000).toLocaleString()+'</td>'+
          '<td class="sev-'+escHtml(a.severity)+'">'+escHtml(a.severity)+'</td>'+
          '<td><span class="sig-badge sig-'+escHtml(a.type)+'">'+escHtml(a.type)+'</span></td>'+
          '<td class="name">'+escHtml(a.item_name||'')+'</td>'+
          '<td class="name">'+escHtml(a.message)+'</td></tr>';
      });
      html+='</tbody></table>';
    }
    html+='<h3 class="chart-title">Trader status</h3>';
    html+=traderNoticeHtml(trader);
    html+=traderControlHtml(trader);
    html+='<h3 class="chart-title">Monitor status</h3>';
    html+='<div class="notice" style="border-color:var(--border);color:var(--text-dim);background:var(--surface)">'+
      (mon.running?'Monitor running (PID '+mon.pid+'), last check '+escHtml(String(mon.last_check_iso||'-').slice(0,16))
                  :'Monitor not running'+(meta.control?' — start it below':' — start it with <code>rshelper monitor</code>'))+'</div>';
    html+=monitorControlHtml(mon);
    if(buckets.length>=2){
      html+='<h3 class="chart-title">Cumulative P&L</h3><canvas id="ovCum" height="180"></canvas>';
    }
    body.innerHTML=html;
    updateBadges();
    if(buckets.length>=2)drawCumulative(document.getElementById('ovCum'),buckets);
  }catch(e){
    body.innerHTML='<div class="loading">Error loading overview: '+escHtml(e.message)+'</div>';
    context.innerHTML='';
  }
}
async function renderActivity(){
  const bar=document.getElementById('viewbar');
  bar.innerHTML=viewbarHtml();
  const body=document.getElementById('listBody');
  const context=document.getElementById('contextPanel');
  body.innerHTML='<div class="loading"><span class="spinner"></span>Loading activity...</div>';
  context.innerHTML='<div class="loading"><span class="spinner"></span></div>';
  const stratParam=strategy?'?strategy='+strategy:'';
  try{
    const [pr,tr,hr]=await Promise.all([
      fetch('/api/pnl'+stratParam),fetch('/api/trades'+stratParam),
      fetch('/api/history?paper=1'+(strategy?'&strategy='+strategy:''))]);
    if(!pr.ok||!tr.ok||!hr.ok)throw new Error('activity API failed');
    const pnl=await pr.json();
    const trades=(await tr.json()).trades||[];
    const h=await hr.json();
    context.innerHTML='<div class="item-name" style="margin-bottom:12px">Activity</div>'+
      '<div class="metric-grid">'+
      metric('Total P&L',format(pnl.total_profit||0)+' gp',(pnl.total_profit||0)>0?'green':(pnl.total_profit||0)<0?'red':'')+
      metric('ROI',(pnl.roi_pct||0).toFixed(2)+'%',(pnl.roi_pct||0)>0?'green':'')+
      metric('Win Rate',(pnl.win_rate||0).toFixed(1)+'%','gold')+
      metric('Trades',format(pnl.trade_count||0),'')+
      metric('Items',format(pnl.items_traded||0),'')+
      metric('Profit Factor',pnl.profit_factor!=null?format(pnl.profit_factor):'-','gold')+
      metric('Max Drawdown',format(pnl.max_drawdown||0)+' gp',(pnl.max_drawdown||0)>0?'red':'')+
      metric('Tax Paid',format(pnl.total_tax_paid||0)+' gp','')+
      '</div>';
    let html='';
    const buckets=h.buckets||[];
    if(buckets.length>=2){
      html+='<h3 class="chart-title">Cumulative P&L</h3><canvas id="actCum" height="200"></canvas>';
      html+='<h3 class="chart-title">Daily trades and win rate</h3><canvas id="actDaily" height="200"></canvas>';
    }
    html+='<h3 class="chart-title">Recent trades</h3>';
    if(!trades.length){
      html+='<div class="loading">No trades yet — open one with <code>trade open &lt;item&gt;</code> or <code>trade paper &lt;item&gt;</code>.</div>';
    }else{
      html+='<table><thead><tr><th>Date</th><th>Item</th><th>Qty</th><th>Buy</th><th>Sell</th><th>Profit</th><th></th></tr></thead><tbody>';
      trades.slice(0,20).forEach(t=>{
        const p=t.profit||0;
        html+='<tr><td>'+escHtml(String(t.timestamp||'').slice(0,16))+'</td><td class="name">'+escHtml(t.name||'')+'</td>'+
          '<td>'+format(t.qty||0)+'</td><td>'+format(t.buy_price||0)+'</td><td>'+format(t.sell_price||0)+'</td>'+
          '<td class="margin '+(p>0?'pos':p<0?'neg':'neutral')+'">'+format(p)+'</td>'+
          '<td><button class="act-btn" style="padding:1px 8px;background:#7f1d1d;border-color:#f87171;color:#f87171" onclick="deleteTrade('+t.id+',event)">&#10005;</button></td></tr>';
      });
      html+='</tbody></table>';
    }
    html+=historyTablesHtml(h);
    body.innerHTML=html;
    if(buckets.length>=2){
      drawCumulative(document.getElementById('actCum'),buckets);
      drawDaily(document.getElementById('actDaily'),buckets);
    }
  }catch(e){
    body.innerHTML='<div class="loading">Error loading activity: '+escHtml(e.message)+'</div>';
    context.innerHTML='';
  }
}
async function deleteTrade(tradeId,ev){
  if(ev)ev.stopPropagation();
  if(!confirm('Delete this trade from the journal?'))return;
  try{
    const r=await fetch('/api/trades/delete',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({trade_id:tradeId})});
    if(!r.ok)throw new Error('delete failed');
    setStatus('Trade deleted',false);
    fetchData();
  }catch(e){setStatus('Error: '+e.message,true);}
}
fetchData();
subscribeSSE();
setInterval(tick,1000);
"""
