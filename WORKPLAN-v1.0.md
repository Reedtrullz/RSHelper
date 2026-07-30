# RSHelper v1.0–v1.4 Work Plan

> Generated 2026-07-29 from competitive intelligence research across 16 OSRS
> GE tools. Each phase is self-contained and shippable. Phases are sequenced:
> each builds on the previous. Tests are specified per-module, not per-function.
> All code is Python stdlib only, per project constraint.

---

## Phase Map

| Version | Theme | New Files | Modified Files | Est. Tests |
|---|---|---|---|---|
| v1.0 | Dashboard + Polish | 0 | `cli.py` | 83→83 |
| v1.1 | Signals + RS Score | `signals.py`, `test_signals.py` | `scanner.py`, `cli.py`, `models.py`, `dashboard/*` | 83→100+ |
| v1.2 | Daemon Monitor | `monitor.py`, `test_monitor.py` | `cli.py`, `dashboard/*` | 100→115+ |
| v1.3 | Trade Journal | `journal.py`, `test_journal.py` | `cli.py`, `dashboard/*` | 115→135+ |
| v1.4 | Multi-Account Profiles | `test_profiles.py` | `config.py`, `cli.py`, `api.py`, `watchlist.py`, `snapshot.py`, `journal.py` | 135→155+ |

---

## v1.0 — Dashboard + Polish

### Objective
Ship the dashboard built in the working tree. Fix remaining sharp edges from
the HANDOFF audit. Commit clean.

### Tasks

**T1.1 — Fix `_out_pending` initialization**
- File: `src/rshelper/cli.py`, function `item_info()`
- Add `_out_pending = None` before the `if args.json:` / `else:` branch
- Change deferred print guard to `if args.json and _out_pending is not None:`
- Effort: 3 lines. No new tests needed.

**T1.2 — Verify all tests pass**
```bash
for f in tests/test_*.py; do .venv/bin/python "$f"; done
```
Already confirmed: 83 tests green as of 2026-07-29.

**T1.3 — Review Anti panel findings**
Confirmed locally:
- `FlipScanner` removal from `watch_check`: safe (dead code)
- `diff_cmd` format change: intentional fix for doubled `++`
- Stderr redirects: no test regressions
- Dashboard `--bind` warning: already handled in `server.py`

**T1.4 — Commit**
```bash
git add -A
git commit -m "v1.0: dashboard, stderr polish, and CLI fixes"
```

### Completion Gate
- [ ] `_out_pending` initialized before branch
- [ ] All 83 tests pass
- [ ] `rshelper dashboard --help` prints usage
- [ ] `rshelper dashboard` starts server and prints URL
- [ ] Committed with clean working tree

---

## v1.1 — Intelligence Release: Signals + RS Score

### Objective
Add the two highest-impact competitive features: a signal detection engine
(DUMP/CRASH/SURGE/FLIP alerts, modeled on Varrock Observer) and a unified
RS Score (0–100, modeled on 07Flip + GrandExchanger scoring).

### New Module: `src/rshelper/signals.py`

**Signal dataclass:**
```python
@dataclass
class Signal:
    type: str       # "DUMP" | "CRASH" | "SURGE" | "FLIP" | "STALE"
    item_id: int
    name: str
    severity: str   # "HIGH" | "MEDIUM" | "LOW"
    current_price: int
    deviation: float  # percentage
    message: str     # e.g. "Zulrah's scales: -14.3% below 1h avg"
```

**Signal types and detection thresholds:**

| Signal | Condition | Severity | Cooldown |
|---|---|---|---|
| DUMP | sell price >10% below 1h avg, volume >100 | MEDIUM | 15 min |
| CRASH | sell price >20% below 1h avg, volume >100 | HIGH | 15 min |
| SURGE | 5m volume >3x 1h baseline | MEDIUM | 15 min |
| FLIP | spread >5% of buy price, volume >500 | varies by RS Score | 15 min |
| STALE | latest data timestamp >30 min old | LOW | none |

**Core function:**
```python
def detect_signals(
    items: list[Item],
    latest_prices: dict[str, dict],
    prices_1h: dict[str, dict],
    volume_5m: dict[str, dict],
    cooldown_minutes: int = 15,
) -> list[Signal]:
```

**Cooldown state:** `~/.config/rshelper/signal_cooldowns.json`
- Per (item_id, signal_type) pair, stores last fire timestamp.
- Atomic writes via temp file + os.replace.

### RS Score

**Add to `Item` dataclass** (`src/rshelper/models.py`):
```python
rs_score: float = 0.0  # 0–100 composite flip quality score
```

**FlipScanner** (`src/rshelper/scanner.py`):
- Compute per-item: volume score (40%) + volatility proxy (30%) + spread quality (20%) + freshness (10%)
- Same weighting as 07Flip confidence score. No timeseries needed.
- Formula: `min(100, vol_ratio * 40 + 0.7 * 30 + spread_qual * 20 + 10)`

**MarginScanner:** already has `confidence` (0–1). Scale: `analysis.confidence * 100`.

**AlchScanner:** use percentile rank of gp_per_hour within results.

**Display:** Add RS Score column to all terminal tables, JSON keys, CSV columns,
HTML tables, and the dashboard.

### CLI: `rshelper signals`

```
rshelper signals [--members-only] [--json] [--cooldown N]
```

Output groups signals by type, ordered by severity (HIGH → MEDIUM → LOW):

```
  Signals (3 active, cooldown: 15 min)

  CRASH — Severe price drops
  ----------------------------------------------------------------------
  Severity  Item                  Price    1h Avg   Drop     Suggested
  HIGH      Zulrah's scales        142       195   -27.2%   Buy at 140-145
  MEDIUM    Dragon bones         2,847     3,200   -11.0%   Buy at 2,800-2,850

  FLIP — Wide margins with liquidity
  ----------------------------------------------------------------------
  Severity  Item                  Margin   ROI    Volume   RS Score
  HIGH      Nature rune              12   9.2%   482,000       87
  MEDIUM    Prayer potion(4)      1,247   8.5%    12,400       72
```

### Dashboard

- New route: `/api/signals` — returns active signals as JSON
- Table: add RS Score column, sort option
- Controls: add "RS Score" sort option

### Tests: `tests/test_signals.py` (17 new tests)

| Test | What it verifies |
|---|---|
| `test_dump_detection` | 10% below 1h avg triggers DUMP |
| `test_crash_detection` | 20% below triggers CRASH |
| `test_surge_detection` | 3x volume triggers SURGE |
| `test_flip_detection` | 5% spread + volume triggers FLIP |
| `test_stale_detection` | Old timestamp triggers STALE |
| `test_cooldown_suppression` | Signal suppressed within cooldown |
| `test_cooldown_expiry` | Signal fires after cooldown |
| `test_no_false_positives` | Normal data produces no signals |
| `test_empty_input` | Empty items → empty signals |
| `test_signal_serialization` | Signal → dict roundtrip |
| `test_rs_score_in_flip_scanner` | RS Score computed, in [0, 100] |
| `test_rs_score_in_margin_scanner` | Confidence → RS Score scaling |
| `test_rs_score_in_alch_scanner` | Percentile rank computed |
| `test_rs_score_in_json_output` | `--json` includes `rs_score` |
| `test_rs_score_in_csv_output` | `--csv` includes rs_score column |
| `test_signals_cli_parse` | CLI args parse correctly |
| `test_signals_cli_output` | Command exits 0, produces valid output |

### Completion Gate
- [ ] `rs_score` field on all Item outputs
- [ ] `rshelper signals` command runs with table output
- [ ] Signal cooldowns prevent duplicate alerts
- [ ] Dashboard `/api/signals` endpoint returns JSON
- [ ] Dashboard table shows RS Score column
- [ ] 100+ tests pass (83 existing + ~17 new)
- [ ] No regressions on any existing subcommand

---

## v1.2 — Daemon Monitor

### Objective
Turn RSHelper from a "run it when you remember" tool into an always-on
companion. Background polling loop with macOS notifications for signals
and watchlist triggers.

### New Module: `src/rshelper/monitor.py`

```python
def notify(title: str, message: str) -> None:
    """Fire a macOS notification via osascript."""

def run_monitor(interval_sec: int = 120, no_notify: bool = False) -> None:
    """Main loop: fetch prices, detect signals, check watchlist, notify."""

def stop_monitor() -> bool:
    """Kill running monitor by PID file."""

def monitor_status() -> dict | None:
    """Return {running, pid, uptime_sec, last_check_iso} or None."""
```

**Monitor loop:**
```
while True:
    1. Fetch mapping + latest + 5m + 1h via _fetch_bootstrap()
    2. detect_signals() — fire notification for each new signal
    3. Check watchlist thresholds — fire for triggers
    4. Write last_check timestamp + signal_count to state file
    5. sleep(interval_sec)
```

**PID file:** `~/.config/rshelper/monitor.pid` — contains process PID.
**State file:** `~/.config/rshelper/monitor_state.json` — `{pid, started_iso, last_check_iso, profile}`.

### CLI: `rshelper monitor`

```
rshelper monitor [--interval N] [--no-notify]
rshelper monitor --stop
rshelper monitor --status
```

`--status` output:
```
  Monitor: RUNNING
  PID: 42891
  Running since: 14:32:01 (47 min ago)
  Last check: 14:38:45
  Last signals: 3 (1 CRASH, 2 FLIP)
```

### Dashboard

- Route: `/api/monitor` → `{running, pid, uptime_sec, last_check_iso, last_signal_count}`
- Footer: green/grey status dot next to refresh indicator

### Tests: `tests/test_monitor.py` (8 new tests)

| Test | What it verifies |
|---|---|
| `test_notify_command_format` | osascript string is well-formed |
| `test_pid_file_roundtrip` | Write PID, read it back |
| `test_stop_monitor_no_pid` | Returns False when no PID file |
| `test_monitor_status_none` | Returns None when not running |
| `test_signal_state_new_vs_repeat` | New signals fire, repeated ones don't |
| `test_monitor_cli_args` | --interval, --stop, --status, --no-notify parse |
| `test_monitor_loop_survives_api_error` | Exception logged, loop continues |
| `test_monitor_cli_help` | --help exits 0 |

### Completion Gate
- [ ] `rshelper monitor` starts, polls, logs to stderr
- [ ] `rshelper monitor --status` shows running state
- [ ] `rshelper monitor --stop` kills running monitor
- [ ] macOS notifications fire on new signals and watchlist triggers
- [ ] Monitor survives API errors (logs, retries)
- [ ] Dashboard shows monitor status indicator
- [ ] 115+ tests pass

---

## v1.3 — Trade Journal

### Objective
Close the feedback loop: log trades, see realized P&L. Modeled on Flipping
Utilities' trade log and 07Flip's P&L tracker, CLI-first.

### New Module: `src/rshelper/journal.py`

```python
@dataclass
class Trade:
    id: int
    item_id: int
    name: str
    qty: int
    buy_price: int       # per unit
    sell_price: int      # per unit
    tax_paid: int        # computed: max(1, int(sell_price * qty * 0.02))
    profit: int          # computed: (sell - buy) * qty - tax_paid
    timestamp: str       # ISO 8601
    note: str = ""

@dataclass
class PnLSummary:
    total_profit: int
    total_tax_paid: int
    trade_count: int
    winning_trades: int
    losing_trades: int
    win_rate: float            # 0–100
    best_trade: Trade | None
    worst_trade: Trade | None
    active_gp_per_hour: float  # profit / hours between first and last trade
    items_traded: int          # unique items

def log_trade(item_id, name, qty, buy_price, sell_price, note="") -> Trade: ...
def delete_trade(trade_id: int) -> bool: ...
def list_trades(item_name=None, since=None, top=0) -> list[Trade]: ...
def compute_pnl(since=None) -> PnLSummary: ...
```

**State file:** `~/.config/rshelper/trades.json` — `{"trades": [...]}`, atomic writes.
Trade IDs are sequential integers starting from 1.

### CLI

```
rshelper trade log <item> <qty> <buy_price> <sell_price> [--note "..."]
rshelper trade list [--item X] [--since YYYY-MM-DD] [--top N] [--json] [--csv]
rshelper trade pnl [--since YYYY-MM-DD] [--json]
rshelper trade delete <id>
```

PNL terminal output:
```
  P&L Summary (all time)
  ═══════════════════════════════════════
  Total profit:     +12,847,000 gp
  Total tax paid:      262,000 gp
  Trades:                   47
  Win rate:               78.7%
  Best trade:      Dragon claws  (+1,247,000 gp)
  Worst trade:     Zulrah's scales (-43,000 gp)
  Items traded:              12
  Active gp/hr:        847,000 gp
```

### Dashboard

- `POST /api/trades` — log a trade
- `GET /api/trades` — list trades
- `GET /api/pnl` — P&L summary
- Optional "Trades" panel with recent trades and P&L card

### Tests: `tests/test_journal.py` (14 new tests)

| Test | What it verifies |
|---|---|
| `test_log_trade` | Create trade, verify fields, auto-increment ID |
| `test_log_trade_zero_profit` | buy=sell, profit is negative (tax) |
| `test_log_trade_tax_calculation` | 2% capped at 5M per item |
| `test_delete_trade_exists` | Delete existing trade |
| `test_delete_trade_nonexistent` | Returns False |
| `test_list_trades_empty` | Returns [] |
| `test_list_trades_filtered_by_item` | Only matching items |
| `test_list_trades_filtered_by_date` | Since filter works |
| `test_atomic_save_no_corruption` | Interrupted write doesn't corrupt |
| `test_pnl_mixed_wins_losses` | win_rate computed correctly |
| `test_pnl_empty_ledger` | Zeroes, no crash |
| `test_pnl_gp_per_hour` | Trades over 2h span → active gp/hr |
| `test_cli_trade_log_parse` | Args parse, correct Trade created |
| `test_cli_trade_pnl_output` | Exits 0, valid output |

### Completion Gate
- [ ] `rshelper trade log "Nature rune" 10000 118 130` logs a trade
- [ ] `rshelper trade list` shows trades in a table
- [ ] `rshelper trade pnl` shows computed P&L
- [ ] `rshelper trade delete 1` removes a trade
- [ ] JSON/CSV export works for trades
- [ ] Dashboard trade endpoints return valid JSON
- [ ] 135+ tests pass

---

## v1.4 — Multi-Account Profiles

### Objective
Support multiple OSRS accounts (main + alt). Each profile gets isolated
config, watchlist, trades, snapshots, and cache.

### Architecture

**Directory layout:**
```
~/.config/rshelper/
  config.toml              ← "default" profile (backward compatible)
  watchlist.json
  trades.json
  snapshots/
  active_profile           ← plain text: current profile name or empty
  profiles/
    alt/
      config.toml
      watchlist.json
      trades.json
      snapshots/

~/.cache/rshelper/
  mapping.json             ← "default" profile cache
  latest.json
  5m.json
  profiles/
    alt/
      mapping.json
      latest.json
      5m.json
```

**Active profile resolution:**
- Read `~/.config/rshelper/active_profile`. Empty/missing → "default".
- "default" profile uses legacy paths directly.
- All path-constructing functions accept optional `profile` kwarg.
- When `profile` is None, use active profile.

**Modified modules:**
- `config.py` — config_path(profile=None)
- `watchlist.py` — WATCHLIST_PATH resolved per profile
- `snapshot.py` — snapshot_dir per profile
- `api.py` — cache_dir per profile
- `journal.py` — trades_path per profile
- `monitor.py` — state files per profile

### CLI

```
rshelper profile create <name>
rshelper profile switch <name>
rshelper profile list
rshelper profile delete <name> [--force]

rshelper --profile <name> <command>     ← override for one command
```

Profile names: alphanumeric, dashes, underscores. Max 32 chars.

### Dashboard
- `run()` accepts optional `profile` parameter
- Dashboard startup logs active profile name
- All API endpoints use active profile's data

### Tests: `tests/test_profiles.py` (10 new tests)

| Test | What it verifies |
|---|---|
| `test_default_profile_no_file` | Missing active_profile → "default" |
| `test_profile_switch_readback` | Write profile name, read it back |
| `test_create_profile_creates_dirs` | Dirs exist after create |
| `test_delete_profile_removes_dirs` | Dirs gone after delete |
| `test_profile_watchlist_isolation` | Two profiles, separate watchlists |
| `test_profile_cache_isolation` | Two profiles, separate caches |
| `test_profile_trade_isolation` | Two profiles, separate trade ledgers |
| `test_profile_cli_create_switch` | CLI args parse correctly |
| `test_global_profile_flag` | `--profile alt flip-scan` parses |
| `test_default_profile_backward_compat` | Legacy paths still work without profiles |

### Completion Gate
- [ ] `rshelper profile create alt` creates dirs
- [ ] `rshelper profile switch alt` changes active profile
- [ ] `rshelper --profile alt watch list` uses alt's watchlist
- [ ] Config, watchlist, trades, snapshots, cache isolated per profile
- [ ] "default" profile uses legacy paths (backward compatible)
- [ ] All existing commands work without `--profile` (backward compatible)
- [ ] 155+ tests pass

---

## Cross-Cutting Concerns

### Testing
- All tests use stdlib `unittest` — matching existing pattern
- Integration tests (network) go in `tests/test_integration.py`
- Run-all: `for f in tests/test_*.py; do .venv/bin/python "$f"; done`
- Target: zero failures, zero regressions per phase

### Documentation
- Update `HANDOFF-v1.0.md` after each phase with new version section
- Update `README.md` with new subcommands as they ship

### Commit Convention
```
v1.0: dashboard, stderr polish, and CLI fixes
v1.1: signal detection engine and RS Score
v1.2: daemon monitor with desktop notifications
v1.3: trade journal and P&L tracking
v1.4: multi-account profile support
```

### Ponytail Constraints (Active Throughout)
- Zero external dependencies — stdlib only
- One assert-based self-check or test file per new module
- No abstractions without two concrete use cases
- `ponytail:` comments for known ceilings with documented upgrade paths
- Deletion over addition — fix root causes, not symptoms

---

## Competitive Positioning Summary

Each phase addresses a specific competitive gap identified in the landscape
analysis:

| Phase | Feature | Competitive Gap Filled |
|---|---|---|
| v1.0 | Dashboard + polish | Bridges CLI and web. No other tool offers local server + CLI dual-mode. |
| v1.1 | Signals + RS Score | Matches the composite scoring and event-driven alerts that distinguish top web tools (07Flip, Varrock Observer). No CLI competitor has either. |
| v1.2 | Daemon Monitor | Always-on passive monitoring. GE Hound/Varrock Observer do this via Discord — RSHelper does it locally. |
| v1.3 | Trade Journal | Closes the P&L feedback loop. Flipping Utilities (132k users) and 07Flip offer this — nobody in CLI does. |
| v1.4 | Multi-Account Profiles | Unique across all categories. Even web trackers rarely support profile switching. |

**What RSHelper deliberately does NOT compete on:**
- Public web service (GE Margin has won "free forever" positioning)
- RuneLite plugin (Flipping Utilities has 132k+ installs, crowded market)
- More calculators (GE Margin has 17, catching up is low-value)
- AI/ML price prediction (API data isn't high-resolution enough)

**RSHelper's defensible niche:** the most capable OSRS trading CLI in existence,
with a companion local web dashboard — running entirely on your own machine with
zero external dependencies.
