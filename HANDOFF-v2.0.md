# RSHelper Handoff v2.0: Current State (v1.5 + hardening)

You are taking over RSHelper at `/Users/reidar/Documents/RSHelper`, a Python
CLI plus local web dashboard for OSRS Grand Exchange trading. It has grown
from the v0.1 alch scanner into a full trading platform: flip/margin analysis
with confidence scoring, market signals, a daemon monitor, a trade journal,
multi-account profiles, and a dashboard.

**Stdlib only. Python 3.11+ (uses `tomllib`). Venv at `.venv/`.**

## Project State

```
3720 lines of Python
18 source files: __init__, __main__, api, models, analysis, scanner, signals,
                 config, watchlist, snapshot, journal, monitor, profile, cli,
                 dashboard/{__init__, handlers, server, templates}
12 test files, 140 tests, all passing:
  test_analysis (15)  test_cli (16)     test_dashboard (22)  test_integration (4)
  test_journal (14)   test_monitor (8)  test_profile (10)    test_properties (8)
  test_scanner (12)   test_signals (14) test_snapshot (8)    test_watchlist (9)
```

**Git log (HEAD):**
```
cf153a2 hardening: fix remaining stdout leaks, ROI helper, review fixes
f037c05 v1.5: capital efficiency, CLI polish, paper trade workflow
c893bb9 tuning: stderr fix, dashboard RS Score, min_volume defaults
d942665 next-level: wiki URL + price prediction on item-info
ed529f4 next-level: --quiet flag, tax curve optimizer, stderr fix
3ce46a2 audit: resolve all ponytail + Opus hardening findings
b8143d8 v1.0-v1.4: complete RSHelper trading platform
469510d v0.9: hardening, bug fixes, and 17 new tests
```

**CLI surface (13 top-level commands):**
```
rshelper alch-scan     [--nature-rune-cost N] [--members-only] [--min-volume N]
                       [--name X] [--top N] [--json|--csv|--html] [--save-snapshot]
rshelper flip-scan     [--flip-direction traditional|arbitrage] [--members-only]
                       [--min-volume N] [--min-margin N] [--ge-slots N]
                       [--name X] [--top N] [--capital N] [--json|--csv|--html]
                       [--save-snapshot]
rshelper margin-check  [--flip-direction ...] [--members-only] [--min-volume N]
                       [--min-margin N] [--name X] [--check N] [--top N]
                       [--capital N] [--ge-slots N] [--workers N] [--risk]
                       [--json|--csv] [--save-snapshot]
rshelper item-info     <name-or-id> [--timeseries] [--tax-curve] [--wiki]
                       [--wiki-open] [--predict] [--json]
rshelper signals       [--members-only] [--flip-direction ...] [--cooldown N] [--json]
rshelper monitor       [--interval N] [--no-notify] [--stop] [--status]
rshelper watch         add <item> [--alert-above N] [--alert-below N] | remove <id>
                       | list | check [--flip-direction ...] [-v]
rshelper trade         log <item> <qty> <buy> <sell> [--note] | paper <item>
                       [qty] [--capital N] [--flip-direction ...] [--note]
                       | list [--item] [--since] [--top] [--json|--csv]
                       | pnl [--since] [--by-item] [--json] | delete <id>
rshelper profile       create|switch|list|delete <name> [--force]
rshelper diff          [alch|flip|margin] [--date YYYY-MM-DD]
rshelper snapshots     [alch|flip|margin]
rshelper config        show | path
rshelper dashboard     [--bind BIND] [--port PORT]
```

Global flags: `--profile NAME`, `--quiet`, `--version`.

## Architecture Decisions — DO NOT REGRESS

### GE tax: 2%, capped at 5M per item
Applied on the sell side everywhere (scanner, analysis, journal, monitor,
watch, CLI tax curve). The OSRS Wiki raised the tax from 1% to 2% on
29 May 2025. **The `1%` lines in `research/*` are stale** — see the banners at
the top of those files. Do not change the rate back.

### Margin convention
`buy_price = API "high"` (instant-buy), `sell_price = API "low"`
(instant-sell). The `direction` parameter on `FlipScanner` and
`analyze_timeseries` decides which way to compute the margin, not which API
field maps to which price. `--flip-direction arbitrage` finds `low > high`
windows; `traditional` is standard buy-bid/sell-offer flipping.

### Confidence model
- `MarginAnalysis.reliability` (0-1): consistency of the margin pattern
  (margin_consistency 40%, spread 15%, volume 20%, volatility 25%).
- `profitability_score` (0-1): 60% historical ROI sigmoid + 40% current ROI
  sigmoid, floored at 0.
- `confidence = reliability x profitability x recency x trend`, clamped to
  [0, 1]. `MarginScanner` sorts by `expected_gp_per_hour =
  confidence x current_profit x throughput`.

### Cache strategy
Fresh cache -> live API -> stale fallback (up to 3x max age). Never serve
stale ahead of a network attempt. Atomic writes (temp file + `os.replace`).
Cache dir `~/.cache/rshelper/` with 0600 perms.

### stdout / stderr contract
stdout is data only (table, JSON, CSV, HTML, primary output). All status,
fetch, progress, and error messages go to stderr. This is the most-regressed
invariant; the v1.5 + hardening rounds eliminated the last leaks, and the
progress `\r` in margin-check now writes to stderr.

### Trade size
`min(buy_limit, capital // buy_price, max(1, volume * 12))`; returns 0 for
zero-volume items. `trade paper` sizes from `--capital` when `qty` is omitted.

### Multi-account profiles
`~/.config/rshelper/active_profile` (empty/missing = "default"). Default
profile uses legacy paths; other profiles isolate under
`~/.config/rshelper/profiles/<name>/` and `~/.cache/rshelper/profiles/<name>/`.
All path-constructing functions take `profile: str | None = None`.

### Defaults tuned for paper trading
`flip` and `margin` sections default `min_volume = 10` (was 0) so vol <= 5
items don't pollute results. `--members-only` uses `BooleanOptionalAction`
and honors `config.toml` (E26 residual closed in v1.5). Flip output includes
`roi` (`profit / buy_price`) and `capital_per_unit` in JSON/CSV and an ROI%
column in the table/HTML so capital-heavy items are not misleading.

## What Each Version Built (history, not regress list)

- v0.1-v0.3: alch scanner, API client, caching, flip/margin analysis.
- v0.4-v0.9: reliability x profitability split, direction-aware margins,
  parallel fetch, HTML export, snapshots/diff, watchlist, 60+ tests.
- v1.0-v1.4 (commit `b8143d8`): dashboard server, signals + RS Score,
  daemon monitor with macOS notifications, trade journal, multi-account
  profiles. 133 tests.
- v1.5 (`f037c05`): ROI/capital output, `--version`, config booleans, alch
  CSV on `asdict`, `trade paper`, journal validation, dashboard Trades view,
  `dashboard` subcommand wired into the real CLI.
- hardening (`cf153a2`): last stdout leaks to stderr, `_roi_pct()` helper,
  test hygiene (temp dirs, dynamic version assertion), Opus review triage.
- paper trading round (`747d8b1`): ROI/cost basis in P&L, `pnl --by-item`
  per-item breakdown, `trade paper --flip-direction` (traditional mode),
  and `--profile` threaded through trade log/list/delete (was split-brain:
  pnl read the alt ledger while log/list wrote the default).

## Remaining Sharp Edges

1. `_filter_by_name` returns the original list objects; a caller that mutates
   filtered results mutates the scan output. Not a current bug.
2. `fetch_timeseries` serves stale cache silently on API failure (by design:
   stale beats nothing for history); the note goes to stderr.
3. HTML sort strips commas before `parseFloat`; basic but functional.
4. `--quiet` replaces `sys.stderr` with `os.devnull` without restoring it —
   fine for one-shot CLI processes.
5. Journal `trade log` looks up `item_id` from mapping by exact name; a
   renamed/unmatched item logs with `item_id = 0`.
6. `detect_signals` DUMP/CRASH compare current sell price against the 5m
   average only; no 1h baseline. Known ceiling, documented in `signals.py`.

## Verification Gates

1. All 12 test files pass: `for f in tests/test_*.py; do .venv/bin/python "$f"; done`.
2. Smoke every touched subcommand against the live Wiki API.
3. `--json` output pipes through `json.tool` with clean stderr.
4. Config round-trip: delete `~/.config/rshelper/config.toml`, run any scan,
   verify defaults are recreated (flip/margin `min_volume = 10`).
5. Watchlist/trades/snapshots state files stay valid JSON with atomic writes.
6. Every new flag or command ships with at least one unit test and one smoke.
7. Larger rounds: `$anti` sidecar review on the diff; triage every finding
   locally before editing (see AGENTS.md).

## Working with $anti

The gateway runs at `http://127.0.0.1:51122/v1`. Useful invocations:
```bash
python3 ~/.codex/skills/anti/scripts/anti.py smoke
python3 ~/.codex/skills/anti/scripts/anti.py review --model opus --scope diff --base HEAD~2
python3 ~/.codex/skills/anti/scripts/anti.py workflow review-ready --scope staged
```
Default review model is `opus` (claude-opus-4-6). Anti output is advisory:
verify findings locally before fixing, and record skipped items.

## Commit and Log

```bash
cd /Users/reidar/Documents/RSHelper
git add -A
git commit -m "v1.x: <summary>"   # or "hardening: <summary>"
```

Log the commit SHA, test counts, and key decisions to today's Obsidian daily
note under `## Log` (`- HH:MM — [[Personal/Projects/RSHelper|RSHelper]] — ...`).
Update `Personal/Projects/RSHelper.md` with a new version section. Vault:
`/Users/reidar/Obsidian/Hermes/Hermes/`.
