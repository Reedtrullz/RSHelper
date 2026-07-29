# RSHelper v1.0 Handoff: From CLI Tool to Trading Platform

You are taking over RSHelper at `/Users/reidar/Documents/RSHelper`, a Python CLI
tool for Old School RuneScape Grand Exchange profit scanning. The codebase has
gone through four rounds of development (v0.4→v0.9) totaling 3001 lines of
Python across 10 source files and 7 test files. **61 tests pass offline; 4
integration tests pass with network.**

**No external dependencies beyond Python stdlib.** Python 3.14, venv at `.venv/`.

## Project State

```
3001 lines of Python
10 source files: __init__, __main__, models, api, analysis, scanner, cli, config, snapshot, watchlist
7 test files: test_scanner (12), test_analysis (15), test_cli (9), test_integration (4),
              test_properties (8), test_snapshot (8), test_watchlist (9)
61 offline tests + 4 network tests, all passing
```

**Git log:**
```
469510d v0.9: hardening, bug fixes, and 17 new tests
6cb0222 v0.8: diff/trend snapshots, status→stderr polish
9210758 v0.7: parallel fetch, HTML export, risk metrics, and sharp edge fixes
ce32942 v0.6: watchlist, config commands, GE slots, direction fix, sub-scores, and 20 new tests
586d4df v0.5: Phase 3 features + Opus review fixes
06c52db v0.4: deep audit, hardening, and real-trading readiness improvements
65f93a5 v0.1: Alch-profit scanner with OSRS Wiki API client
```

**CLI surface (8 subcommands):**
```
rshelper alch-scan     [--nature-rune-cost N] [--members-only] [--min-volume N]
                       [--name X] [--top N] [--json] [--csv] [--html]
                       [--save-snapshot]
rshelper flip-scan     [--flip-direction traditional|arbitrage] [--members-only]
                       [--min-volume N] [--min-margin N] [--ge-slots N]
                       [--name X] [--top N] [--capital N] [--json] [--csv]
                       [--html] [--save-snapshot]
rshelper margin-check  [--flip-direction traditional|arbitrage] [--members-only]
                       [--min-volume N] [--min-margin N] [--name X] [--check N]
                       [--top N] [--capital N] [--ge-slots N] [--workers N]
                       [--risk] [--json] [--csv] [--save-snapshot]
rshelper item-info     <name-or-id> [--timeseries] [--json]
rshelper watch         {add,remove,list,check}
rshelper diff          [alch|flip|margin] [--date YYYY-MM-DD]
rshelper snapshots     [alch|flip|margin]
rshelper config        {show,path}
```

Config at `~/.config/rshelper/config.toml` (auto-created, `[alch]`/`[flip]`/`[margin]`).
Cache at `~/.cache/rshelper/` (0600 perms). Watchlist at `~/.config/rshelper/watchlist.json`.
Snapshots at `~/.config/rshelper/snapshots/`.

Run tests:
```bash
cd /Users/reidar/Documents/RSHelper && for f in tests/test_*.py; do .venv/bin/python "$f"; done
```

Run CLI:
```bash
cd /Users/reidar/Documents/RSHelper && PYTHONPATH=src .venv/bin/python -m rshelper <command>
```

## Architecture Decisions — DO NOT REGRESS

### Margin convention
`buy_price = API "high"` (instant-buy), `sell_price = API "low"` (instant-sell).
Consistent across the codebase. The `direction` parameter on FlipScanner and
analyze_timeseries decides which way to compute the margin, not which API field
maps to which price.

### Confidence model
Split into `reliability` × `profitability_score` on `MarginAnalysis`.
- **Reliability** (0-1): weighted composite of margin_consistency (40%), spread_score (20%),
  volume_score (20%), volatility_score (20%). Ignores profitability direction —
  a "reliable loser" still scores high here.
- **Profitability** (0-1): shifted sigmoid `2*sigmoid(avg_margin/125)-1`, giving 0 at margin=0.
- **Confidence** = reliability × profitability_score. A reliable loser gets near-zero.
- **Sub-scores** exposed: `spread_score`, `volume_score`, `volatility_score` on MarginAnalysis.

### Cache strategy
Fresh → API → stale fallback. Never serve stale data ahead of a network attempt.
`_load_cache` returns only fresh data; `_load_stale_cache` is only called on API failure.
Cache dir is `~/.cache/rshelper/` with 0600 perms. Atomic writes (temp file + os.replace).

### Trade size formula
`min(buy_limit, capital // buy_price, max(1, volume * 12))`.
`max(1, ...)` ensures at least 1 unit even when volume data is missing.

### No external dependencies
Everything is stdlib. This is deliberate. Do not add `requests`, `pandas`, `rich`, `click`,
or any PyPI package. Python 3.11+ required (uses `tomllib`).

### Status messages → stderr
All fetch/bootstrap/progress messages go to stderr. This keeps stdout clean for JSON,
CSV, and HTML piping. The `_fetch_bootstrap()` shared helper uses stderr exclusively.

## What Each Version Built — DO NOT REGRESS

### v0.4 (core hardening)
Split confidence model into reliability × profitability. Fixed "reliable loser" scoring.
Margin volatility now measures margin CV instead of sell-price CV. FlipScanner direction
(arbitrage vs traditional). Retry with exponential backoff on 429/503.

### v0.5 (Phase 3 features)
Config file at `~/.config/rshelper/config.toml` with `tomllib`. `--capital N` trade sizing.
Five Opus-reviewed defect fixes: D1 max() crash guard, D2 flip margin sign consistency,
D3 stale cache separation, D4 cache path security (no more /tmp), D5 unlink guard.
Shared `_fetch_bootstrap()` de-duplicated 4 fetch chains.

### v0.6 (Phase 1-2 Opus plan items)
- Sub-scores exposed on MarginAnalysis (spread_score, volume_score, volatility_score)
- Config show/path commands
- Direction gap fix: `analyze_timeseries()` is now direction-aware, threaded through MarginScanner
- `--ge-slots N` flag replacing hardcoded `/2` halving
- Integration test (4 tests, skip offline), E2E CLI tests (9), property-based fuzz (8 tests, 5000 trials each)
- Watchlist: atomic JSON state file, add/remove/list/check, alert thresholds, exit code 1 on triggers

### v0.7 (Phase 3b-4)
- Parallel timeseries fetching: ThreadPoolExecutor, thread-safe throttle via threading.Lock,
  `--workers N` flag (default 4)
- HTML export: `--html` flag, self-contained sortable tables with inline CSS/JS
- Risk metrics: `--risk` flag on margin-check (Worst + Stability columns)
- Sharp edge fixes: fetch_mapping preemptive unwrap, stale cache → stderr,
  CSV uses dataclasses.asdict(), thread-safe rate limiter

### v0.8 (Phase 3b features)
- Diff/trend: JSON snapshots at `~/.config/rshelper/snapshots/`, `--save-snapshot` flag,
  `rshelper diff [scan-type] [--date]`, `rshelper snapshots [scan-type]`
- All status messages routed to stderr for clean piping

### v0.9 (hardening)
- Bug fix: snapshot diff now correctly handles both `profit` (alch/flip) and `avg_margin` (margin)
  keys — autodetects the value key from the first item
- Bug fix: `load()` includes today's snapshots; diff uses separate previous-day logic
- Bug fix: watch_add status → stderr
- 17 new tests: 9 watchlist + 8 snapshot

## Remaining Sharp Edges

### 1. Config boolean fields aren't wired (E26 residual)
`members_only` exists in the TOML config dataclasses but can't be set to True from config
because argparse `store_true` defaults to False and doesn't support dynamic defaults.
Fix: switch to `--members/--no-members` flags or use `BooleanOptionalAction`.

### 2. `_filter_by_name` returns original list objects
The filter creates a new list comprehension `[r for r in results if ...]` with references
to the same Item/MarginAnalysis objects. If a caller mutates filtered results, it mutates
the original scan output. Not a current bug, but fragile.

### 3. Alch-scan CSV still uses hand-rolled field map
Unlike flip-scan and margin-check which were migrated to `dataclasses.asdict()`, the
alch-scan CSV path still uses the old lambda-based field map. If Item field names change,
the CSV silently produces wrong values.

### 4. Timeseries batch progress collision
`print(..., end="\r")` in the parallel fetch progress callback still uses stdout, and
cache hit messages from `fetch_timeseries` (via `_load_cache`) can break the progress
line. The stale cache messages were moved to stderr, but cache-hit silence means
concurrent workers accessing cache don't produce output — mostly fine now.

### 5. `_get()` retry loop re-runs `_throttle()` on each attempt
For 3 retries at 2s/4s/8s backoff delays, the throttle sleep is redundant — the backoff
already spaces requests. Low priority, but wastes time on retries.

### 6. `fetch_timeseries` returns stale cache silently when API fails
Unlike `fetch_latest`/`fetch_5m` which check fresh first, `fetch_timeseries` checks
`_load_cache` (fresh) then falls through to `_load_stale_cache`. The stale message now
goes to stderr via v0.7 fix, but the behavior is: if the API is down, you get stale
timeseries data without an explicit warning in the output. The stale-cache note appears
on stderr but the data is silently included in results. This is by design (better stale
than nothing for timeseries analysis), but worth documenting.

### 7. Ponytail debt markers
Two remaining `ponytail:` comments in [scanner.py](/Users/reidar/Documents/RSHelper/src/rshelper/scanner.py):
- Line 41: `item.volume * 12  # ponytail: 5-min volume → hourly` — crude but functional.
- Line 151: `# ponytail: default ge_slots=2 for buy+sell; use --ge-slots N to adjust`
Both have known ceilings and documented upgrade paths. Not bugs.

### 8. Margin-check outputs "Fetching OSRS Wiki prices..." twice
`_fetch_bootstrap()` prints this, and the stale cache cleanup also prints messages.
When cache is fresh, you see the "Fetching..." line once. Fine, but the output could
be cleaner by collapsing duplicate messages.

### 9. HTML sort breaks on comma-formatted numbers
The JS sort regex `replace(/[,\s]/g, "")` strips commas, but `parseFloat` on values
like "1,317,000" → 1317000 works correctly. Edge case: negative numbers like "-1,000"
parse correctly (`-1000`). The sort is basic but functional.

### 10. No `--version` flag
There's no `rshelper --version` output. Versions are only tracked in git tags/commits.
A `__version__` constant and `--version` flag would help users verify what they're running.

## Next-Level Ideas

### A. Real-time GE monitor (daemon mode)
A `rshelper monitor` command that runs as a background process, fetches prices every
2 minutes, checks the watchlist, and sends desktop notifications (via `osascript` on
macOS) when alerts trigger. This turns RSHelper from a scan-then-check tool into a
genuine trading companion.

Architecture: simple polling loop with `time.sleep(120)`, re-fetch latest prices,
recompute margins, compare to watchlist thresholds, fire notifications.

### B. Trade journal / P&L tracking
A `rshelper trade log <item> <qty> <buy_price> <sell_price>` command that records
trades to a JSON ledger. `rshelper pnl` shows realized P&L, win rate, best/worst trades.
This closes the loop from "find opportunity" to "measure outcome."

### C. Multi-account support
OSRS players often have alts. A `--profile` flag that switches config/cache/watchlist
directories per account: `~/.config/rshelper/profiles/main/`, `~/.config/rshelper/profiles/alt/`.
`rshelper profile switch <name>` or `rshelper --profile alt flip-scan`.

### D. OSRS Wiki price alert integration
The OSRS Wiki has a "price alerts" page. An `rshelper alert-web` command that
generates a URL or opens the browser to set up wiki-side alerts for watched items,
bridging the CLI and web tooling.

### E. Margin heatmap / dashboard
A `rshelper dashboard` command that opens a local web server with a real-time
dashboard: top flips, watchlist status, margin trends sparklines. Could use the
existing HTML export as a foundation, served via `http.server` (stdlib).

### F. GE tax optimization
The 1% GE tax (capped at 5M) is a significant cost for high-value flips. A
`--tax-optimize` mode that computes the optimal sell price to minimize tax while
maximizing profit. The formula: `profit = sell_price * 0.99 - buy_price - 1` with
constraints from the bid/ask spread.

### G. Discord webhook integration
Push scan results, watchlist alerts, or daily summaries to a Discord channel via
webhook. `rshelper notify discord --webhook-url <url>` using stdlib `urllib`.

### H. Scheduled scans (cron-friendly)
Ensure every subcommand works correctly in non-TTY environments (already mostly true
with stderr routing). Add `--quiet` flag to suppress all non-error output except the
final table/JSON/CSV. Document crontab examples in README.

### I. Item price prediction
Use the existing timeseries data + simple linear regression (stdlib `statistics`)
to project short-term price direction. `rshelper item-info <id> --predict` shows
"likely up/down/flat" with a confidence score.

## Sharp Edges from the Original Audit Still Open

These are from the original v0.4 audit that were never addressed because they're
low-priority or require design decisions:

- **R5 residual**: `fetch_mapping` now has preemptive unwrap (v0.7), closing this.
- **E22 complete**: Watchlist shipped in v0.6.
- **E21 (SQLite)**: Explicitly deferred. JSON snapshots (v0.8) serve the diff use case.
- **E27 (diff/trend)**: Shipped in v0.8.
- **E26 (config file)**: Shipped in v0.5, but boolean wiring gap remains (sharp edge #1 above).
- **E24 (trade sizing)**: Shipped in v0.5.
- **D18 (property-based tests)**: Shipped in v0.6.
- **F31 (component score exposure)**: Shipped in v0.6.
- **Parallel fetch**: Shipped in v0.7, but see edge #4 above.

## Verification Gates for the Next Agent

Before considering any round "done":

1. **All existing tests pass.** Run both test files. Any new tests you add should also pass.
2. **No regressions on the full CLI surface.** Smoke-test every subcommand. The features
   listed above under "DO NOT REGRESS" are hard constraints.
3. **Live API smoke**: `margin-check --check 5 --top 5 --risk` exits 0, confidence scores
   in [0,1], risk columns present, no crashes.
4. **Config round-trip**: Delete `~/.config/rshelper/config.toml`, run any scan, verify
   it's recreated with correct defaults.
5. **Output format consistency**: JSON output is valid JSON, CSV has headers, HTML is
   well-formed. Status messages on stderr only.
6. **Watchlist integrity**: Add/remove items, verify state file is valid JSON, check
   doesn't crash with empty watchlist or missing price data.
7. **Diff correctness**: Create two snapshots, verify diff correctly identifies new/
   improved/fell-off/removed items. Test with both alch (profit key) and margin
   (avg_margin key) scan types.
8. **New features have their own gates.** Every new command or flag should have at
   least one unit test and one manual smoke test.

## Working with $anti

The `$anti` skill is available for Opus/Sonnet reviews and planning. Use it for:
- `python3 ~/.codex/skills/anti/scripts/anti.py review --model opus --scope working-tree`
  before committing large changes
- `python3 ~/.codex/skills/anti/scripts/anti.py workflow review-ready --scope staged`
  for pre-commit review
- `python3 ~/.codex/skills/anti/scripts/anti.py plan --model opus --scope working-tree`
  for deep autonomous work planning

Run `smoke` first if gateway readiness is uncertain. The gateway runs at
`http://127.0.0.1:51122/v1`. Default review model is `opus` (claude-opus-4-6).

## Commit

When done with a round:
```bash
cd /Users/reidar/Documents/RSHelper
git add -A
git commit -m "v1.0: <summary of what you built and fixed>"
```

Log the commit SHA, test counts, and key decisions to today's Obsidian daily note under
`## Log` with the format:
`- HH:MM — [[Personal/Projects/RSHelper|RSHelper]] — what happened. Evidence: ...`

Update `Personal/Projects/RSHelper.md` with the new version section.

The Obsidian vault is at `/Users/reidar/Obsidian/Hermes/Hermes/`. Today's daily note is
`Daily/DD-MM-YYYY.md` (use `date '+%d-%m-%Y'` to get the current date).
