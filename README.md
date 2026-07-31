# RSHelper

OSRS Grand Exchange trading companion: alch-profit scanning, flip/margin
analysis with confidence scoring, market signals, a background monitor with
macOS notifications, a trade journal with P&L, and a local web dashboard.
Stdlib-only Python (3.11+), no external dependencies.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # empty; stdlib only
PYTHONPATH=src .venv/bin/python -m rshelper --version
```

Config auto-creates at `~/.config/rshelper/config.toml`. Cached API data
lands in `~/.cache/rshelper/`.

## Commands

```bash
rshelper alch-scan          # profitable high-alchemy items by GP/hr
rshelper flip-scan          # flip margins (arbitrage or traditional)
rshelper margin-check       # timeseries confidence scoring, --risk metrics
rshelper item-info <item>   # prices, tax curve, history, prediction, wiki
rshelper signals            # DUMP / CRASH / SURGE / FLIP / STALE detection
rshelper monitor            # daemon polling with notifications (--stop/--status)
rshelper watch              # watchlist with margin alert thresholds
rshelper trade              # log / paper / list / pnl / delete
rshelper profile            # multi-account isolated config, cache, journal
rshelper diff               # compare scans across days (--save-snapshot first)
rshelper snapshots          # list saved scan snapshots
rshelper config             # show / path
rshelper dashboard          # local web dashboard (default :5555)
```

Common flags: `--json`, `--csv`, `--html`, `--top N`, `--min-volume N`,
`--members-only/--no-members-only`, `--capital N`, `--profile NAME`,
`--quiet`, `--version`. Status messages go to stderr, so `--json` output
pipes cleanly:

```bash
PYTHONPATH=src .venv/bin/python -m rshelper flip-scan --top 20 --json | jq
```

## Paper Trading Loop

1. `flip-scan --capital 500000` shows ROI% and buy quantity per flip.
2. `trade paper "Nature rune" --capital 100000` logs a trade at live GE
   prices (instant buy, estimated sell) with a `paper` note.
3. `trade pnl` reports realized profit, tax, win rate, best/worst, GP/hr.
4. `dashboard` shows the flip table plus a Trades view with P&L.

GE tax is 2% on sells (capped at 5M per item) — the rate has been 2% since
29 May 2025 and is applied everywhere.

## Development

```bash
for f in tests/test_*.py; do .venv/bin/python "$f"; done   # 140 tests, 12 files
```

See `AGENTS.md` for invariants (tax, margin convention, stdout/stderr,
stdlib-only) and `HANDOFF-v2.0.md` for the full architecture and CLI surface.
