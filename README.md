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
                            #   --monitor N: live follow mode (re-scan + print new)
rshelper monitor            # daemon polling with notifications (--stop/--status)
rshelper watch              # watchlist with margin alert thresholds
                            #   check --json: JSON alert output (exit 1 still fires)
rshelper trade              # log / paper [--flip-direction] / open / close /
                            # positions / status / list / pnl [--by-item] / delete
                            #   status: positions + unrealized + realized + trader
rshelper history            # progression: daily buckets, eras, per-item P&L
rshelper profile            # multi-account isolated config, cache, journal
rshelper diff               # compare scans across days (--save-snapshot first)
rshelper snapshots          # list saved scan snapshots
rshelper config             # show / path
rshelper dashboard          # local web dashboard (default :5555)
                            #   --open: open the browser
                            #   --control: enable daemon start/stop (trusted local only)
                            #   --profile NAME: serve a specific profile
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
   prices (instant round-trip) with a `paper` note; add
   `--flip-direction traditional` to model buy-at-bid/sell-at-offer.
3. `trade pnl` reports realized profit, cost basis, ROI, tax, win rate,
   best/worst, and GP/hr. `trade pnl --by-item` shows the per-item breakdown
   so you can see which items to keep flipping. `trade status` gives the
   whole picture (open positions + unrealized + realized + trader status) in
   one shot, and `history` mirrors the dashboard's Activity view headless.
4. `dashboard` is a 9-tab command center:
   - **Overview** — headline P&L, persistent alert feed (signals, watch
     triggers, trader exits, system events; bell in the topbar), daemon
     health cards with start/stop when `--control` is on.
   - **Trading** — paper trade form, open positions with Close (manual lots),
     auto-trader status + performance, live market on traded items.
   - **Market** — flip table (sort/search/filter) + Alchemy toggle; detail
     panel adds a 24h margin-history chart.
   - **Signals / Watchlist / Grand Exchange / Bank / Materials** — as before;
     the Watchlist tab now has inline alert-threshold editing.
   - **Activity** — cumulative P&L + daily charts, recent trades (with
     delete), per-item P&L, tuning eras.
   The dashboard pushes updates over SSE (`/api/events`) with a 60s poll
   fallback. GE/bank views are backed by `/api/ge`, `/api/ge/collect`, and
   `/api/bank`; the alert feed by `/api/alerts`.

GE tax is 2% on sells (capped at 5M per item) — the rate has been 2% since
29 May 2025 and is applied everywhere.

## Development

```bash
for f in tests/test_*.py; do .venv/bin/python "$f"; done   # 344 tests, 24 files
```

See `AGENTS.md` for invariants (tax, margin convention, stdout/stderr,
stdlib-only) and `HANDOFF-v4.0.md` for the full architecture and CLI surface.

## Data sources

Live GE data comes from the OSRS Wiki prices API (`prices.runescape.wiki`).
When it is unreachable (it returns HTTP 403 from datacenter IPs), the client
falls back to the GE Tracker all-items dump (`www.ge-tracker.com/api/items`,
no auth) for item metadata, live buy/sell prices, and a quantity-based volume
proxy. The wiki remains primary; see `deploy/README.md` for the VPS-specific
reachability notes.

## Deployment

Pushing to `main` builds a GHCR image and deploys it to the Racknerd VPS
behind Caddy at https://rs.reidar.tech (Ansible playbook in `deploy/`,
exact-SHA health verification in CI). A scheduled workflow runs public
uptime checks; the current live SHA is the source of truth:

```bash
curl -fsS https://rs.reidar.tech/api/health
```
