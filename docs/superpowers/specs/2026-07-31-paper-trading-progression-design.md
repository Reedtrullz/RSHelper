# Paper Trading Progression Dashboard — Design

**Status:** approved (2026-07-31)

## Goal

Add a Progression view to the existing RSHelper local web dashboard that shows
paper trading outcomes over time and correlates them with configuration
(tuning) changes, answering: "did changing `min_volume` / `direction` / `top`
improve results?"

## Context (verified against code)

- Stdlib-only Python 3.11 CLI + dashboard. Zero PyPI deps is an invariant.
- Dashboard: `http.server` (`dashboard/server.py`), closure TTL cache,
  inline HTML template (`dashboard/templates.py`), routes in
  `dashboard/handlers.py` (`/api/scan`, `/api/trades`, `/api/pnl`,
  `/api/signals`, `/api/monitor`).
- Data already available:
  - `trades.json`: per-trade `item_id, name, qty, buy_price, sell_price,
    tax_paid, profit, timestamp` (UTC ISO), `note`. Paper trades are logged
    with `note = "paper"` (`cli._trade_paper`).
  - `journal.py`: `compute_pnl()` and `compute_pnl_by_item()` already compute
    totals, win rate, ROI, best/worst, per-item breakdown.
  - `snapshots/`: one JSON file per day per scan type (`alch|flip|margin`),
    each with `date`, `count`, `items`.
  - `config.toml`: effective tuning params (alch/flip/margin sections).
  - Multi-account profiles via `~/.config/rshelper/profiles/<name>/`.

## Approach

Extend the existing dashboard. No new architecture, no new dependencies.

1. New `tuning.py`: effective config params fingerprint + a persisted
   `tuning_log.json` changelog (`ts`, `params`, `note`), written only when
   params actually change. Checked at dashboard startup and whenever a CLI
   scan saves a snapshot.
2. `snapshot.save()` embeds a `config` fingerprint in each snapshot payload
   for retroactive context.
3. New `history.py`: `build_history(profile, paper_only)` joins trades +
   snapshots + tuning log into daily buckets, tuning eras, per-item rows, and
   a summary. Reuses `journal.list_trades` / `compute_pnl` /
   `compute_pnl_by_item` (gaining an optional `note` filter).
4. New `/api/history` route in the dashboard; a Progression toggle in the
   inline template renders Canvas 2D charts and tables (no chart library).

## Data Model

`tuning_log.json` (config dir, atomic writes):

```json
{"entries": [{"ts": "2026-07-31T12:00:00+00:00",
              "params": {"alch": {...}, "flip": {...}, "margin": {...}},
              "note": "auto"}]}
```

`GET /api/history?paper=1|0` response:

```json
{
  "summary": {"total_profit": 0, "win_rate": 0.0, "roi_pct": 0.0,
              "trade_count": 0, "items_traded": 0, "active_days": 0},
  "buckets": [{"date": "2026-07-30", "trade_count": 0, "profit": 0,
               "cumulative_profit": 0, "win_rate": null,
               "avg_profit_per_trade": null,
               "snapshots": [{"scan_type": "flip", "count": 0, "avg_value": null}],
               "config": null, "config_changed": false}],
  "eras": [{"start": "2026-07-31", "end": "2026-07-31", "config": {...},
            "note": "auto", "trade_count": 0, "profit": 0, "win_rate": null,
            "roi_pct": null, "trades_per_day": 0}],
  "items": [{"item_id": 1, "name": "...", "trade_count": 0, "qty": 0,
             "cost_basis": 0, "profit": 0, "roi_pct": 0.0, "win_rate": 0.0}]
}
```

## Progression View

- Summary metrics: total P&L, win rate, ROI, trade count, items traded,
  active days.
- Chart 1: cumulative P&L line, vertical markers at tuning changes, shaded
  era segments.
- Chart 2: daily trade count (bars) + win rate (line), same change markers.
- Tuning eras table: per config change — changed params, trades, profit,
  win rate, ROI, trades/day.
- Per-item table: profit, ROI, win rate, trades.

## Decisions

- Default view: active profile, paper trades only (`note == "paper"`), with a
  toggle for all trades.
- No retroactive tuning history: the first tuning era starts when this ships.
  Snapshots gain a config fingerprint going forward.
- Tuning log entries are recorded at dashboard startup and on CLI snapshot
  saves; any day with a snapshot therefore has a tuning entry.
- Charts use the Canvas 2D API inline; no external assets.

## Non-Goals

- No new CLI commands, no external dashboard, no PyPI dependencies.
- No real-money tracking changes; this is display + correlation only.
- No retroactive reconstruction of past config changes.

## Testing

- `tests/test_tuning.py`: params shape; record on change; skip when
  unchanged; profile isolation; `config_at` day lookup.
- `tests/test_history.py`: daily bucketing + cumulative profit; paper filter;
  snapshot join; config assignment + change flags; era stats.
- `tests/test_journal.py` additions: `note` filter on `list_trades`,
  `compute_pnl`, `compute_pnl_by_item`.
- `tests/test_snapshot.py` addition: saved payload contains `config`
  fingerprint.
- `tests/test_dashboard.py` additions: `/api/history` returns 200 + expected
  keys; Progression toggle and `/api/history` present in `INDEX_HTML`.
- All 14 test files must pass; dashboard smoke-checked with `curl`.

## Files

- Create: `src/rshelper/tuning.py`, `src/rshelper/history.py`,
  `tests/test_tuning.py`, `tests/test_history.py`.
- Modify: `src/rshelper/journal.py`, `src/rshelper/snapshot.py`,
  `src/rshelper/dashboard/handlers.py`, `src/rshelper/dashboard/server.py`,
  `src/rshelper/dashboard/templates.py`, `src/rshelper/cli.py`,
  `tests/test_journal.py`, `tests/test_snapshot.py`,
  `tests/test_dashboard.py`.
