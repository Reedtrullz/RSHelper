 # Plan: Grand Exchange UI + Bank Window

 ## Overview

 Two new OSRS-themed tabs in the RSHelper dashboard that simulate the
 in-game Grand Exchange and Bank interfaces. The GE tab shows active
 trades as live offers with animated fill progress. The Bank tab shows
 current holdings in a bank-style grid. Both use real OSRS item icons
 from the wiki.

 ---

 ## 1. GE Tab — Active Offers

 ### What it shows

 An 8-slot grid (4×2) styled after the OSRS Grand Exchange interface.
 Each slot represents one open position (from `positions.json`) as an
 active buy or sell offer. Empty slots show the OSRS "Empty" slot with
 the backpack icon.

 Per slot:
- **Offer type label**: "Buy" or "Sell" in OSRS gold text
- **Item icon**: OSRS detail image (40×40 sprite from wiki)
- **Item name**: truncated if needed, white text
- **Fill progress bar**: animated bar (green for buy, orange for sell)
  that progresses based on volume and time held
- **Price display**: "737,373 coins" format (OSRS comma-separated)
- **Status**: pending / partially filled / filled
- **Collect button**: appears when fill reaches 100%, triggers position close

 ### Slot layout

 ```
 ┌─────────────┬─────────────┬─────────────┬─────────────┐
 │    Buy      │    Buy      │    Sell      │    Buy      │
 │  [icon]     │  [icon]     │  [icon]     │  (Empty)    │
 │  Item Name  │  Item Name  │  Item Name  │             │
 │  [======  ] │  [========] │  [====    ] │  [  backpack]│
 │  737K coins │  73K coins  │  250M coins │             │
 ├─────────────┼─────────────┼─────────────┼─────────────┤
 │    Sell      │    Buy      │    Sell      │   Empty     │
 │  [icon]     │  [icon]     │  [icon]     │             │
 │  Item Name  │  Item Name  │  Item Name  │             │
 │  [====    ] │  [======  ] │  [======  ] │  [  backpack]│
 │  250K coins │  300 coins  │  99 coins   │             │
 └─────────────┴─────────────┴─────────────┴─────────────┘
 ```

 ### Fill simulation

 Offers don't fill instantly in OSRS. The fill progress is simulated:

 - **Fill rate** based on item volume: high-volume items fill faster.
   `fill_speed = min(1.0, (volume * 12) / qty)` per minute of hold time.
 - **Fill curve**: ease-out — fast start, tapering end (realistic: bulk
   of volume comes in waves, last few units take longer).
 - **Fill %** = `clamp(0, 1, elapsed_minutes * fill_speed * ease_factor)`
 - **Animated transition**: CSS transition on the bar width (0.5s ease-out)
   updated every 10 seconds via polling `/api/ge`.
 - When fill reaches 100%, the slot shows "Collect" button (like OSRS).
   Clicking Collect closes the position and realizes P&L.

 ### History sub-tab

 A toggle within the GE view (like the real "History" button in the
 top-left of the OSRS GE). Shows recent offers that have been collected
 or closed, pulled from the trade journal. Columns:
- Item name + icon
- Buy/Sell type
- Quantity
- Price
- Status (filled / partial / cancelled)
- Time
- P&L (for completed trades)

 Styled as the OSRS GE history overlay: dark background, list format.

 ### Data flow

 ```
 /api/ge (GET)
   → reads positions.json (open positions)
   → reads trader_state.json (last cycle, cycle count)
   → for each position:
     - compute fill_pct based on volume, qty, time_held
     - determine offer_type (buy/sell) from direction
     - look up current market price for slot value
   → returns: { slots: [...], history: [...], meta: {...} }

 /api/ge/collect (POST)
   → accepts: { position_id: N }
   → calls trade close logic (positions.close_positions + journal.log_trade)
   → returns: { ok, realized_pnl, ... }
 ```

 ### Files touched

 | File | Change |
 |------|--------|
 | `src/rshelper/ge_offers.py` *(new)* | Fill simulation + slot state computation |
 | `src/rshelper/dashboard/handlers.py` | Add `/api/ge` and `/api/ge/collect` routes |
 | `src/rshelper/dashboard/server.py` | Wire GE endpoints through `make_handler` |
 | `src/rshelper/dashboard/templates.py` | GE tab CSS + JS + HTML template |

 ---

 ## 2. Bank Tab — Holdings Overview

 ### What it shows

 A bank-style grid showing all items currently held as open positions,
 styled after the OSRS "Bank of RuneScape" interface. This is the
 inventory view: what you own right now, with quantities and estimated
 values.

 Per slot:
- **Item icon**: OSRS inventory image (40×40)
- **Quantity**: large number overlay (like "5290K", "127K")
- **Item name** on hover (tooltip or detail overlay)
- **Current market value** per unit
- **Total value** for the stack
- **Unrealized P&L** color-coded (green = profit, red = loss)

 ### Bank UI design

 ```
 ┌─────────────────────────────────────────────────────────┐
 │              The Bank of RuneScape                      │
 │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ...     │
 │  │ 5290K│ │ 127K │ │ 155K │ │ 72K  │ │ 36K  │         │
 │  │[icon]│ │[icon]│ │[icon]│ │[icon]│ │[icon]│         │
 │  │ Item │ │ Item │ │ Item │ │ Item │ │ Item │         │
 │  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘         │
 │  ┌──────┐ ┌──────┐ ...                                 │
 │  │      │ │      │                                     │
 │  └──────┘ └──────┘                                     │
 │                                                         │
 │  Total holdings: 1,234,567 gp   │  Positions: 5        │
 │  Unrealized P&L: +12,345 gp     │  Members: 3          │
 └─────────────────────────────────────────────────────────┘
 ```

 ### Scrollable grid

 If holdings exceed the visible area (like the bank scrollbar), the grid
 scrolls vertically. Capacity shown in the footer: "X/Y slots used".

 ### Data flow

 ```
 /api/bank (GET)
   → reads positions.json (all open positions)
   → for each unique item_id:
     - aggregate total qty across positions
     - look up current market price
     - compute avg buy price (weighted by qty across positions)
     - compute unrealized P&L (current_value - cost_basis - est_tax)
   → returns: {
       items: [...],  // sorted by total value desc
       total_value: N,
       unrealized_pnl: N,
       slot_count: N,
       ...
     }
 ```

 ### Files touched

 | File | Change |
 |------|--------|
 | `src/rshelper/bank.py` *(new)* | Holdings aggregation + valuation |
 | `src/rshelper/dashboard/handlers.py` | Add `/api/bank` route |
 | `src/rshelper/dashboard/server.py` | Wire bank endpoint |
 | `src/rshelper/dashboard/templates.py` | Bank tab CSS + JS + HTML |

 ---

 ## 3. Item Icon System

 ### Source

 OSRS Wiki MediaWiki API — all item sprites are hosted at
 `oldschool.runescape.wiki/images/`. Two image types:
- **Detail icons** (GE slot style): `/{Name}_detail.png` — larger, used
  in GE offers
- **Inventory icons** (bank style): `/{Name}.png` — smaller, used in bank

 ### Resolution strategy

 Item names from RSHelper don't always match wiki filenames exactly
(e.g., "Green dragon leather" → `Green_dragon_leather.png`). Two-tier
approach:

1. **Client-side**: construct URL from item name directly
   (`Name.replace(' ', '_') + '_detail.png'`). Works for ~85% of items.
2. **Fallback**: if image 404s, resolve via wiki MediaWiki API:
   `api.php?action=query&titles=File:{Name}_detail.png&prop=imageinfo&iiprop=url&format=json`
3. **Cache**: resolved icon URLs stored in a client-side Map (session
   lifetime). Once resolved, never re-fetch.

 ### Pre-fetch at dashboard startup

 When the dashboard bootstraps (or a `/api/ge` or `/api/bank` call is
 made), the server resolves icon filenames for all items in the current
 positions and includes them in the API response. This avoids client-side
 404 probing.

 ```python
 # In ge_offers.py / bank.py
 def resolve_icon_url(item_name: str, detail: bool = True) -> str:
     suffix = "_detail" if detail else ""
     filename = item_name.replace(" ", "_") + suffix + ".png"
     return f"https://oldschool.runescape.wiki/images/{filename}"
 ```

 The server returns `{ ..., "icon_url": "...", "icon_url_detail": "..." }`
 in slot/item objects. Client uses these directly — no probing needed.

 ---

 ## 4. Animations & Polish

 ### Fill bar animation

 - CSS `transition: width 0.5s ease-out` on the progress bar element
 - Width updates via JS every 10 seconds (polling `/api/ge`)
 - Bar color: green gradient for buy offers, orange gradient for sell offers
 - At 100%, bar pulses briefly (CSS `@keyframes pulse`) to signal "ready
   to collect"
 - Collect button fades in with a short scale animation

 ### Slot interactions

 - Hover: slight glow effect (OSRS-style gold border highlight)
 - Click: expands to show detail panel (spread at entry, time held,
   TP/SL targets, current market price, unrealized P&L)
 - Collect: button triggers POST, slot shows brief "collecting..." state
   with a coin stack animation, then slot empties

 ### Bank hover

 - Hover on a bank slot: tooltip with item name, quantity, avg buy price,
   current price, unrealized P&L
 - Subtle scale-up on hover (1.05x, 0.15s ease)

 ### Empty slots

 - GE: OSRS-style empty slot with small backpack icon (CSS-drawn or a
   small inline SVG)
 - Bank: empty slots show faint grid lines (like the real bank)

 ---

 ## 5. New Python Modules

 ### `src/rshelper/ge_offers.py` (~100 lines)

 ```python
 """Grand Exchange offer simulation: fill progress + slot state."""

 def compute_fill_pct(position, vol_5m: dict, now: float) -> float:
     """Return 0.0–1.0 fill progress for a position."""

 def build_ge_slots(profile=None) -> list[dict]:
     """Build all 8 GE slots from open positions + empty slots."""

 def collect_offer(position_id: int, profile=None) -> dict:
     """Close a filled offer and return realized P&L."""

 def resolve_icon_url(item_name: str, detail: bool = True) -> str:
     """Construct OSRS wiki icon URL from item name."""
 ```

 ### `src/rshelper/bank.py` (~70 lines)

 ```python
 """Bank holdings: aggregate positions into inventory view."""

 def build_bank_items(profile=None) -> dict:
     """Aggregate open positions into bank-style inventory items."""
 ```

 ---

 ## 6. Dashboard Tab Wiring

 ### New nav tab

 Add two tabs to the nav row:
- **"Grand Exchange"** — the GE offer grid
- **"Bank"** — the holdings inventory

 These sit alongside the existing Market, Paper Trading, Signals, and
 Watchlist tabs.

 ### JS view functions

 - `setView('ge')` — fetches `/api/ge`, renders the 8-slot grid
- `setView('bank')` — fetches `/api/bank`, renders the bank grid
- Both auto-refresh on the existing 60-second cycle
- Collect button triggers `POST /api/ge/collect` then re-renders

 ---

 ## 7. Testing

 New test file: `tests/test_ge_offers.py` (~15 tests)
- fill_pct computation (volume edges: 0, low, high, max_volume)
- fill_pct time progression (0 min, 1 min, full)
- ease-out curve shape
- slot building (0, 1, 5, 8 positions → correct slot count)
- empty slots (max 8, correct indices)
- collect_offer (calls close_positions, returns realized P&L)
- icon URL construction (spaces, special chars)

 New test file: `tests/test_bank.py` (~10 tests)
- aggregation across multiple positions for same item
- weighted avg buy price
- unrealized P&L with 2% tax
- empty positions → empty bank
- total value computation

 Existing tests: all 252 must remain green.

 ---

 ## 8. Commit Convention

 ```
 v2.6: Grand Exchange offer UI + Bank holdings view
 ```

 Single commit (or two if the PR is large): new modules + template
 changes + tests.

 ---

 ## 9. Files Summary

 ### New files (2)
- `src/rshelper/ge_offers.py`
- `src/rshelper/bank.py`

 ### Modified files (4)
- `src/rshelper/dashboard/templates.py`
- `src/rshelper/dashboard/handlers.py`
- `src/rshelper/dashboard/server.py`
- (test files: `tests/test_ge_offers.py`, `tests/test_bank.py`)

 ### Total: 8 files touched, 0 new dependencies

 ---

 ## 10. Implementation Order

 1. `ge_offers.py` — fill simulation + slot builder + icon resolver
 2. `bank.py` — holdings aggregator
 3. `/api/ge` + `/api/bank` + `/api/ge/collect` handlers
 4. Wire endpoints in `server.py`
 5. Template: GE tab CSS + JS (8-slot grid, fill bars, animations)
 6. Template: Bank tab CSS + JS (inventory grid, hover tooltips)
 7. Template: History sub-tab within GE view
 8. Tests for ge_offers + bank
 9. Smoke-test all new endpoints against live data
 10. Run full test suite (252+ tests, zero failures)
 11. Commit

 ---

 ## 11. Out of Scope (for now)

 - Drag-to-reorder slots (like OSRS swap/insert mode)
 - Bank tab organization (folders, search, layout persistence)
 - GE price graph per slot (the Market view already covers this)
 - Actual GE API integration (paper-only, as always)
 - Sound effects (coin sound on collect — fun but not v1)
