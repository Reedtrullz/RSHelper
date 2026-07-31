# RSHelper — Agent Instructions

RSHelper is a stdlib-only Python CLI and local web dashboard for Old School
RuneScape Grand Exchange trading: alch-profit scanning, flip/margin analysis,
market signals, a daemon monitor, a trade journal, and multi-account profiles.
Current version: `1.5.0` (`rshelper --version`). Latest handoff:
`HANDOFF-v2.0.md`.

## Environment

- Python 3.11+ required (`tomllib`); venv at `.venv/`. Run everything through
  `.venv/bin/python`.
- Zero external dependencies. Do not add PyPI packages; the OSRS Wiki API
  client uses `urllib` and the dashboard uses `http.server`.
- Cache at `~/.cache/rshelper/` (0600, atomic writes). Config, watchlist,
  trades, snapshots, cooldowns, volume baselines, monitor state at
  `~/.config/rshelper/`.
- Run tests:
  ```bash
  for f in tests/test_*.py; do .venv/bin/python "$f"; done
  ```
  Expected: 140 tests across 12 files, all passing.
- Run the CLI:
  ```bash
  PYTHONPATH=src .venv/bin/python -m rshelper <command>
  ```

## Architecture Invariants — DO NOT REGRESS

1. **GE tax is 2%** on the sell price, capped at 5M per item. It was raised
   from 1% on 29 May 2025 (OSRS Wiki). The `1%` claims in `research/*` are
   stale — see the correction banners at the top of those files. Do not
   "fix" the tax rate to 1%.
2. **Margin convention**: `buy_price = API "high"` (instant buy),
   `sell_price = API "low"` (instant sell). The `direction` parameter decides
   which way the margin is computed, never which API field maps to which price.
3. **Confidence model**: `confidence = reliability x profitability`, split so
   a "reliable loser" scores near zero. MarginScanner sorts by expected
   GP/hr (confidence x current_profit x throughput).
4. **Cache strategy**: fresh cache -> live API -> stale cache fallback. Never
   serve stale data ahead of a network attempt. All cache writes are atomic
   (temp file + `os.replace`).
5. **stdout is for data only**. Tables, JSON, CSV, HTML, and primary command
   output go to stdout. Every fetch/progress/status/error message goes to
   stderr. Breaking this breaks `--json`/`--csv` piping — it is the most
   common regression in this repo.
6. **`--quiet`** routes status output to `/dev/null`; `--version` prints the
   `__version__` constant. Keep the CLI surface listed in `HANDOFF-v2.0.md`
   working: every subcommand and flag must have at least one test and a smoke
   check.
7. **Defaults are tuned for paper trading**: flip/margin scans default
   `min_volume = 10` so untradeable items (vol <= 5) do not pollute results.
   `--members-only` is a `BooleanOptionalAction` whose default comes from
   `config.toml`.

## Known Deliberate Simplifications (ponytail)

- `scanner.py`: 5-min volume is extrapolated to hourly with `volume * 12`.
- `dashboard/server.py`: closure-based TTL cache, re-fetch every 120s.
- `dashboard/templates.py`: inline HTML template, no template engine.

## Workflow Gates

Before committing a round:
1. Run all 12 test files; zero failures.
2. Smoke-test every touched subcommand against the live Wiki API.
3. Verify `--json` output pipes through `json.tool` without stderr leakage.
4. For larger rounds, run an `$anti` sidecar review on the diff and triage
   every finding (verify locally before fixing; record skips).
5. Commit per convention: `v1.x: <summary>` or `hardening: <summary>`.
6. Log to Obsidian: today's daily note (`Daily/DD-MM-YYYY.md`) under `## Log`
   with commit SHA, test counts, and evidence; add a version section to
   `Personal/Projects/RSHelper.md`. State plainly if logging was skipped.

## Disk Hygiene

- Before long build/test loops, check `df -h /System/Volumes/Data`; stop if
  below 30Gi free.
- Use bounded scratch paths (`swift`/`xcodebuild` only apply to sibling
  projects; RSHelper itself builds nothing).
- Clean stale temp files after autonomous work; never delete data in
  `~/.config/rshelper/` or `~/.cache/rshelper/` except via the app's own
  cleanup paths (`cleanup_stale_cache`, profile delete).
