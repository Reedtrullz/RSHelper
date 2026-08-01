# RSHelper — Agent Instructions

RSHelper is a stdlib-only Python CLI and local web dashboard for Old School
RuneScape Grand Exchange trading: alch-profit scanning, flip/margin analysis,
market signals, a daemon monitor, a trade journal, and multi-account profiles.
It also ships a production deployment (Docker on a Racknerd VPS behind Caddy)
served at https://rs.reidar.tech. Current version: `2.1.0`
(`rshelper --version`). Latest handoff: `HANDOFF-v3.0.md`.

## Environment

- Python 3.11+ required (`tomllib`); venv at `.venv/`. Run everything through
  `.venv/bin/python`.
- Zero external dependencies. Do not add PyPI packages; the API clients
  (OSRS Wiki + GE Tracker fallback) use `urllib` and the dashboard uses
  `http.server`.
- Cache at `~/.cache/rshelper/` (0600, atomic writes). Config, watchlist,
  trades, snapshots, cooldowns, volume baselines, monitor state at
  `~/.config/rshelper/`.
- Run tests:
  ```bash
  for f in tests/test_*.py; do .venv/bin/python "$f"; done
  ```
  Expected: 220 tests across 18 files, all passing.
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
   `__version__` constant. Keep the CLI surface listed in `HANDOFF-v3.0.md`
   working: every subcommand and flag must have at least one test and a smoke
   check.
7. **Defaults are tuned for paper trading**: flip/margin scans default
   `min_volume = 10` so untradeable items (vol <= 5) do not pollute results.
   `--members-only` is a `BooleanOptionalAction` whose default comes from
   `config.toml`.

## Known Deliberate Simplifications (ponytail)

- `scanner.py`: 5-min volume is extrapolated to hourly with `volume * 12`.
- `dashboard/server.py`: closure-based TTL cache, re-fetch every 120s.
- `api.py`: GE Tracker fallback volume is order quantities
  (`buyingQuantity`/`sellingQuantity`), not real 5m trade volume; real
  trade-volume timeseries are wiki-only. The GE Tracker dump is cached 300s
  so the undocumented endpoint gets one fetch per refresh cycle.
- `dashboard/templates.py`: inline HTML template, no template engine.
- `market.py`: staleness (>24h) and spread-ratio (>20x) thresholds are
  hardcoded guards shared by every price consumer; price sanity is applied
  in `build_items_from_api` and by all raw-price paths (watch-check,
  monitor alerts, item-info, trade paper).
- `positions.py`: open paper positions are closed FIFO; in-process lock
  only (cross-process writes are last-writer-wins, single-user tool).

## Workflow Gates

Before committing a round:
1. Run all 18 test files; zero failures.
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

## Disk Hygiene

- Before long build/test loops, check `df -h /System/Volumes/Data`; stop if
  below 30Gi free.
- Use bounded scratch paths (`swift`/`xcodebuild` only apply to sibling
  projects; RSHelper itself builds nothing).
- Clean stale temp files after autonomous work; never delete data in
  `~/.config/rshelper/` or `~/.cache/rshelper/` except via the app's own
  cleanup paths (`cleanup_stale_cache`, profile delete).
