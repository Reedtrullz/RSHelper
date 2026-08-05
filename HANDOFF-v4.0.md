# HANDOFF v4.0 — Command Center UI/UX Refactor + Dual-Surface Parity

**Current state: v3.0.0** — stdlib-only Python 3.11+, 344 tests across 24
files, all passing. Live deploy: https://rs.reidar.tech (VPS + Caddy).

## What changed in v3.0

The dashboard grew organically from 4 tabs to 7 without an IA redesign; the
auto-trader, GE/Bank, and Materials features all landed on top of the original
layout. v3.0 restructures both surfaces around jobs-to-be-done, adds a
persistent alert feed, server-push refresh, daemon control, and closes the
CLI/dashboard feature-parity gaps both directions.

### New module: `src/rshelper/alerts.py`
- Persistent per-profile alert feed: `alerts.json` (cap 200, prune 14d,
  atomic writes, thread-safe). `push_alert` never raises (best-effort).
- Types: `signal` (DUMP/CRASH/SURGE/FLIP), `watch` (threshold crossing),
  `trader` (every auto-close: reason + P&L), `system` (source change).
- Watch-threshold dedupe map (`watch_triggered`, 15-min window) lives in the
  same file; this makes the feed work on the VPS where the monitor never runs.
- Synced to the deploy: `scripts/sync-and-push-state.py` FILES + 
  `deploy/merge_state.py` `LIST_FILES` (union by id, repo wins ties).

### Dashboard (`server.py` / `handlers.py` / `templates.py` / `scripts.py`)
- **9-tab IA**: Overview · Market · Trading · Signals · Watchlist ·
  Grand Exchange · Bank · Materials · Activity.
  - **Overview**: headline P&L, alert feed, trader + monitor status cards
    (start/stop when control enabled), cumulative P&L mini-chart.
  - **Trading**: paper trade form, open positions with **Close** (manual
    lots only; auto lots show "Auto"), trader status/control/perf, live
    market on traded items.
  - **Activity**: P&L metrics, cumulative + daily charts, recent trades with
    **Delete**, per-item P&L, tuning eras (absorbed the old GE History modal).
  - **Market**: flip table + **Alchemy toggle**; detail panel gains a 24h
    margin-history chart alongside the 8h sparkline.
  - **Watchlist**: inline alert-threshold editor (✎ per row) + check-now.
- **SSE push** (`/api/events`): server broadcasts `refresh` (on 120s cache
  refresh) and `alert` events; the client refetches immediately and updates
  the bell/unread badge. 60s poll stays as fallback. SSE handler is
  self-terminating (bounded wait) so tests don't hang.
- **Alert bell** in the topbar with unread badge, dropdown of recent alerts,
  mark-all-read.
- **Daemon control** behind `rshelper dashboard --control`: POST
  `/api/trader` and `/api/monitor` with `{action: start|stop}`. Spawns
  detached daemons with logs at `~/.config/rshelper/logs/<daemon>.log`
  (rotated at 5MB). **403 without `--control`**; the VPS deploy never enables
  it (control defaults off).
- **Profile threading**: every closure now takes `profile=` — the dashboard
  finally respects `--profile NAME`.
- `--open` flag fires the browser (precedent: `item-info --wiki-open`).
- New routes: `/api/alerts`, `/api/alerts/read`, `/api/events`,
  `/api/trader` POST, `/api/monitor` POST, `/api/alch`, `/api/confidence`,
  `/api/positions` POST (close), `/api/watchlist` action `"alerts"`,
  `/api/watchlist/check`, `/api/trades/delete`; `/api/timeseries` gains
  `step=` and `points=`.
- Emitters: trader pushes `trader` alerts on closes; monitor pushes
  `signal` + `watch` alerts; the dashboard server pushes `signal` (only when
  no local monitor — no double-push), `watch`, and `system` alerts, and
  broadcasts every push over SSE.
- `templates.py` (shell + CSS) and new `scripts.py` (JS split into
  `SCRIPT_CORE` / `SCRIPT_CHARTS` / `SCRIPT_VIEWS`) — still one served
  artifact, zero deps.

### CLI parity additions (`src/rshelper/cli.py`)
- `trade status [--json]` — positions + unrealized + realized P&L + trader
  status in one summary (mirror of the Trading tab).
- `history [--all] [--strategy] [--json]` — progression (Activity parity).
- `signals --monitor [N]` — live follow mode: re-scans every N s (default
  30), prints `[signal] ...` lines for new signals only; Ctrl-C clean.
- `watch check --json` — JSON alerts (exit 1 still fires on triggers).
- `dashboard --open --control --profile NAME`.
- `trade positions --json` rows now include `note`.

### `ge_offers.py`
- Extracted `close_market_price(position, latest)` (direction-aware exit
  leg, buy-price fallback) shared by `collect_offer` and the new dashboard
  position-close closure.

## Current CLI surface (17 top-level commands)

`alch-scan` · `flip-scan` · `process-scan` · `margin-check` · `item-info` ·
`signals` (--monitor N) · `monitor` · `watch` (check --json) · `auto-trade` ·
`trade` (log / paper / open / close / positions / **status** / list / pnl /
delete) · **`history`** · `profile` · `diff` · `snapshots` · `config` ·
`dashboard` (--open / --control / --profile). Global: `--profile`,
`--quiet`, `--version`.

## Dashboard routes (full)

GET: `/` · `/api/scan` · `/api/health` · `/api/monitor` · `/api/signals` ·
`/api/trades` · `/api/pnl` · `/api/history` · `/api/prices` · `/api/meta`
(+ control, profile, unread_alerts) · `/api/watchlist` ·
`/api/watchlist/check` · `/api/timeseries` (step/points) · `/api/positions` ·
`/api/trader` · `/api/ge` · `/api/bank` · `/api/process` · `/api/alch` ·
`/api/confidence` · `/api/alerts` · `/api/events` (SSE).

POST (all origin-checked): `/api/trades` · `/api/watchlist`
(add/remove/alerts) · `/api/paper` · `/api/ge/collect` · `/api/positions`
(close, manual only) · `/api/trader` (start/stop, 403 without control) ·
`/api/monitor` (start/stop, 403 without control) · `/api/alerts/read` ·
`/api/trades/delete`.

## Tests (344, 24 files)

New: `tests/test_alerts.py` (11 — push/list/prune/mark-read/dedupe/profile
isolation/atomic-write/failure-silent) and 13 new route tests in
`tests/test_dashboard.py` (alerts, alerts-read, confidence, alch,
watchlist-check, watchlist-alerts action, positions close, trader/monitor
control 403 + start, trades delete, SSE headers, timeseries step).
Updated: `test_dashboard.py` handler signature changes (timeseries arity
fallback), `test_merge_state.py` (alerts.json union).

## Operations notes

- `rshelper dashboard --control` on the Mac enables Start/Stop for the
  trader/monitor from the UI. The launchd trader keeps running as before;
  the state-sync LaunchAgent now also syncs `alerts.json`.
- SSE through Caddy works (read-only GET, `Access-Control-Allow-Origin: *`).
- The live site shows `control: false` in `/api/meta` — daemon control is
  deliberately unavailable remotely.

## Guardrails honored

- Stdlib-only, atomic writes, stdout=data contract, 2% tax via `ge_tax()`,
  margin convention, cache strategy — all unchanged.
- The live trader process/state was never touched during development; all
  tests use temp/monkeypatched paths.
- `--control` defaults off and is documented as trusted-local-only.
