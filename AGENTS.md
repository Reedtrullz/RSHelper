# RSHelper — Agent Instructions

RSHelper is a stdlib-only Python CLI and local web dashboard for Old School
RuneScape Grand Exchange trading: alch-profit scanning, flip/margin analysis,
market signals, a daemon monitor, a trade journal, an auto-trader, a
persistent alert feed, and multi-account profiles. It also ships a production
deployment (Docker on a Racknerd VPS behind Caddy) served at
https://rs.reidar.tech. Current version: `3.0.0`
(`rshelper --version`). Latest handoff: `HANDOFF-v4.0.md`.

## Environment

- Python 3.11+ required (`tomllib`); venv at `.venv/`. Run everything through
  `.venv/bin/python`.
- Zero external dependencies. Do not add PyPI packages; the API clients
  (OSRS Wiki + GE Tracker fallback) use `urllib` and the dashboard uses
  `http.server`.
- Cache at `~/.cache/rshelper/` (0600, atomic writes). Config, watchlist,
  trades, snapshots, cooldowns, volume baselines, monitor/trader state,
  alerts at `~/.config/rshelper/`.
- Run tests:
  ```bash
  for f in tests/test_*.py; do .venv/bin/python "$f"; done
  ```
  Expected: 344 tests across 24 files, all passing.
- Run the CLI:
  ```bash
  PYTHONPATH=src .venv/bin/python -m rshelper <command>
  ```

## Architecture Invariants — DO NOT REGRESS

1. **GE tax is 2%** on the sell price, capped at 5M per item. It was raised
   from 1% on 29 May 2025 (OSRS Wiki). The `1%` claims in `research/*` are
   stale — see the correction banners at the top of those files. Do not
   "fix" the tax rate to 1%. The 2% is rounded down per item with **no
   minimum** (items sold below 50 gp pay no tax) — the wiki is explicit.
   Always route tax through `rshelper.market.ge_tax()`; never re-derive it
   with a `max(1, ...)` floor.
2. **Margin convention**: `buy_price = API "high"` (instant buy),
   `sell_price = API "low"` (instant sell). The `direction` parameter decides
   which way the margin is computed, never which API field maps to which price.
3. **Confidence model**: `confidence = reliability x profitability`, split so
   a "reliable loser" scores near zero. MarginScanner sorts by expected
   GP/hr (confidence x current_profit x throughput).
4. **Cache strategy**: fresh cache -> live API -> GE Tracker fallback -> stale
   cache. Never serve stale data ahead of a network attempt. The OSRS Wiki
   prices API returns HTTP 403 from datacenter IPs (Cloudflare), so on the VPS
   the fallback (GE Tracker all-items dump, no auth) is the effective live
   source; the wiki stays primary on residential IPs. All cache writes are
   atomic (temp file + `os.replace`).
5. **stdout is for data only**. Tables, JSON, CSV, HTML, and primary command
   output go to stdout. Every fetch/progress/status/error message goes to
   stderr. Breaking this breaks `--json`/`--csv` piping — it is the most
   common regression in this repo.
6. **`--quiet`** routes status output to `/dev/null`; `--version` prints the
   `__version__` constant. Keep the CLI surface listed in `HANDOFF-v4.0.md`
   working: every subcommand and flag must have at least one test and a smoke
   check.
7. **Defaults are tuned for paper trading**: flip/margin scans default
   `min_volume = 10` so untradeable items (vol <= 5) do not pollute results.
   `--members-only` is a `BooleanOptionalAction` whose default comes from
   `config.toml`.
8. **Trader R:R is asymmetric by design**: take-profit `+3.0%` net (after
   tax), stop-loss `-2.0%` from the stop mark. The stop mark blends the
   entry bid with the 5m `avgLowPrice` via `stop_mark_blend` (0.0 = legacy
   entry-bid mark) so a dip entry is not stopped by the very dip it bought.
   `stop_slippage` (0.97) models worse stop fills. Always route tax through
   `rshelper.market.ge_tax()`.
9. **Candidate ranking**: `select_candidates` ranks by `edge = dip_pct *
   (spread_pct - 2.0)` first, then an optional confidence model (reliability
   x profitability) breaks ties, then volume. The scanner's `rs_score` is a
   secondary signal, never the primary rank.
10. **Replay-validated defaults** (`scripts/replay.py` + `scripts/sweep.py`):
   the trader defaults were tuned against 30 real items' 5m candles — dip
   `>= 3.0%` (2% bought falling knives), stop `-2.0%` (wider than -1.5%,
   fewer noise stops), grace `20 min` (let the dip revert), time-exit at
   `60 min` (no idling to max_hold). Sweep: dip3+stop2+grace20 → ROI 4.62%
   vs 3.11% baseline on the replay set. Re-run `sweep.py` after collecting
   more live trades before changing these again.

## Known Deliberate Simplifications (ponytail)

- `recipes.py`: the recipe table is hand-maintained and curated (smelting
  bars + a couple of crafts). Recipe IDs are verified against the wiki
  mapping; add new recipes by appending to `RECIPES` with verified IDs.
- `scanner.py`: 5-min volume is extrapolated to hourly with `volume * 12`.
- `dashboard/server.py`: closure-based TTL cache, re-fetch every 120s.
  Daemon control endpoints (start/stop auto-trade + monitor) are gated by
  the `--control` flag — never enabled on the VPS deploy.
- `dashboard/templates.py` + `dashboard/scripts.py`: inline HTML/JS split
  into core/charts/views constants, still one served artifact, no engine.
- `alerts.py`: the alert feed is persisted (cap 200, prune 14d) and synced
  to the deploy like the journal; watch-threshold dedupe is 15 min.
- `api.py`: GE Tracker fallback volume is order quantities
  (`buyingQuantity`/`sellingQuantity`), not real 5m trade volume; real
  trade-volume timeseries are wiki-only. The GE Tracker dump is cached 300s
  so the undocumented endpoint gets one fetch per refresh cycle.
- `dashboard/templates.py` + `dashboard/scripts.py`: inline HTML/JS split
  into core/charts/views constants, still one served artifact, no engine.
- `alerts.py`: the alert feed is persisted (cap 200, prune 14d) and synced
  to the deploy like the journal; watch-threshold dedupe is 15 min.
- `market.py`: staleness (>24h) and spread-ratio (>20x) thresholds are
  hardcoded guards shared by every price consumer; price sanity is applied
  in `build_items_from_api` and by all raw-price paths (watch-check,
  monitor alerts, item-info, trade paper).
- `positions.py`: open paper positions are closed FIFO; in-process lock
  only (cross-process writes are last-writer-wins, single-user tool).

## Workflow Gates

Before committing a round:
1. Run all 24 test files; zero failures.
2. Smoke-test every touched subcommand against the live Wiki API (or the GE
   Tracker fallback when testing from a datacenter IP).
3. Verify `--json` output pipes through `json.tool` without stderr leakage.
4. For larger rounds, run an `$anti` sidecar review on the diff and triage
   every finding (verify locally before fixing; record skips).
5. Commit per convention: `v1.x: <summary>` or `hardening: <summary>`.
6. Log to Obsidian: today's daily note (`Daily/DD-MM-YYYY.md`) under `## Log`
   with commit SHA, test counts, and evidence; add a version section to
   `Personal/Projects/RSHelper.md`. State plainly if logging was skipped.

## Deployment

- Push to `main` runs the CI pipeline (checks -> GHCR build/push -> Ansible
  deploy -> exact-SHA public health verify) in `.github/workflows/ci.yml`.
- The playbook and inventory live in `deploy/`; secrets
  `VPS_SSH_PRIVATE_KEY` / `VPS_SSH_HOST_KEY` are set on the repo.
- `.github/workflows/monitoring.yml` runs scheduled public uptime checks.
- `.github/workflows/probe-sources.yml` is a manual (dispatch-only) diagnostic
  that curls candidate GE data sources from the VPS host; it does not touch
  the deployed app.

## Operations (local macOS)

The dashboard runs locally as a launchd service so it starts at login and
survives crashes:

- `~/Library/LaunchAgents/com.reidar.rshelper-trader.plist` — runs
  `.venv/bin/python -m rshelper auto-trade` (the paper-trader loop), pointing
  at this repo's venv. `KeepAlive: true` — launchd restarts it on ANY exit
  (clean or crash), so a clean stop never leaves the trader down permanently.
- `~/Library/LaunchAgents/com.reidar.rshelper-state-sync.plist` — runs
  `~/.config/rshelper/bin/sync-and-push-state.py` every 15 min, committing
  trading state (`data/state/*.json`, incl. `alerts.json`) to `main` as
  "state: sync trading history". It commits with `commit.gpgsign=true` (SSH
  signing via 1Password), so it only pushes while 1Password is unlocked; if
  sync stalls, unlock 1Password (or check `launchctl list | grep rshelper-state-sync`).

Do not edit `~/.config/rshelper/` trading state by hand — it is written by
the CLI and synced to the repo by the state-sync agent.

## Disk Hygiene

- Before long build/test loops, check `df -h /System/Volumes/Data`; stop if
  below 30Gi free.
- Use bounded scratch paths (`swift`/`xcodebuild` only apply to sibling
  projects; RSHelper itself builds nothing).
- Clean stale temp files after autonomous work; never delete data in
  `~/.config/rshelper/` or `~/.cache/rshelper/` except via the app's own
  cleanup paths (`cleanup_stale_cache`, profile delete).
