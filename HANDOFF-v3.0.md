# RSHelper Handoff v3.0: Current State (v1.9.0)

You are taking over RSHelper at `/Users/reidar/Documents/RSHelper`, a Python
CLI plus local web dashboard for OSRS Grand Exchange trading, with a
production deployment at https://rs.reidar.tech. It has grown from the v0.1
alch scanner into a full trading platform: flip/margin analysis with
confidence scoring, market signals, a daemon monitor, a trade journal,
multi-account profiles, a paper-trading progression dashboard, and a
VPS-hosted public dashboard deployed by CI.

**Stdlib only. Python 3.11+ (uses `tomllib`). Venv at `.venv/`.**

## Project State

```
4276 lines of Python
21 source files: __init__, __main__, api, models, analysis, scanner, signals,
                 config, watchlist, snapshot, journal, positions, monitor,
                 profile, history, tuning, cli,
                 dashboard/{__init__, handlers, server, templates}
17 test files, 205 tests, all passing:
  test_analysis (16)        test_cli (22)         test_dashboard (38)
  test_ge_tracker_fallback (10) test_history (5)  test_integration (4)
  test_journal (20)         test_market (4)       test_monitor (8)
  test_positions (6)        test_profile (10)
  test_properties (8)       test_scanner (14)     test_signals (16)
  test_snapshot (9)         test_tuning (6)       test_watchlist (9)
```

**Git log (HEAD):**
```
9cd8f26 v1.6: GE Tracker fallback source when OSRS Wiki is blocked
117549a fix: monitoring health-check inline python
89a0fd7 hardening: drop wiki diagnostic; document VPS wiki 403
bf6356e hardening: dashboard survives wiki 403 (fresh VPS)
1e66fa1 v1.6: release CI ansible deployment + python 3.11 compat
48db063 v1.6: paper trading progression dashboard
e5eb1f2 docs: paper trading progression spec and plan
9da8238 hardening: review fixes for surge baseline and test isolation
759e531 v1.6: signal/tuning round (SURGE EMA baseline, paper capital guard)
747d8b1 paper trading review round (ROI/cost basis, pnl --by-item)
cf153a2 hardening: fix remaining stdout leaks, ROI helper, review fixes
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
                       | open <item> [qty] [--capital N] [--flip-direction ...]
                       [--note] | close <item> [qty] | positions [--json]
                       | list [--item] [--since] [--top] [--json|--csv]
                       | pnl [--since] [--by-item] [--json] | delete <id>
rshelper profile       create|switch|list|delete <name> [--force]
rshelper diff          [alch|flip|margin] [--date YYYY-MM-DD]
rshelper snapshots     [alch|flip|margin]
rshelper config        show | path
rshelper dashboard     [--bind BIND] [--port PORT]
```

Global flags: `--profile NAME`, `--quiet`, `--version` (prints `1.9.0`).

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

### Data sources and cache strategy
Primary source is the OSRS Wiki prices API (`prices.runescape.wiki` v1; v2
exists with richer timeseries but is not yet wired). Order per fetch:
fresh cache -> live API -> **GE Tracker fallback** -> stale cache.

- The wiki prices API returns HTTP 403 from datacenter IPs (Cloudflare,
  ASN-level; confirmed from the Racknerd VPS with both curl and urllib). The
  whole wiki plus `api.weirdgloop.org` are blocked; the VPS cannot use any
  wiki-hosted source.
- `api.py` falls back to the GE Tracker all-items dump
  (`www.ge-tracker.com/api/items`, no auth, reachable from the VPS): item
  metadata (`buyLimit` -> `limit`, `highAlch`/`lowAlch`, `members`), live
  prices (`buying`/`selling` -> `high`/`low`), and a volume proxy from
  `buyingQuantity`/`sellingQuantity` (order quantities, **not** real 5m trade
  volume). The dump is cached 300s so the undocumented endpoint gets one
  fetch per refresh cycle.
- Never serve stale data ahead of a network attempt. All cache writes are
  atomic (temp file + `os.replace`). Cache dir `~/.cache/rshelper/` (0600).
- Assessed but not wired: Jagex legacy itemdb
  (`secure/services.runescape.com`, guide prices + 180d daily history,
  works from the VPS) and osrsbox-db metadata (GitHub raw, but repo frozen
  Aug 2022). Add these if longer-range history is wanted on the progression
  charts.

### stdout / stderr contract
stdout is data only (table, JSON, CSV, HTML, primary output). All status,
fetch, progress, and error messages go to stderr. This is the most-regressed
invariant; `--json` output must pipe through `json.tool` cleanly.

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
and honors `config.toml`. Flip output includes `roi` and
`capital_per_unit` in JSON/CSV and an ROI% column in the table/HTML.

## Progression Dashboard (v1.6)

- `tuning.py`: config fingerprint + `tuning_log.json` changelog, recorded at
  dashboard startup and CLI snapshot saves.
- `history.py`: `build_history(profile, paper_only)` joins trades + snapshots
  + tuning log into daily buckets, tuning eras, per-item rows, and a summary.
- `/api/history?paper=1|0` and a Progression view (cumulative P&L with
  config-change markers, daily trades + win rate, tuning eras, per-item P&L).
- The dashboard survives a failed bootstrap fetch: it starts with
  cached/empty data and keeps previous data on refresh failure
  (`dashboard/server.py` wraps `_fetch_bootstrap` in `try/except SystemExit`).

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
- v1.5 rounds (`747d8b1`, `759e531`): ROI/cost basis in P&L, `pnl --by-item`,
  `trade paper --flip-direction`, profile threading in trade log/list/delete,
  SURGE rolling EMA baseline, paper capital guard.
- v1.6 progression (`48db063`): tuning log, history joins, `/api/history`,
  Progression dashboard view. 162 tests across 14 files.
- v1.6 deploy (`1e66fa1` + follow-ups): Docker image, release CI, Ansible
  playbook with rollback, monitoring workflow, Python 3.11 compat (PEP 701
  f-string fixes), state-volume ownership for container uid 1000.
- v1.6 hardening (`bf6356e`, `89a0fd7`): dashboard survives the wiki 403
  (fresh-VPS crash-loop root-caused), diagnostic removed and documented.
- v1.6 data sources (`9cd8f26`): GE Tracker fallback + volume proxy + 5 new
  tests. 167 tests across 15 files.

## Deployment

- Push to `main` -> `.github/workflows/ci.yml`: checks -> GHCR build/push
  (immutable SHA tag) -> Ansible deploy -> exact-SHA public health verify.
- Playbook/inventory/templates in `deploy/`; container state volume at
  `/opt/apps/rshelper/data` owned by uid 1000 (container user `rshelper`).
- Secrets on the repo: `VPS_SSH_PRIVATE_KEY`, `VPS_SSH_HOST_KEY` (host key
  is compared against a fresh `ssh-keyscan` at deploy time).
- `.github/workflows/monitoring.yml`: scheduled public uptime checks (cron
  every 6h) + dispatch.
- `.github/workflows/probe-sources.yml`: manual dispatch-only diagnostic that
  curls candidate GE data sources from the VPS host. Keep it; it is the fast
  way to re-check reachability when a source changes.
- The `production` environment is declared in the workflow but has no GitHub
  protection rule yet.
- `/api/health` exposes `{"status": "healthy", "version": <git SHA>}`; the
  live SHA at https://rs.reidar.tech/api/health is the source of truth for
  what is deployed.

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
   average only; no 1h baseline. SURGE uses a persisted rolling EMA baseline
   (`volume_baseline.json`) so a single snapshot has nothing to compare
   against until a second scan seeds it.
7. GE Tracker fallback: endpoint is undocumented (no SLA), quantities are
   order-book snapshots not trade volume, and poisoned-weapon GE anomalies
   (e.g. instant-buy at 1 gp) pass through unfiltered.
8. `cleanup_stale_cache` treats any cache file older than 24h as stale,
   including the 5-min GE Tracker dump on a profile that has not fetched
   recently.

## Verification Gates

1. All 15 test files pass: `for f in tests/test_*.py; do .venv/bin/python "$f"; done`.
2. Smoke every touched subcommand against the live Wiki API (or the GE
   Tracker fallback from a datacenter IP).
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
