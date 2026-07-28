# RSHelper v0.1 — Implementation Handoff

## Task

Implement a Python CLI alch-profit scanner for OSRS Grand Exchange trading. This is the first
runnable code for RSHelper — the foundation that all subsequent features (flip finder,
backtester, RuneLite plugin) will build on.

## Starting state

- Project root: `/Users/reidar/Documents/RSHelper`
- No git repo yet, no application code, no data models
- Research is done: see `research_notes.md` (805 lines, 28 sources) for all formulas
- Two existing Python scripts (`clean_transcripts.py`, `extract_transcripts.py`) are research
  tooling — leave them alone or move to a `scripts/` directory

## v0.1 Deliverable

A runnable Python CLI that:

1. Fetches all OSRS items + live prices from the OSRS Wiki Realtime Prices API
2. Calculates alch profit for every item
3. Outputs a ranked table of profitable alchs sorted by estimated GP/hr

## Implementation plan

### Phase 1: Project setup

```bash
cd /Users/reidar/Documents/RSHelper
git init
```

Create this structure, moving research artifacts out of the root:

```
src/
  rshelper/
    __init__.py
    api.py          — OSRS Wiki API client
    models.py       — Item dataclass
    scanner.py      — AlchScanner
    cli.py          — argparse entry point
tests/
  test_scanner.py
scripts/
  clean_transcripts.py    (move existing)
  extract_transcripts.py  (move existing)
data/                       (move existing db_*.json, aalto_thesis_text.txt here)
research/                   (keep existing research notes)
transcripts/                (keep existing)
README.md
requirements.txt
.gitignore
```

### Phase 2: API client (`src/rshelper/api.py`)

The OSRS Wiki Realtime Prices API. Three endpoints:

```
https://prices.runescape.wiki/api/v1/osrs/mapping   — item ID → name, buy limit, members, alch value
https://prices.runescape.wiki/api/v1/osrs/latest    — current high/low prices + high/low time
https://prices.runescape.wiki/api/v1/osrs/5m        — 5-minute OHLC averages
```

**Requirements:**
- Set `User-Agent: RSHelper/0.1 (contact@example.com)` — the Wiki requires this
- Rate limit: max 1 request per second. Use a simple `time.sleep(1)` between calls for v0.1
- The mapping endpoint returns all items in one call. `latest` and `5m` also return all items
- Parse JSON responses into Python dataclasses
- Handle HTTP errors gracefully (print warning, continue with partial data)
- Cache responses to a temp file so repeated runs don't hammer the API

**Mapping response shape** (partial — extract what you need):
```json
[{"id": 2, "name": "Cannonball", "examine": "...", "members": true,
  "lowalch": 2, "limit": 10000, "value": 5, "highalch": 3, "icon": "..."}, ...]
```

**Latest prices response shape:**
```json
{"data": {"2": {"high": 5, "highTime": 1722000000, "low": 4, "lowTime": 1722000000}, ...}}
```

### Phase 3: Data model (`src/rshelper/models.py`)

```python
from dataclasses import dataclass

@dataclass
class Item:
    id: int
    name: str
    members: bool
    buy_limit: int       # 4-hour GE buy limit
    alch_value: int      # high alch value (60% of store value)
    buy_price: int       # instant buy price (API "high" = what you pay to buy instantly)
    sell_price: int      # instant sell price (API "low")
    volume: int          # 5-minute volume from /5m endpoint
    # Computed:
    profit: int = 0      # profit per alch cast
    gp_per_hour: int = 0 # estimated GP/hr after buy limit constraint
```

### Phase 4: Alch scanner (`src/rshelper/scanner.py`)

**Core formula** (from research):
```
profit_per_cast = alch_value - buy_price - nature_rune_cost
```

**GP/hr calculation** (from the OSRS Wiki Market Watch/Alchemy page):
```
max_casts_per_4h = min(buy_limit, 4800)  # 4800 = 1200 casts/hr * 4 hours
casts_per_hour = max_casts_per_4h / 4

# Volume correction: if the item trades so little you can't sustain the buy limit
if volume < (6 * buy_limit) and volume < 28800:
    casts_per_hour = volume / 24

gp_per_hour = profit_per_cast * casts_per_hour
```

**Nature rune cost:** Default to 147 GP (current GE price). Make it a CLI argument (`--nature-rune-cost`).

**Output:** Ranked table sorted by gp_per_hour descending, showing:
```
Rank  Item Name          Buy Price  Alch Value  Profit/Cast  GP/hr      Buy Limit
1     Rune dagger(p+)    3,492      4,800       1,161        81,270     70
2     Black d'hide body   6,935      8,088       1,006        70,420     70
...
```

Filter out items with profit <= 0.

### Phase 5: CLI (`src/rshelper/cli.py`)

```
Usage: python -m rshelper.cli alch-scan [--nature-rune-cost 147] [--members-only] [--min-volume 100] [--top 50]
```

Arguments:
- `--nature-rune-cost` (default 147): GP cost of nature runes
- `--members-only` (flag): filter to members items only
- `--min-volume` (default 0): minimum 5-minute trade volume
- `--top` (default 50): how many results to show
- `--json` (flag): output JSON instead of table

### Phase 6: Test (`tests/test_scanner.py`)

One focused test exercising the scanner with mock data:

```python
def test_alch_scanner_basic():
    items = [
        Item(id=1, name="Test item", members=False, buy_limit=100,
             alch_value=1000, buy_price=800, sell_price=750, volume=500),
        Item(id=2, name="Loss item", members=False, buy_limit=50,
             alch_value=100, buy_price=200, sell_price=190, volume=10),
    ]
    scanner = AlchScanner(nature_rune_cost=147)
    results = scanner.scan(items)
    assert len(results) == 1  # only the profitable one
    assert results[0].profit == 53  # 1000 - 800 - 147
```

### Phase 7: Commit

```bash
git add -A
git commit -m "v0.1: Alch-profit scanner with OSRS Wiki API client"
```

## Key research findings to apply during implementation

These are the specific formulas, thresholds, and mechanics from `research_notes.md`
that matter for v0.1:

| Finding | Source | How to use |
|---|---|---|
| Alch profit formula | gemargin, OSRS Wiki | Core calculation |
| Max alchs per hour: 1,200 | OSRS Wiki | GP/hr ceiling |
| Cast speed: 5 ticks (3.0s) | OSRS Wiki | Hard constraint |
| Buy limit = 4-hour cycle | OSRS Wiki | Bottleneck calculation |
| Nature rune cost ~147-150 GP | OSRS Wiki Market Watch | CLI default |
| Explorer's Ring 4: 30 free alchs/day | OSRS Wiki | Nice-to-have edge case |
| Fire staff: eliminates fire rune cost | gemargin, OSRS Wiki | Assumed by default |
| Volume tiers: 500k+/day = high | Benefits guide | Optional filter |
| Profit * min(buy_limit, 4800) | OSRS Wiki Market Watch | GP/hr formula |
| Volume < 6*buy_limit correction | OSRS Wiki Market Watch | GP/hr realism adjustment |

## What NOT to build in v0.1

- Flip finder / margin scanner (v0.2)
- Paper trading / backtesting (v0.3)
- RuneLite Java plugin (after Python algorithms are validated)
- Multi-account support
- Set arbitrage or decanting calculators
- Overnight scheduling
- Any UI beyond CLI table output

## After v0.1 ships

Verify output against live GE prices manually (pick 3-5 items, check in-game or on
ge-tracker.com that the profit margins are real). Then plan v0.2 (flip scanner).

## Log when done

Append to today's Obsidian daily note under ## Log with the commit SHA and a summary.
Update the RSHelper project note in Obsidian with the new verified state.
