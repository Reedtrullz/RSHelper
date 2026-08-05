"""Dashboard HTML template — Command Center layout (v3.0 IA).

The HTML shell + CSS live here; the client-side JavaScript lives in
scripts.py (SCRIPT_CORE / SCRIPT_CHARTS / SCRIPT_VIEWS) and is inlined into
the single served artifact below. Still zero external dependencies.
"""

from rshelper.dashboard.scripts import SCRIPT_CORE, SCRIPT_CHARTS, SCRIPT_VIEWS

_STYLE = r"""
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
  color:var(--text-dim);font-size:15px;cursor:pointer;position:relative
}
.icon-btn:hover{color:var(--gold);border-color:var(--gold-dim)}
.bell-badge{
  position:absolute;top:-6px;right:-8px;min-width:16px;padding:0 4px;border-radius:9px;
  background:var(--neg);color:#fff;font-size:10px;font-weight:700;line-height:16px;text-align:center
}
.alert-dropdown{
  position:fixed;top:52px;right:20px;width:420px;max-height:70vh;overflow-y:auto;
  background:var(--surface2);border:1px solid var(--gold-dim);border-radius:8px;z-index:200;
  box-shadow:0 8px 24px rgba(0,0,0,.5)
}
.alert-dd-head{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-bottom:1px solid var(--border);font-weight:700;color:var(--gold)}
.alert-dd-clear{background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:12px}
.alert-dd-clear:hover{color:var(--gold)}
.alert-dd-item{padding:8px 12px;border-bottom:1px solid var(--border);font-size:12px;line-height:1.4;color:var(--text)}
.alert-dd-item.read{color:var(--text-dim)}
.alert-dd-item:hover{background:var(--surface3)}
.alert-sev{font-weight:700}
.alert-type{color:var(--blue);text-transform:uppercase;font-size:10px}
.alert-ts{color:var(--text-dim);float:right;font-size:10px}
.navrow{
  display:flex;align-items:center;gap:6px;padding:8px 20px;
  background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0;
  flex-wrap:wrap
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
  display:flex;align-items:center;gap:8px;padding:8px 20px 0;flex-shrink:0;
  flex-wrap:wrap
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
.alert-edit{background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:13px}
.alert-edit:hover{color:var(--gold)}
.sig-badge{display:inline-block;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.4px}
.sig-CRASH{background:rgba(248,113,113,.15);color:var(--neg);border:1px solid rgba(248,113,113,.35)}
.sig-DUMP{background:rgba(234,179,8,.12);color:var(--warn);border:1px solid rgba(234,179,8,.35)}
.sig-SURGE{background:rgba(96,165,250,.12);color:var(--blue);border:1px solid rgba(96,165,250,.35)}
.sig-FLIP{background:rgba(201,168,76,.12);color:var(--gold);border:1px solid rgba(201,168,76,.35)}
.sig-trader{background:rgba(34,197,94,.12);color:var(--pos);border:1px solid rgba(34,197,94,.35)}
.sig-watch{background:rgba(234,179,8,.12);color:var(--warn);border:1px solid rgba(234,179,8,.35)}
.sig-system{background:rgba(148,163,184,.12);color:var(--text-dim);border:1px solid rgba(148,163,184,.35)}
.sev-HIGH{color:var(--neg);font-weight:700}.sev-MEDIUM{color:var(--warn)}.sev-LOW{color:var(--text-dim)}.sev-INFO{color:var(--blue)}
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
#marginChart{width:100%;height:120px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);display:block}
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
"""

_NAV = r"""
<div class="navrow" role="tablist" aria-label="Views">
  <button class="nav-btn" id="btnOverview" role="tab" onclick="setView('overview')">Overview <span class="badge" id="badgeOverview">-</span></button>
  <button class="nav-btn active" id="btnMarket" role="tab" onclick="setView('market')">Market <span class="badge" id="badgeMarket">-</span></button>
  <button class="nav-btn" id="btnPaper" role="tab" onclick="setView('paper')">Trading <span class="badge" id="badgePaper">-</span></button>
  <button class="nav-btn" id="btnSignals" role="tab" onclick="setView('signals')">Signals <span class="badge" id="badgeSignals">-</span></button>
  <button class="nav-btn" id="btnWatchlist" role="tab" onclick="setView('watchlist')">Watchlist <span class="badge" id="badgeWatchlist">-</span></button>
  <button class="nav-btn" id="btnGE" role="tab" onclick="setView('ge')">Grand Exchange <span class="badge" id="badgeGE">-</span></button>
  <button class="nav-btn" id="btnBank" role="tab" onclick="setView('bank')">Bank <span class="badge" id="badgeBank">-</span></button>
  <button class="nav-btn" id="btnProcess" role="tab" onclick="setView('process')">Materials <span class="badge" id="badgeProcess">-</span></button>
  <button class="nav-btn" id="btnActivity" role="tab" onclick="setView('activity')">Activity <span class="badge" id="badgeActivity">-</span></button>
</div>
"""

_SHELL = r"""
<div class="topbar">
  <h1>RSHelper</h1>
  <div class="search"><input type="text" id="search" placeholder="Filter current list..." oninput="applySearch()" aria-label="Filter items"></div>
  <div class="stats" id="statsSlot"></div>
</div>
"""

_FOOTER = r"""
<div class="footer">
  <span><span class="dot" id="statusDot"></span><span id="statusText">Connected</span><span class="source-badge none" id="sourceBadge">-</span></span>
  <span><span class="kbd" id="kbdHint">&#8593;&#8595; move</span> <span id="lastUpdated">Last updated: --</span> <span id="footerBell"></span></span>
</div>
"""

INDEX_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RSHelper Dashboard</title>
<style>
{_STYLE}
</style>
</head>
<body>
{_SHELL}
{_NAV}
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
{_FOOTER}
<script>
{SCRIPT_CORE}
{SCRIPT_CHARTS}
{SCRIPT_VIEWS}
</script>
</body>
</html>"""
