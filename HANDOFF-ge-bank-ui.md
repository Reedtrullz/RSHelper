 # Handoff: Grand Exchange UI + Bank Window (v2.6)

 You are adding two new dashboard tabs to RSHelper: a **Grand Exchange
 offer simulator** and a **Bank inventory view**, both styled after the
 real OSRS interfaces. This repo is the stdlib-only RSHelper (v2.5.0):
 `http.server` dashboard, `positions.json` paper positions, 252 tests
 across 19 files. This is also the codebase deployed to
 https://rs.reidar.tech via GitHub Actions on push to `main`.

 **Read [PLAN-ge-bank-ui.md](PLAN-ge-bank-ui.md) first** for the visual
 design. This document is the implementation spec.

 ---

 ## Non-Negotiable Rules

 1. **Stdlib only.** No new PyPI packages. `urllib`, `http.server`,
    `json`, `dataclasses`, `threading`, `pathlib` — that's it.
 2. **Python 3.11+** (`tomllib`, `X | Y` unions). Venv: `.venv/`.
 3. **stdout is data only.** Every status/error/log message goes to
    stderr. Breaking this breaks `--json`/`--csv` piping.
 4. **GE tax is 2%**, capped at 5M/item, rounded down, no minimum.
    Always route through `rshelper.market.ge_tax()`.
 5. **Margin convention**: `buy_price` = API "high", `sell_price` =
    API "low".
 6. **Atomic writes** via `rshelper.profile.atomic_write_json()`.
 7. **Profile-aware**: all path functions accept
    `profile: str | None = None`.
 8. **All 252 existing tests must stay green.** Run:
    ```bash
    for f in tests/test_*.py; do .venv/bin/python "$f"; done
    ```
 9. Commit convention: `v2.6: <summary>`. Do not push; that step is
    handled after your round.

 ---

 ## Files

 | File | Change |
 |------|--------|
 | `src/rshelper/ge_offers.py` *(new, ~120 lines)* | Fill simulation, 8-slot builder, collect, icon URLs |
 | `src/rshelper/bank.py` *(new, ~80 lines)* | Holdings aggregation + valuation |
 | `src/rshelper/dashboard/handlers.py` | `/api/ge`, `/api/ge/collect`, `/api/bank` routes |
 | `src/rshelper/dashboard/server.py` | Wire closures into `make_handler` |
 | `src/rshelper/dashboard/templates.py` | GE + Bank tab CSS/JS/HTML |
 | `tests/test_ge_offers.py` *(new)* | ~15 tests, assert-style like `test_positions.py` |
 | `tests/test_bank.py` *(new)* | ~10 tests |

 ---

 ## 1. `src/rshelper/ge_offers.py`

 ```python
 """Grand Exchange offer simulation: fill progress, slots, collect."""

 import time
 from datetime import datetime, timezone

 from rshelper.journal import log_trade
 from rshelper.market import ge_tax
 from rshelper.positions import close_positions, list_positions

 MAX_GE_SLOTS = 8


 def resolve_icon_url(item_name: str, detail: bool = True) -> str:
     """OSRS wiki sprite URL from an item name.
     detail=True -> <Name>_detail.png (GE slot sprite).
     detail=False -> <Name>.png (inventory sprite).
     """
     suffix = "_detail" if detail else ""
     return ("https://oldschool.runescape.wiki/images/"
             + item_name.replace(" ", "_") + suffix + ".png")


 def compute_fill_pct(qty: int, volume_5m: int, opened_at: str) -> float:
     """0.0–1.0 fill progress, ease-out curve.

     rate = volume_5m / 5 units per minute; raw = elapsed_min * rate / qty;
     fill = 1 - (1 - min(raw, 1))^2. Zero/unknown volume falls back to a
     slow default: min(1.0, elapsed_min * (1/qty)).
     """


 def build_ge_slots(profile=None, latest=None, vol_5m=None, now=None) -> dict:
     """All 8 GE slots from open positions.

     Returns {"slots": [...], "empty_count": int, "total_value": int}.
     Each slot dict:
     {"index", "offer_type": "buy"|"sell", "item_id", "name", "qty",
      "fill_pct", "status": "pending"|"partially_filled"|"filled",
      "price" (qty*buy_price), "price_each", "buy_price",
      "current_price"|None, "unrealized"|None, "unrealized_pct",
      "icon_url", "icon_url_detail", "position_id", "opened_at",
      "age_minutes", "can_collect": fill >= 1.0}

     latest/vol_5m are injected (dashboard cache dicts) so tests can pass
     fixtures. Direction "traditional" -> buy offer, "arbitrage" -> sell
     offer. Realized offer_type is the *open side* of the position.
     """


 def collect_offer(position_id: int, profile=None, latest=None) -> dict:
     """Close a filled position at the live price.

     Calls close_positions(position_id's item/qty, sell_price) then
     log_trade(..., note="paper", strategy="ge_collect"). Sell price is
     the current market "high" (offer) for traditional, "low" (bid) for
     arbitrage; fall back to buy_price when no usable price. Returns
     {"ok": True, "name", "qty", "sell_price", "profit"}. Raises
     ValueError when the position id is unknown.
     """
 ```

 ---

 ## 2. `src/rshelper/bank.py`

 ```python
 """Bank holdings: aggregate open positions into an inventory view."""

 from rshelper.market import ge_tax
 from rshelper.positions import list_positions


 def build_bank_items(profile=None, latest=None) -> dict:
     """Group positions by item_id (weighted avg buy price).

     Returns {"items": [...], "total_value", "unrealized_pnl",
     "cost_basis", "slot_count"} sorted by total_value desc.
     Each item: {"item_id", "name", "total_qty", "avg_buy_price",
     "current_price"|None, "total_value", "cost_basis",
     "unrealized_pnl" (current - cost - ge_tax(current)*qty),
     "unrealized_pct", "position_count", "icon_url", "icon_url_detail"}
     """
 ```

 ---

 ## 3. Handler Routes (`dashboard/handlers.py`)

 Add three params to `make_handler()`:
 `ge_fn: Callable[[], dict] | None = None`,
 `ge_collect_fn: Callable[[int], dict] | None = None`,
 `bank_fn: Callable[[], dict] | None = None`.

 In `do_GET`:
 ```python
 elif path == "/api/ge":
     self._serve_ge()
 elif path == "/api/bank":
     self._serve_bank()
 ```
 In `do_POST` (after the origin check):
 ```python
 elif path == "/api/ge/collect":
     self._handle_ge_collect()
 ```

 New methods, following the exact style of `_serve_positions` /
 `_handle_paper_trade` (JSON body parse, `ValueError` -> 400 with
 message, stderr logging, `_serve_json` for success):

 ```python
 def _serve_ge(self):
     self._serve_json(ge_fn() if ge_fn else {"slots": [], "empty_count": 8,
                                             "total_value": 0})

 def _serve_bank(self):
     self._serve_json(bank_fn() if bank_fn else {"items": [], "total_value": 0,
                                                 "unrealized_pnl": 0,
                                                 "cost_basis": 0, "slot_count": 0})

 def _handle_ge_collect(self):
     try:
         length = int(self.headers.get("Content-Length", 0))
         body = json.loads(self.rfile.read(length))
         position_id = int(body.get("position_id", 0))
     except Exception:
         self.send_error(400, "Invalid JSON")
         return
     if ge_collect_fn is None:
         self.send_error(404)
         return
     try:
         self._serve_json(ge_collect_fn(position_id))
     except (ValueError, TypeError) as e:
         print(f"[dashboard] GE collect error: {e}", file=sys.stderr)
         self.send_error(400, str(e))
 ```

 ---

 ## 4. Server Wiring (`dashboard/server.py`)

 Add closures inside `run()` next to `get_positions`/`paper_trade`:

 ```python
 def get_ge():
     refresh()
     from rshelper.ge_offers import build_ge_slots
     return build_ge_slots(latest=cache["latest"], vol_5m=cache["vol"])

 def collect_ge(position_id: int):
     from rshelper.ge_offers import collect_offer
     return collect_offer(position_id, latest=cache["latest"])

 def get_bank():
     refresh()
     from rshelper.bank import build_bank_items
     return build_bank_items(latest=cache["latest"])
 ```

 Pass them in the `make_handler(...)` call. `cache["latest"]` is the
 price dict `{str(item_id): {"high", "low", ...}}`, `cache["vol"]` is the
 5m volume dict. Use `price_issue()` (already imported in server.py) to
 decide usability — mirrors `get_positions()`.

 ---

 ## 5. Template (`dashboard/templates.py`)

 All changes go inside the `INDEX_HTML` string. Reuse the existing CSS
 variables (`--gold`, `--pos`, `--neg`, `--text-dim`, `--border`, ...).

 ### CSS (append to the `<style>` block)

 ```css
 .ge-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:3px;padding:12px;
   background:#3b3023;border:2px solid #5c4a32;border-radius:4px;
   background-image:linear-gradient(135deg,rgba(92,74,50,.08) 25%,transparent 25%),
     linear-gradient(225deg,rgba(92,74,50,.08) 25%,transparent 25%);
   background-size:8px 8px}
 .ge-slot{background:#2a2215;border:1px solid #5c4a32;border-radius:3px;padding:8px;
   min-height:120px;display:flex;flex-direction:column;position:relative;
   cursor:pointer;transition:all .15s ease}
 .ge-slot:hover{border-color:var(--gold);box-shadow:0 0 8px rgba(201,168,76,.3)}
 .ge-slot.empty{opacity:.6;cursor:default;justify-content:center;align-items:center}
 .ge-slot.empty:hover{border-color:#5c4a32;box-shadow:none}
 .ge-offer-type{font-size:11px;font-weight:700;text-transform:uppercase;
   letter-spacing:.5px;margin-bottom:4px}
 .ge-offer-type.buy{color:#7cc950}.ge-offer-type.sell{color:#e8a230}
 .ge-slot-icon{width:40px;height:40px;image-rendering:pixelated;margin:4px auto;
   object-fit:contain}
 .ge-slot-name{font-size:11px;color:var(--text);text-align:center;margin:2px 0;
   white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .ge-fill-track{width:100%;height:12px;background:#1a1208;border:1px solid #5c4a32;
   border-radius:2px;overflow:hidden;margin:4px 0}
 .ge-fill-bar{height:100%;border-radius:2px;transition:width 0.5s ease-out}
 .ge-fill-bar.buy{background:linear-gradient(180deg,#4ade80,#16a34a)}
 .ge-fill-bar.sell{background:linear-gradient(180deg,#fbbf24,#d97706)}
 .ge-fill-bar.filled{animation:ge-pulse 1.5s ease-in-out infinite}
 @keyframes ge-pulse{0%,100%{opacity:1}50%{opacity:.7}}
 .ge-slot-price{font-size:11px;color:var(--text-dim);text-align:center;
   font-variant-numeric:tabular-nums}
 .ge-collect-btn{margin-top:auto;padding:4px 8px;background:var(--gold-dim);
   border:1px solid var(--gold);border-radius:3px;color:#0a0e17;font-size:10px;
   font-weight:700;cursor:pointer;transition:all .2s ease;text-align:center;
   opacity:0;transform:scale(.9)}
 .ge-collect-btn.visible{opacity:1;transform:scale(1)}
 .ge-collect-btn:hover{background:var(--gold)}
 .ge-history-overlay{position:fixed;top:0;left:0;right:0;bottom:0;
   background:rgba(0,0,0,.7);z-index:100;display:flex;justify-content:center;
   align-items:center}
 .ge-history-panel{background:#2a2215;border:2px solid #5c4a32;border-radius:6px;
   width:600px;max-height:80vh;overflow-y:auto;padding:16px}
 .bank-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(70px,1fr));
   gap:2px;padding:12px;background:#3b3023;border:2px solid #5c4a32;
   border-radius:4px}
 .bank-slot{background:#2a2215;border:1px solid #3d3525;border-radius:2px;padding:4px;
   display:flex;flex-direction:column;align-items:center;justify-content:center;
   min-height:72px;position:relative;cursor:pointer;transition:all .15s ease}
 .bank-slot:hover{border-color:var(--gold);transform:scale(1.05);z-index:1;
   box-shadow:0 2px 8px rgba(0,0,0,.4)}
 .bank-slot-icon{width:40px;height:40px;image-rendering:pixelated;object-fit:contain}
 .bank-slot-qty{position:absolute;top:2px;right:4px;font-size:11px;font-weight:700;
   color:var(--gold);text-shadow:1px 1px 0 #000;font-variant-numeric:tabular-nums}
 .bank-tooltip{position:absolute;bottom:calc(100% + 8px);left:50%;
   transform:translateX(-50%);background:#1a1208;border:1px solid #5c4a32;
   border-radius:4px;padding:8px 10px;font-size:11px;white-space:nowrap;z-index:10;
   pointer-events:none;opacity:0;transition:opacity .15s ease}
 .bank-slot:hover .bank-tooltip{opacity:1}
 .bank-footer{display:flex;justify-content:space-between;padding:8px 12px;
   background:var(--surface);border-top:1px solid var(--border);font-size:12px;
   color:var(--text-dim)}
 ```

 ### Nav row

 Add two buttons after Watchlist:
 ```html
 <button class="nav-btn" id="btnGE" role="tab" onclick="setView('ge')">Grand Exchange <span class="badge" id="badgeGE">-</span></button>
 <button class="nav-btn" id="btnBank" role="tab" onclick="setView('bank')">Bank <span class="badge" id="badgeBank">-</span></button>
 ```

 ### JS

 Add state `let geData=null, bankData=null;`. Extend `setView()` and
 `fetchData()` exactly like the existing views (toggle classes, badges
 `badgeGE` = slots.length, `badgeBank` = slot_count, call
 `renderGE()`/`renderBank()`).

 Functions (follow existing vanilla-JS + async/await style, reuse
 `format`, `gp`, `escHtml`, `metric`):

 - `renderGE()` — fetch `/api/ge`, render `.ge-grid` with up to 8
   `geSlotHtml(slot)` + `geEmptySlotHtml()` fillers.
 - `geSlotHtml(slot)` — offer-type label (BUY green / SELL orange),
   `<img class="ge-slot-icon" src="..." onerror="this.style.display='none'">`,
   name, fill bar (`style="width:<pct>%"`, class `buy`/`sell`, add
   `filled` at 100%), price `fmt(slot.price)+' coins'`, and a
   `.ge-collect-btn.visible` when `can_collect`.
 - `collectOffer(positionId, ev)` — POST `/api/ge/collect`
   `{position_id}`; on success set status "Collected <name>: <profit>
   gp" and `fetchData()`; on failure restore button.
 - `geSlotClick(positionId)` — detail in the context panel via
   `metric()`: offer type, qty, buy price, fill %, total value,
   unrealized (color-coded), age, target/stop when present.
 - `showGEHistory()` — overlay `.ge-history-overlay`/`.ge-history-panel`
   fetching `/api/trades?strategy=auto`; table of recent 20 auto trades
   (date, item, qty, buy, sell, profit) + close button.
 - `renderBank()` — fetch `/api/bank`, render `.bank-grid` +
   `.bank-footer` (total value, unrealized P&L, item count).
 - `bankSlotHtml(item)` — qty overlay (`gp()` for >=10k, else `format`),
   icon, `.bank-tooltip` with name/qty/avg buy/current/P&L.
 - `bankSlotClick(itemId)` — detail panel via `metric()`.

 ---

 ## 6. Tests

 Follow the standalone assert-style of `tests/test_positions.py`
 (module-level `_tmpdir`, path monkeypatching of module constants,
 `print("  PASSED ...")`). Key cases:

 `test_ge_offers.py`:
 - `resolve_icon_url` detail/inventory/special chars ("3rd age longsword")
 - `compute_fill_pct`: zero volume (slow default), high volume (fast,
   >= 0.95 after 5 min with vol 1000/qty 100), low volume (slow), ease-out
   shape (5x time > 3x fill), cap at 1.0
 - `build_ge_slots`: empty -> 8 empty, single position shape + icon urls,
   offer_type mapping for traditional vs arbitrage, max 8 slots, stale
   price -> current_price None + unrealized None
 - `collect_offer`: closes + logs trade + returns profit; unknown id
   raises ValueError; no-price fallback sells at buy_price

 `test_bank.py`:
 - empty -> zero totals
 - aggregates multiple positions for one item (weighted avg, position_count)
 - unrealized P&L math with 2% tax (`ge_tax`)
 - sorted by total_value desc
 - `latest=None` -> current_price None, pnl 0

 Mock `positions.POSITIONS_PATH`, `journal.TRADES_PATH`,
 `ge_offers._get_vol` etc. via module constants exactly like
 `test_positions.py` does.

 ---

 ## 7. Verification

 ```bash
 for f in tests/test_*.py; do .venv/bin/python "$f"; done   # 252 + new, all pass
 PYTHONPATH=src .venv/bin/python -m rshelper dashboard &
 curl -s http://127.0.0.1:5555/api/ge | python3 -m json.tool   # no stderr leakage
 curl -s http://127.0.0.1:5555/api/bank | python3 -m json.tool
 ```

 Smoke-check the JSON pipe with `2>/dev/null` clean, then commit:
 `v2.6: Grand Exchange offer UI + Bank holdings view`. Do not push.
