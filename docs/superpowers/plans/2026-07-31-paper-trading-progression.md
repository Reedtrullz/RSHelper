# Paper Trading Progression Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Progression view to the RSHelper dashboard correlating paper
trade outcomes with config (tuning) changes over time.

**Architecture:** Extend the existing stdlib dashboard. A new `tuning.py`
persists config-change events; `snapshot.save()` embeds a config fingerprint;
`history.py` joins trades + snapshots + tuning log into daily buckets and
eras; a `/api/history` route feeds a Canvas-chart Progression tab in the
inline template.

**Tech Stack:** Python 3.11 stdlib only (`tomllib`, `http.server`, `json`),
inline HTML/JS with Canvas 2D. No PyPI packages.

## Global Constraints

- Stdlib only; never add PyPI packages.
- stdout is data only; all status/progress/error messages go to stderr.
- All state-file writes are atomic (temp file + `os.replace`).
- GE tax stays 2% capped at 5M/item; do not touch tax logic.
- Margin convention and confidence model are unchanged.
- Tests run as `for f in tests/test_*.py; do .venv/bin/python "$f"; done`;
  every test file must exit 0 standalone.
- Commit convention: `v1.x: <summary>` or `hardening: <summary>`.
- Run everything through `.venv/bin/python`.

---

### Task 1: tuning.py — config fingerprint + changelog

**Files:**
- Create: `src/rshelper/tuning.py`
- Test: `tests/test_tuning.py`

**Interfaces:**
- Produces: `params(profile=None) -> dict`,
  `log_path(profile=None) -> Path`,
  `load_entries(profile=None) -> list[dict]`,
  `record_if_changed(profile=None, note="auto") -> dict | None`,
  `config_at(day: str, entries: list[dict]) -> dict | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tuning.py`:

```python
"""Tests for the tuning log module."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rshelper import profile, tuning


class TestTuning(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._cfg = profile.CONFIG_DIR
        self._active = profile.ACTIVE_PROFILE_PATH
        profile.CONFIG_DIR = self.tmp
        profile.ACTIVE_PROFILE_PATH = self.tmp / "active_profile"

    def tearDown(self):
        profile.CONFIG_DIR = self._cfg
        profile.ACTIVE_PROFILE_PATH = self._active

    def test_params_shape(self):
        p = tuning.params()
        self.assertEqual(set(p), {"alch", "flip", "margin"})
        self.assertIn("min_volume", p["flip"])
        self.assertIn("direction", p["margin"])

    def test_record_on_change(self):
        entry = tuning.record_if_changed()
        self.assertIsNotNone(entry)
        self.assertEqual(entry["note"], "auto")
        self.assertIn("params", entry)
        self.assertEqual(len(tuning.load_entries()), 1)

    def test_skip_when_unchanged(self):
        tuning.record_if_changed()
        self.assertIsNone(tuning.record_if_changed())
        self.assertEqual(len(tuning.load_entries()), 1)

    def test_profile_isolation(self):
        tuning.record_if_changed("main")
        self.assertTrue(tuning.log_path("main").exists())
        self.assertFalse(tuning.log_path().exists())

    def test_config_at(self):
        entries = [
            {"ts": "2026-07-30T10:00:00Z", "params": {"v": 1}},
            {"ts": "2026-08-01T10:00:00Z", "params": {"v": 2}},
        ]
        self.assertEqual(tuning.config_at("2026-07-31", entries), {"v": 1})
        self.assertEqual(tuning.config_at("2026-08-02", entries), {"v": 2})
        self.assertIsNone(tuning.config_at("2026-01-01", entries))

    def test_unchanged_params_not_duplicated(self):
        tuning.record_if_changed()
        tuning.record_if_changed()
        self.assertEqual(len(tuning.load_entries()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python tests/test_tuning.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'rshelper.tuning'`.

- [ ] **Step 3: Write the minimal implementation**

`src/rshelper/tuning.py`:

```python
"""Tuning log: record config.toml parameter changes over time."""
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone

from rshelper.config import load_config
from rshelper.profile import resolve_config_path


def params(profile: str | None = None) -> dict:
    """Effective tuning parameters as a JSON-safe dict."""
    cfg = load_config(profile)
    return {"alch": asdict(cfg.alch), "flip": asdict(cfg.flip), "margin": asdict(cfg.margin)}


def log_path(profile: str | None = None):
    return resolve_config_path("tuning_log.json", profile)


def load_entries(profile: str | None = None) -> list[dict]:
    path = log_path(profile)
    try:
        if path.exists():
            return json.loads(path.read_text()).get("entries", [])
    except (json.JSONDecodeError, OSError):
        pass
    return []


def record_if_changed(profile: str | None = None, note: str = "auto") -> dict | None:
    """Append a tuning entry when effective params changed. Returns the entry or None."""
    current = params(profile)
    entries = load_entries(profile)
    if entries and entries[-1]["params"] == current:
        return None
    entry = {"ts": datetime.now(timezone.utc).isoformat(),
             "params": current, "note": note}
    entries.append(entry)
    path = log_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"entries": entries}))
    os.replace(tmp, path)
    return entry


def config_at(day: str, entries: list[dict]) -> dict | None:
    """Params in effect on `day` (last entry on or before it), else None."""
    active = None
    for e in entries:
        if e["ts"][:10] <= day:
            active = e["params"]
    return active
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: all 7 tests PASS.

### Task 2: journal note filter

**Files:**
- Modify: `src/rshelper/journal.py` (`list_trades`, `compute_pnl`,
  `compute_pnl_by_item`)
- Test: `tests/test_journal.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `list_trades(item_name="", since="", top=0, profile=None,
  note="")`, `compute_pnl(since="", profile=None, note="")`,
  `compute_pnl_by_item(since="", profile=None, note="")` — all backward
  compatible (default `note=""` means no filter).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_journal.py`:

```python
def test_pnl_note_filter():
    _clean()
    log_trade(1, "A", 1, 100, 200, "paper")
    log_trade(2, "B", 1, 100, 200, "")
    assert list_trades(note="paper")[0].name == "A"
    assert len(list_trades(note="paper")) == 1
    assert compute_pnl(note="paper").trade_count == 1
    rows = compute_pnl_by_item(note="paper")
    assert len(rows) == 1 and rows[0].name == "A"
    assert compute_pnl().trade_count == 2
    print("  PASSED test_pnl_note_filter")
```

Register it in the `__main__` block after `test_pnl_by_item_breakdown()`.

- [ ] **Step 2: Run to verify failure**

Expected: FAIL with `TypeError: list_trades() got an unexpected keyword argument 'note'`.

- [ ] **Step 3: Implement the filter**

In `list_trades`, after the `since` filter:

```python
    if note:
        result = [t for t in result if t.note == note]
```

Change `compute_pnl` signature to `compute_pnl(since: str = "", profile: str | None = None, note: str = "")` and its call:

```python
    trades_list = list_trades(since=since, profile=profile, note=note) if since else list_trades(profile=profile, note=note)
```

Change `compute_pnl_by_item` signature the same way and its call:

```python
    trades_list = list_trades(since=since, profile=profile, note=note) if since else list_trades(profile=profile, note=note)
```

- [ ] **Step 4: Run to verify pass**

```bash
.venv/bin/python tests/test_journal.py
```

Expected: all journal tests PASS.

### Task 3: snapshot config fingerprint

**Files:**
- Modify: `src/rshelper/snapshot.py`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `tuning.params(profile)`.
- Produces: snapshot payloads containing `"config": {...}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_snapshot.py` in `TestSnapshot`:

```python
    def test_save_embeds_config_fingerprint(self):
        path = snapshot.save("flip", self._fake_results())
        data = json.loads(path.read_text())
        self.assertIn("config", data)
        self.assertIn("flip", data["config"])
        self.assertIn("min_volume", data["config"]["flip"])
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL with `KeyError: 'config'`.

- [ ] **Step 3: Implement**

In `snapshot.py`, import at top: `from rshelper.tuning import params` and add
to the `save()` payload:

```python
    payload = {
        "scan_type": scan_type,
        "date": today,
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(results),
        "config": params(profile),
        "items": results,
    }
```

- [ ] **Step 4: Run to verify pass**

Expected: all snapshot tests PASS.

### Task 4: history.py — daily buckets and eras

**Files:**
- Create: `src/rshelper/history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- Consumes: `journal.list_trades/compute_pnl/compute_pnl_by_item` (with
  `note`), `snapshot.list_snapshots`, `tuning.load_entries/config_at`.
- Produces: `build_history(profile=None, paper_only=True) -> dict` with
  `summary`, `buckets`, `eras`, `items` as specified in the design doc.

- [ ] **Step 1: Write the failing tests**

`tests/test_history.py`:

```python
"""Tests for the history builder."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rshelper import history, profile, snapshot
from rshelper import journal as jmod
from rshelper import tuning as tmod


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._trades = jmod.TRADES_PATH
        self._snap = snapshot.SNAPSHOT_DIR
        self._cfg = profile.CONFIG_DIR
        self._active = profile.ACTIVE_PROFILE_PATH
        jmod.TRADES_PATH = self.tmp / "trades.json"
        snapshot.SNAPSHOT_DIR = self.tmp / "snapshots"
        profile.CONFIG_DIR = self.tmp
        profile.ACTIVE_PROFILE_PATH = self.tmp / "active_profile"

    def tearDown(self):
        jmod.TRADES_PATH = self._trades
        snapshot.SNAPSHOT_DIR = self._snap
        profile.CONFIG_DIR = self._cfg
        profile.ACTIVE_PROFILE_PATH = self._active

    def _write_entries(self, entries):
        path = tmod.log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"entries": entries}))

    def test_empty_history(self):
        h = history.build_history()
        self.assertEqual(h["buckets"], [])
        self.assertEqual(h["eras"], [])
        self.assertEqual(h["summary"]["trade_count"], 0)

    def test_cumulative_buckets_and_paper_filter(self):
        jmod.log_trade(1, "A", 1, 100, 200, "paper")
        jmod.log_trade(2, "B", 1, 100, 200, "")
        h = history.build_history(paper_only=True)
        self.assertEqual(h["summary"]["trade_count"], 1)
        self.assertEqual(len(h["buckets"]), 1)
        self.assertEqual(h["buckets"][0]["profit"], 96)
        self.assertEqual(h["buckets"][0]["cumulative_profit"], 96)
        h_all = history.build_history(paper_only=False)
        self.assertEqual(h_all["summary"]["trade_count"], 2)

    def test_config_assignment_and_change_flags(self):
        self._write_entries([
            {"ts": "2026-07-29T10:00:00Z", "params": {"v": 1}, "note": "auto"},
            {"ts": "2026-07-31T10:00:00Z", "params": {"v": 2}, "note": "auto"},
        ])
        jmod.log_trade(1, "A", 1, 100, 200, "paper")
        h = history.build_history()
        day = h["buckets"][0]["date"]
        if day == "2026-07-31":
            self.assertTrue(h["buckets"][0]["config_changed"])
            self.assertEqual(h["buckets"][0]["config"], {"v": 2})
        else:
            self.assertFalse(h["buckets"][0]["config_changed"])
            self.assertEqual(h["buckets"][0]["config"], {"v": 1})

    def test_snapshot_join(self):
        snapshot.save("flip", [
            {"item_id": 1, "name": "A", "profit": 100},
            {"item_id": 2, "name": "B", "profit": 300},
        ])
        h = history.build_history()
        self.assertEqual(len(h["buckets"]), 1)
        snaps = h["buckets"][0]["snapshots"]
        self.assertEqual(snaps[0]["scan_type"], "flip")
        self.assertEqual(snaps[0]["count"], 2)
        self.assertEqual(snaps[0]["avg_value"], 200)

    def test_eras_split_trades(self):
        self._write_entries([
            {"ts": "2026-07-29T10:00:00Z", "params": {"v": 1}, "note": "auto"},
            {"ts": "2026-07-31T10:00:00Z", "params": {"v": 2}, "note": "auto"},
        ])
        jmod.log_trade(1, "A", 1, 100, 200, "paper")
        h = history.build_history()
        self.assertEqual(len(h["eras"]), 2)
        last = h["eras"][-1]
        self.assertEqual(last["config"], {"v": 2})
        self.assertGreaterEqual(last["trade_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

Note: `log_trade` timestamps use the real clock, so `test_eras_split_trades`
keeps assertions date-agnostic; `test_config_assignment_and_change_flags`
branches on today's date.

- [ ] **Step 2: Run to verify failure**

Expected: FAIL with `ModuleNotFoundError: No module named 'rshelper.history'`.

- [ ] **Step 3: Implement `history.py`**

```python
"""Daily history for the dashboard Progression view."""
import json
from collections import defaultdict
from datetime import date

from rshelper import snapshot, tuning
from rshelper.journal import compute_pnl, compute_pnl_by_item, list_trades


def build_history(profile: str | None = None, paper_only: bool = True) -> dict:
    """Join trades, snapshots, and tuning entries into daily buckets and eras."""
    note = "paper" if paper_only else ""
    trades = list_trades(note=note, profile=profile)
    pnl = compute_pnl(note=note, profile=profile)
    items = compute_pnl_by_item(note=note, profile=profile)
    entries = tuning.load_entries(profile)

    daily: dict[str, list] = defaultdict(list)
    for t in trades:
        daily[t.timestamp[:10]].append(t)

    snaps_by_day: dict[str, list] = defaultdict(list)
    for path in snapshot.list_snapshots(profile=profile):
        day = path.stem.rsplit("-", 1)[-1]
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        vals = [i.get("profit") if i.get("profit") is not None else i.get("avg_margin")
                for i in data.get("items", [])]
        vals = [v for v in vals if v is not None]
        snaps_by_day[day].append({
            "scan_type": data.get("scan_type"),
            "count": data.get("count", 0),
            "avg_value": round(sum(vals) / len(vals)) if vals else None,
        })

    days = sorted(set(daily) | set(snaps_by_day))
    buckets = []
    cumulative = 0
    for day in days:
        day_trades = daily.get(day, [])
        profit = sum(t.profit for t in day_trades)
        wins = sum(1 for t in day_trades if t.profit > 0)
        cumulative += profit
        buckets.append({
            "date": day,
            "trade_count": len(day_trades),
            "profit": profit,
            "cumulative_profit": cumulative,
            "win_rate": round(wins / len(day_trades) * 100, 1) if day_trades else None,
            "avg_profit_per_trade": round(profit / len(day_trades)) if day_trades else None,
            "snapshots": snaps_by_day.get(day, []),
            "config": tuning.config_at(day, entries),
            "config_changed": any(e["ts"][:10] == day for e in entries),
        })

    today = date.today().isoformat()
    last_day = days[-1] if days else today
    eras = []
    for i, e in enumerate(entries):
        start = e["ts"][:10]
        end = entries[i + 1]["ts"][:10] if i + 1 < len(entries) else last_day
        if end <= start:
            end = last_day
        era_trades = [t for t in trades
                      if start <= t.timestamp[:10] < end] if end > start else \
                     [t for t in trades if t.timestamp[:10] >= start]
        cost = sum(t.buy_price * t.qty for t in era_trades)
        profit = sum(t.profit for t in era_trades)
        wins = sum(1 for t in era_trades if t.profit > 0)
        active_days = len({t.timestamp[:10] for t in era_trades})
        eras.append({
            "start": start,
            "end": end,
            "config": e["params"],
            "note": e.get("note", "auto"),
            "trade_count": len(era_trades),
            "profit": profit,
            "win_rate": round(wins / len(era_trades) * 100, 1) if era_trades else None,
            "roi_pct": round(profit / cost * 100, 2) if cost else None,
            "trades_per_day": round(len(era_trades) / active_days, 1) if active_days else 0,
        })

    return {
        "summary": {
            "total_profit": pnl.total_profit,
            "win_rate": round(pnl.win_rate, 1),
            "roi_pct": round(pnl.roi_pct, 2),
            "trade_count": pnl.trade_count,
            "items_traded": pnl.items_traded,
            "active_days": len({t.timestamp[:10] for t in trades}),
        },
        "buckets": buckets,
        "eras": eras,
        "items": [
            {"item_id": i.item_id, "name": i.name, "trade_count": i.trade_count,
             "qty": i.qty, "cost_basis": i.cost_basis, "profit": i.profit,
             "roi_pct": round(i.roi_pct, 2), "win_rate": round(i.win_rate, 1)}
            for i in items
        ],
    }
```

- [ ] **Step 4: Run tests to verify pass**

```bash
.venv/bin/python tests/test_history.py
```

Expected: all 6 tests PASS.

### Task 5: `/api/history` route + record wiring

**Files:**
- Modify: `src/rshelper/dashboard/handlers.py`,
  `src/rshelper/dashboard/server.py`, `src/rshelper/cli.py`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `history.build_history`, `tuning.record_if_changed`.
- Produces: `GET /api/history?paper=1|0` JSON; tuning entry written at
  dashboard startup and on every CLI snapshot save.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dashboard.py` (in `TestHandlerRouting`, reusing the
existing harness):

```python
    def test_history_route(self):
        self.handler.path = "/api/history?paper=1"
        self.handler.do_GET()
        self.assertEqual(self.handler.response_code, 200)
        data = json.loads(self._get_body().decode())
        for key in ("summary", "buckets", "eras", "items"):
            self.assertIn(key, data)

    def test_progression_markup_present(self):
        self.assertIn("Progression", INDEX_HTML)
        self.assertIn("/api/history", INDEX_HTML)
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — history route returns 404; "Progression" absent from HTML.

- [ ] **Step 3: Implement**

In `handlers.py` `do_GET`, add before the 404 branch:

```python
            elif path == "/api/history":
                self._serve_history()
```

Add the handler method:

```python
        def _serve_history(self):
            from urllib.parse import parse_qs
            from rshelper.history import build_history
            qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            paper_only = qs.get("paper", ["1"])[0] != "0"
            try:
                self._serve_json(build_history(paper_only=paper_only))
            except Exception as e:
                print(f"[dashboard] history error: {e}", file=sys.stderr)
                self.send_error(500, "History failed")
```

In `server.py` `run()`, after the bootstrap fetch:

```python
    from rshelper.tuning import record_if_changed
    record_if_changed()
```

In `cli.py`, change the import to `from rshelper import snapshot, watchlist, tuning`
and add one line to each of `_save_alch_snapshot`, `_save_flip_snapshot`,
`_save_margin_snapshot` after `snapshot.save(...)`:

```python
    tuning.record_if_changed(profile)
```

- [ ] **Step 4: Run to verify pass**

```bash
.venv/bin/python tests/test_dashboard.py
```

Expected: all dashboard tests PASS.

### Task 6: Progression view in the dashboard template

**Files:**
- Modify: `src/rshelper/dashboard/templates.py`
- Test: covered by `test_progression_markup_present` in Task 5.

**Interfaces:**
- Consumes: `/api/history` JSON.
- Produces: Progression toggle + paper toggle; summary metrics; cumulative
  P&L canvas with tuning markers; daily bars + win-rate canvas; eras and
  per-item tables.

- [ ] **Step 1: Add the toggle buttons**

In the `.controls` div, after the Trades button:

```html
  <button id="btnProgress" onclick="toggleProgress()">Progression</button>
  <button id="btnPaper" onclick="togglePaper()" class="active">Paper</button>
```

- [ ] **Step 2: Add the JS**

Add to the script, after `toggleTrades()`:

```js
let showProgress=false,paperOnly=true;
function toggleProgress(){
  showProgress=!showProgress;
  document.getElementById('btnProgress').classList.toggle('active',showProgress);
  if(showProgress)renderProgress();
  else{selectedId=null;applyFilters()}
}
function togglePaper(){
  paperOnly=!paperOnly;
  document.getElementById('btnPaper').classList.toggle('active',paperOnly);
  if(showProgress)renderProgress();
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
    const buckets=h.buckets||[],eras=h.eras||[],items=h.items||[];
    let html='';
    if(buckets.length<2){
      html+='<div class="loading">Not enough days yet — log a few paper trades over time and tune config.toml between days.</div>';
    }else{
      html+='<h3 class="chart-title">Cumulative P&L with tuning changes</h3><canvas id="cumChart" height="220"></canvas>';
      html+='<h3 class="chart-title">Daily trades and win rate</h3><canvas id="dailyChart" height="220"></canvas>';
    }
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
    const px=x(i),py=y2(b.win_rate,h,pad);
    i?ctx.lineTo(px,py):ctx.moveTo(px,py);
  });
  ctx.stroke();ctx.lineWidth=1;
  ctx.fillStyle='#60a5fa';ctx.fillText('win %',w-46,pad.t+4);
}
function y2(v,h,pad){
  const span=100;
  return pad.t+(h-pad.t-pad.b)*(100-(v==null?0:v))/span;
}
```

Add a small style rule near `.loading`:

```css
.chart-title{font-size:13px;font-weight:700;color:var(--gold);margin:20px 0 8px}
.table-panel canvas{width:100%;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)}
```

- [ ] **Step 3: Run dashboard tests**

```bash
.venv/bin/python tests/test_dashboard.py
```

Expected: PASS (markup assertions from Task 5).

### Task 7: Full suite, smoke, commit

- [ ] **Step 1: Run all test files**

```bash
for f in tests/test_*.py; do .venv/bin/python "$f"; done
```

Expected: 14 files, all passing (12 existing + `test_tuning.py` +
`test_history.py`).

- [ ] **Step 2: Smoke the dashboard**

```bash
PYTHONPATH=src .venv/bin/python -m rshelper dashboard --port 5561 &
sleep 2
curl -s http://127.0.0.1:5561/ | head -5
curl -s http://127.0.0.1:5561/api/history?paper=0 | python3 -m json.tool | head -20
curl -s http://127.0.0.1:5561/api/health
kill %1
```

Expected: HTML served; history JSON valid with `summary`, `buckets`,
`eras`, `items`; health `{"status":"ok"}`. Also verify
`~/.config/rshelper/tuning_log.json` was created with one entry.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-07-31-paper-trading-progression-design.md
git add docs/superpowers/plans/2026-07-31-paper-trading-progression.md
git commit -m "docs: paper trading progression spec and plan"
git add src tests
git commit -m "v1.6: paper trading progression dashboard"
```

- [ ] **Step 4: Anti sidecar review on the code diff, triage findings**

```bash
python3 ~/.codex/skills/anti/scripts/anti.py review --model opus --scope diff --base HEAD~1
```

Verify every actionable finding locally before fixing; record skips.

## Self-Review

- Spec coverage: tuning log (Task 1), snapshot fingerprint (Task 3), history
  join (Task 4), `/api/history` (Task 5), Progression view (Task 6), tests +
  smoke + commit (Task 7). Journal `note` filter (Task 2) is the enabler for
  paper-only filtering. No spec requirement is left without a task.
- Placeholder scan: no TBD/TODO; every code step carries real code.
- Type consistency: `params(profile=None)`, `load_entries(profile=None)`,
  `config_at(day, entries)`, `build_history(profile=None, paper_only=True)`,
  `list_trades(..., note="")`, `compute_pnl(..., note="")`,
  `compute_pnl_by_item(..., note="")` — all used with matching names and
  signatures across tasks.
