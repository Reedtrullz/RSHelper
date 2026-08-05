"""CLI entry point for RSHelper."""

import argparse
import csv
import io
import json
import math
import sys
from datetime import date

from rshelper.api import fetch_mapping, fetch_latest, fetch_5m, cleanup_stale_cache, fetch_timeseries_batch, fetch_timeseries
from rshelper.scanner import AlchScanner, FlipScanner, MarginScanner, build_items_from_api, trade_size
from rshelper.market import MAX_PRICE_RATIO, ge_tax, price_issue
from rshelper.config import load_config
from rshelper import snapshot, watchlist, tuning
from rshelper.profile import resolve_config_path
from rshelper import __version__


def _fetch_bootstrap(profile: str | None = None):
    """Shared fetch-bootstrap: mapping, latest, 5m volume, and built items."""
    removed = cleanup_stale_cache(profile)
    if removed:
        print(f"  Cleaned {removed} stale cache files", file=sys.stderr)

    print("Fetching OSRS Wiki prices...", file=sys.stderr)
    mapping = fetch_mapping(profile)
    if not mapping:
        print("Error: could not fetch item mapping.", file=sys.stderr)
        sys.exit(1)
    latest = fetch_latest(profile)
    if not latest:
        print("Error: could not fetch latest prices.", file=sys.stderr)
        sys.exit(1)
    volume_5m = fetch_5m(profile) or {}

    print("Building item list...", file=sys.stderr)
    items = build_items_from_api(mapping, latest, volume_5m)
    print(f"  {len(items)} items with price data", file=sys.stderr)
    return mapping, latest, volume_5m, items


def _format_table(results, top: int) -> str:
    """Render results as an aligned text table."""
    rows = results[:top]
    if not rows:
        return "No profitable alchs found."
    name_width = max(len(r.name) for r in rows)
    name_width = min(name_width, 40)
    name_width = max(name_width, 10)
    header = f"{'Rank':<5} {'Item':<{name_width}} {'Buy':>10} {'Alch':>10} {'Profit':>8} {'GP/hr':>10} {'RS':>4} {'Limit':>7}"
    sep = "-" * len(header)
    lines = [header, sep]
    for i, item in enumerate(rows, 1):
        name = item.name[:name_width]
        lines.append(
            f"{i:<5} {name:<{name_width}} {item.buy_price:>10,} {item.alch_value:>10,} "
            f"{item.profit:>8,} {item.gp_per_hour:>10,} {item.rs_score:>4.0f} {item.buy_limit:>7,}"
        )
    return "\n".join(lines)


def _roi_pct(item) -> float:
    """Return flip ROI as a percentage of buy price."""
    return item.profit / item.buy_price * 100 if item.buy_price > 0 else 0.0


def _format_flip_table(results, top: int, capital: int = 0) -> str:
    """Render flip results as an aligned text table."""
    rows = results[:top]
    if not rows:
        return "No profitable flips found."
    name_width = max(len(r.name) for r in rows)
    name_width = min(name_width, 36)
    name_width = max(name_width, 8)
    has_qty = capital > 0
    if has_qty:
        header = (
            f"{'Rank':<4} {'Item':<{name_width}} {'Buy':>9} {'Sell':>9} "
            f"{'Margin':>7} {'ROI':>5} {'RS':>4} {'GP/hr':>9} {'Qty':>6} {'Limit':>6}"
        )
    else:
        header = (
            f"{'Rank':<4} {'Item':<{name_width}} {'Buy':>9} {'Sell':>9} "
            f"{'Margin':>7} {'ROI':>5} {'RS':>4} {'GP/hr':>9} {'Limit':>7}"
        )
    sep = "-" * len(header)
    lines = [header, sep]
    for i, item in enumerate(rows, 1):
        name = item.name[:name_width]
        if has_qty:
            qty = trade_size(item, capital)
            lines.append(
                f"{i:<4} {name:<{name_width}} {item.buy_price:>9,} {item.sell_price:>9,} "
                f"{item.profit:>7,} {_roi_pct(item):>5.1f} {item.rs_score:>4.0f} "
                f"{item.gp_per_hour:>9,} {qty:>6,} {item.buy_limit:>6,}"
            )
        else:
            lines.append(
                f"{i:<4} {name:<{name_width}} {item.buy_price:>9,} {item.sell_price:>9,} "
                f"{item.profit:>7,} {_roi_pct(item):>5.1f} {item.rs_score:>4.0f} "
                f"{item.gp_per_hour:>9,} {item.buy_limit:>7,}"
            )
    return "\n".join(lines)
def _html_output(rows: list[dict], columns: list[str], title: str) -> str:
    """Render results as a self-contained sortable HTML table."""
    from html import escape
    from datetime import datetime

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    col_headers = "".join(f"<th>{escape(c)}</th>" for c in columns)
    tbody = ""
    for row in rows:
        tbody += "<tr>" + "".join(
            f"<td>{escape(str(row.get(c, '')))}</td>" for c in columns
        ) + "</tr>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(title)} — RSHelper</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th {{ background: #f0f0f0; cursor: pointer; padding: 8px 12px; text-align: right; position: sticky; top: 0; }}
  th:first-child, td:first-child {{ text-align: left; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #e0e0e0; text-align: right; }}
  tr:hover {{ background: #fafafa; }}
  .footer {{ color: #999; font-size: 0.85rem; margin-top: 1rem; }}
</style>
</head>
<body>
<h1>{escape(title)}</h1>
<table id="results">
<thead><tr>{col_headers}</tr></thead>
<tbody>{tbody}</tbody>
</table>
<p class="footer">Generated {ts} by RSHelper. Click column headers to sort.</p>
<script>
(function() {{
  var table = document.getElementById("results");
  var headers = table.querySelectorAll("th");
  headers.forEach(function(th, i) {{
    th.addEventListener("click", function() {{
      var tbody = table.querySelector("tbody");
      var rows = Array.from(tbody.querySelectorAll("tr"));
      var asc = th.classList.contains("asc");
      headers.forEach(function(h) {{ h.classList.remove("asc", "desc"); }});
      th.classList.add(asc ? "desc" : "asc");
      rows.sort(function(a, b) {{
        var va = a.cells[i].textContent.replace(/[,\\s]/g, "");
        var vb = b.cells[i].textContent.replace(/[,\\s]/g, "");
        var na = parseFloat(va), nb = parseFloat(vb);
        if (!isNaN(na) && !isNaN(nb)) return asc ? nb - na : na - nb;
        return asc ? vb.localeCompare(va) : va.localeCompare(vb);
      }});
      rows.forEach(function(r) {{ tbody.appendChild(r); }});
    }});
  }});
}})();
</script>
</body>
</html>"""



def _filter_by_name(results, name_filter: str) -> list:
    """Filter results by substring match on item name."""
    if not name_filter:
        return results
    q = name_filter.lower()
    return [r for r in results if q in r.name.lower()]
def _csv_output(results, top: int, fields: list[str], field_map: dict) -> str:
    """Render results as CSV string."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for i, r in enumerate(results[:top], 1):
        row = {"rank": i}
        for f in fields:
            if f == "rank":
                continue
            row[f] = field_map.get(f, lambda x: getattr(x, f, ""))(r)
        writer.writerow(row)
    return out.getvalue()


def alch_scan(args: argparse.Namespace) -> None:
    """Fetch data, scan for profitable alchs, print results."""
    mapping, latest, volume_5m, items = _fetch_bootstrap(args.profile)

    nature_cost = args.nature_rune_cost if args.nature_rune_cost > 0 else _fetch_nature_rune_cost(mapping, latest)
    if not args.nature_rune_cost:
        print(f"  Nature rune: {nature_cost} gp", file=sys.stderr)

    scanner = AlchScanner(nature_rune_cost=nature_cost)
    results = scanner.scan(
        items,
        members_only=args.members_only,
        min_volume=args.min_volume,
    )
    print(f"  {len(results)} profitable alchs", file=sys.stderr)
    if args.name:
        results = _filter_by_name(results, args.name)
        print(f"  {len(results)} after --name filter", file=sys.stderr)
    else:
        print(file=sys.stderr)

    if args.csv:
        from dataclasses import asdict
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=[
            "rank", "name", "buy_price", "alch_value", "profit", "gp_per_hour",
            "sell_price", "volume", "buy_limit",
        ], extrasaction='ignore')
        writer.writeheader()
        for i, item in enumerate(results[:args.top], 1):
            row = asdict(item)
            row["rank"] = i
            writer.writerow(row)
        print(out.getvalue())
    elif args.json:
        print(json.dumps([
            {
                "rank": i + 1,
                "name": r.name,
                "buy_price": r.buy_price,
                "alch_value": r.alch_value,
                "profit": r.profit,
                "gp_per_hour": r.gp_per_hour,
                "sell_price": r.sell_price,
                "volume": r.volume,
                "buy_limit": r.buy_limit,
            }
            for i, r in enumerate(results[:args.top])
        ], indent=2))
    elif args.html:
        print(_html_output([
            {"Rank": i + 1, "Item": r.name, "Buy": f"{r.buy_price:,}",
             "Alch": f"{r.alch_value:,}", "Profit": f"{r.profit:,}",
             "GP/hr": f"{r.gp_per_hour:,}", "RS": f"{r.rs_score:.0f}", "Limit": f"{r.buy_limit:,}"}
            for i, r in enumerate(results[:args.top])
        ], ["Rank", "Item", "Buy", "Alch", "Profit", "GP/hr", "RS", "Limit"], "Alchemy Scan"))
    else:
        print(_format_table(results, args.top))

    if getattr(args, 'save_snapshot', False):
        _save_alch_snapshot(results[:args.top], args.profile)


def _fetch_nature_rune_cost(mapping: list[dict], latest: dict) -> int:
    """Look up nature rune (id 561) buy price from API data."""
    for entry in mapping:
        if entry.get("id") == 561:
            price = latest.get("561", {})
            if isinstance(price, dict):
                high = price.get("high", 0)
                if high and high > 0:
                    return high
            break
    return 147


def flip_scan(args: argparse.Namespace) -> None:
    """Fetch data, scan for profitable flips, print results."""
    mapping, latest, volume_5m, items = _fetch_bootstrap(args.profile)

    direction = getattr(args, "flip_direction", "arbitrage")
    scanner = FlipScanner(direction=direction, ge_slots=args.ge_slots)
    results = scanner.scan(
        items,
        members_only=args.members_only,
        min_volume=args.min_volume,
        min_margin=args.min_margin,
    )
    print(f"  {len(results)} profitable flips ({direction} mode)", file=sys.stderr)
    if args.name:
        results = _filter_by_name(results, args.name)
        print(f"  {len(results)} after --name filter", file=sys.stderr)
    else:
        print(file=sys.stderr)

    if args.csv:
        from dataclasses import asdict
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=[
            "rank", "name", "buy_price", "sell_price", "profit", "roi",
            "capital_per_unit", "gp_per_hour", "volume", "buy_limit",
        ], extrasaction='ignore')
        writer.writeheader()
        for i, item in enumerate(results[:args.top], 1):
            row = asdict(item)
            row["rank"] = i
            row["roi"] = round(_roi_pct(item), 2)
            row["capital_per_unit"] = item.buy_price
            writer.writerow(row)
        print(out.getvalue())
    elif args.json:
        print(json.dumps([
            {
                "rank": i + 1,
                "name": r.name,
                "buy_price": r.buy_price,
                "sell_price": r.sell_price,
                "margin": r.profit,
                "roi": round(_roi_pct(r), 2),
                "capital_per_unit": r.buy_price,
                "gp_per_hour": r.gp_per_hour,
                "volume": r.volume,
                "buy_limit": r.buy_limit,
            }
            for i, r in enumerate(results[:args.top])
        ], indent=2))
    elif args.html:
        capital = getattr(args, 'capital', 0)
        cols = ["Rank", "Item", "Buy", "Sell", "Margin", "ROI%", "RS", "GP/hr", "Limit"]
        rows = [{"Rank": i + 1, "Item": r.name, "Buy": f"{r.buy_price:,}",
                 "Sell": f"{r.sell_price:,}", "Margin": f"{r.profit:,}",
                 "ROI%": f"{_roi_pct(r):.1f}",
                 "GP/hr": f"{r.gp_per_hour:,}", "RS": f"{r.rs_score:.0f}", "Limit": f"{r.buy_limit:,}"}
                for i, r in enumerate(results[:args.top])]
        if capital:
            cols.insert(-1, "Qty")
            for i, row in enumerate(rows):
                row["Qty"] = f"{trade_size(results[i], capital):,}"
        print(_html_output(rows, cols, "Flip Scan"))
    else:
        print(_format_flip_table(results, args.top, getattr(args, 'capital', 0)))

    if getattr(args, 'save_snapshot', False):
        _save_flip_snapshot(results[:args.top], args.profile)


def process_scan(args: argparse.Namespace) -> None:
    """Fetch data, scan materials-processing recipes, print results."""
    mapping, latest, volume_5m, items = _fetch_bootstrap(args.profile)

    from rshelper.scanner import ProcessScanner
    scanner = ProcessScanner()
    skill = getattr(args, "skill", "")
    results = scanner.scan(
        items,
        members_only=args.members_only,
        min_volume=args.min_volume,
        min_profit=args.min_profit,
        capital=args.capital,
        skill=skill,
    )
    scope = f" ({skill})" if skill else ""
    print(f"  {len(results)} profitable processing recipes{scope}", file=sys.stderr)
    if args.name:
        results = _filter_by_name(results, args.name)
        print(f"  {len(results)} after --name filter", file=sys.stderr)
    else:
        print(file=sys.stderr)

    if args.csv:
        from dataclasses import asdict
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=[
            "rank", "name", "input_cost", "sell_price", "profit", "roi",
            "gp_per_hour", "volume", "buy_limit",
        ], extrasaction='ignore')
        writer.writeheader()
        for i, item in enumerate(results[:args.top], 1):
            row = asdict(item)
            row["rank"] = i
            row["roi"] = round(_roi_pct(item), 2)
            writer.writerow(row)
        print(out.getvalue())
    elif args.json:
        print(json.dumps([
            {
                "rank": i + 1,
                "name": r.name,
                "input_cost": r.input_cost,
                "sell_price": r.sell_price,
                "profit": r.profit,
                "roi": round(_roi_pct(r), 2),
                "gp_per_hour": r.gp_per_hour,
                "volume": r.volume,
                "buy_limit": r.buy_limit,
            }
            for i, r in enumerate(results[:args.top])
        ], indent=2))
    elif args.html:
        cols = ["Rank", "Output", "Input Cost", "Sell", "Profit", "ROI%", "GP/hr"]
        rows = [{"Rank": i + 1, "Output": r.name,
                 "Input Cost": f"{r.input_cost:,}", "Sell": f"{r.sell_price:,}",
                 "Profit": f"{r.profit:,}", "ROI%": f"{_roi_pct(r):.1f}",
                 "GP/hr": f"{r.gp_per_hour:,}"}
                for i, r in enumerate(results[:args.top])]
        print(_html_output(rows, cols, "Materials Processing"))
    else:
        print(_format_process_table(results, args.top))

    if getattr(args, 'save_snapshot', False):
        _save_process_snapshot(results[:args.top], args.profile)


def _format_process_table(results, top: int) -> str:
    """Render process-scan results as an aligned text table."""
    rows = results[:top]
    if not rows:
        return "No profitable processing recipes."
    name_width = max((len(r.name) for r in rows), default=10)
    name_width = min(name_width, 24)
    name_width = max(name_width, 6)
    header = (f"{'Output':<{name_width}} {'InputCost':>9} {'Sell':>8} "
              f"{'Profit':>7} {'ROI%':>6} {'GP/hr':>9}")
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(f"{r.name:<{name_width}} {r.input_cost:>9,} "
                     f"{r.sell_price:>8,} {r.profit:>7,} "
                     f"{_roi_pct(r):>6.1f} {r.gp_per_hour:>9,}")
    return "\n".join(lines)


def _save_process_snapshot(results, profile: str | None = None) -> None:
    """Persist a process scan snapshot for diffing across days."""
    from rshelper import snapshot
    data = [{
        "item_id": r.id, "name": r.name,
        "input_cost": r.input_cost, "sell_price": r.sell_price,
        "profit": r.profit, "gp_per_hour": r.gp_per_hour,
        "volume": r.volume, "buy_limit": r.buy_limit,
    } for r in results]
    snapshot.save("process", data, profile)
    from rshelper import tuning
    tuning.record_if_changed(profile)


def _format_margin_table(results, top: int, lookup: dict, capital: int = 0,
                         risk_metrics: dict | None = None) -> str:
    """Render margin-check results as an aligned text table."""
    rows = results[:top]
    if not rows:
        return "No items with sufficient timeseries data."
    name_width = max((len(lookup[a.item_id].name) for a in rows if a.item_id in lookup), default=10)
    name_width = min(name_width, 24)
    name_width = max(name_width, 6)
    has_risk = risk_metrics is not None
    if has_risk:
        header = (
            f"{'Rank':<4} {'Item':<{name_width}} {'Buy':>9} {'Sell':>9} "
            f"{'CurProfit':>9} {'Conf':>5} {'ExpGP/hr':>10} {'AvgMar':>8} "
            f"{'Worst':>8} {'Stab':>5} {'Hrs':>5}"
        )
    else:
        header = (
            f"{'Rank':<4} {'Item':<{name_width}} {'Buy':>9} {'Sell':>9} "
            f"{'CurProfit':>9} {'Conf':>5} {'ExpGP/hr':>10} {'AvgMar':>8} {'Hrs':>5}"
        )
    sep = "-" * len(header)
    lines = [header, sep]
    for i, a in enumerate(rows, 1):
        item = lookup.get(a.item_id)
        name = item.name[:name_width] if item else str(a.item_id)
        buy = item.buy_price if item else 0
        sell = item.sell_price if item else 0
        risk = risk_metrics.get(a.item_id) if risk_metrics else None
        if has_risk:
            worst = risk["worst"] if risk else 0
            stab = risk["stability"] if risk else 0
            lines.append(
                f"{i:<4} {name:<{name_width}} {buy:>9,} {sell:>9,} "
                f"{a.current_profit:>9,} {a.confidence:>5.2f} {a.expected_gp_per_hour:>10,} "
                f"{a.avg_margin:>8,.0f} {worst:>8,} {stab:>5.2f} {a.window_hours:>5.0f}"
            )
        else:
            lines.append(
                f"{i:<4} {name:<{name_width}} {buy:>9,} {sell:>9,} "
                f"{a.current_profit:>9,} {a.confidence:>5.2f} {a.expected_gp_per_hour:>10,} "
                f"{a.avg_margin:>8,.0f} {a.window_hours:>5.0f}"
            )
    return "\n".join(lines)


def _resolve_item(args: argparse.Namespace) -> dict:
    """Look up an item by exact name or unique substring; exits on failure."""
    from rshelper.api import fetch_mapping
    profile = getattr(args, "profile", None)
    mapping = fetch_mapping(profile) or []
    q = args.item.lower()
    entry = next((e for e in mapping if (e.get("name") or "").lower() == q), None)
    if entry is not None:
        return entry
    matches = [e for e in mapping if q in (e.get("name") or "").lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"Multiple matches for '{args.item}':", file=sys.stderr)
        for e in matches[:20]:
            print(f"  {e['id']:>6}  {e['name']}", file=sys.stderr)
    else:
        print(f"Item not found: {args.item}", file=sys.stderr)
    sys.exit(1)


def _resolve_paper_prices(entry: dict, profile: str | None, direction: str
                          ) -> tuple[int, int]:
    """Live guarded (buy_price, sell_price) for the given flip direction."""
    from rshelper.api import fetch_latest
    latest = fetch_latest(profile) or {}
    price = latest.get(str(entry["id"])) or {}
    if not isinstance(price, dict) or price_issue(price):
        print(f"No reliable live price data for {entry.get('name')} "
              f"(stale or manipulated prices).", file=sys.stderr)
        sys.exit(1)
    high = int(price.get("high", 0) or 0)
    low = int(price.get("low", 0) or 0)
    if direction == "traditional":
        buy_price, sell_price = low, high
    else:
        buy_price, sell_price = high, low
    if buy_price <= 0 or sell_price <= 0:
        print(f"No live price data for {entry.get('name')}.", file=sys.stderr)
        sys.exit(1)
    return buy_price, sell_price


def _size_qty(args: argparse.Namespace, entry: dict, buy_price: int) -> int:
    """Size a trade from --qty, --capital, or default to 1."""
    if args.qty > 0:
        return args.qty
    if args.capital > 0:
        buy_limit = int(entry.get("limit") or 0)
        qty = min(buy_limit, args.capital // buy_price) if buy_price > 0 else 0
        if qty <= 0:
            print(f"Capital {args.capital:,} gp is below one unit of "
                  f"{entry.get('name')} at {buy_price:,} gp.", file=sys.stderr)
            sys.exit(1)
        return qty
    return 1


def _trade_paper(args: argparse.Namespace) -> None:
    """Log a paper trade at live GE prices, sized from --capital or --qty."""
    from rshelper.journal import log_trade
    profile = getattr(args, "profile", None)
    entry = _resolve_item(args)
    buy_price, sell_price = _resolve_paper_prices(
        entry, profile, args.flip_direction)
    qty = _size_qty(args, entry, buy_price)
    trade = log_trade(entry["id"], entry["name"], qty, buy_price,
                      sell_price, note=args.note or "paper", profile=profile,
                      strategy="manual")
    mode = args.flip_direction
    print(f"Paper trade #{trade.id}: {trade.qty:,}x {trade.name} "
          f"({mode}) buy {trade.buy_price:,} gp, sell {trade.sell_price:,} gp "
          f"— profit: {trade.profit:+,} gp "
          f"(tax: {trade.tax_paid:,})")


def _trade_open(args: argparse.Namespace) -> None:
    """Open a paper position: buy and hold at the live price."""
    from rshelper.positions import open_position
    profile = getattr(args, "profile", None)
    entry = _resolve_item(args)
    buy_price, sell_price = _resolve_paper_prices(
        entry, profile, args.flip_direction)
    qty = _size_qty(args, entry, buy_price)
    entry_offer = sell_price if args.flip_direction == "traditional" else None
    pos = open_position(entry["id"], entry["name"], qty, buy_price,
                        direction=args.flip_direction,
                        note=args.note or "paper", profile=profile,
                        entry_sell=sell_price, entry_offer=entry_offer)
    print(f"Opened position #{pos.id}: {pos.qty:,}x {pos.name} at "
          f"{pos.buy_price:,} gp ({pos.direction})")


def _trade_close(args: argparse.Namespace) -> None:
    """Close open paper positions for an item at the live price."""
    from rshelper.positions import close_positions, list_positions, open_qty
    from rshelper.journal import log_trade
    profile = getattr(args, "profile", None)
    entry = _resolve_item(args)
    open_positions = [p for p in list_positions(profile) if p.item_id == entry["id"]]
    if not open_positions:
        print(f"No open positions for {entry['name']}.", file=sys.stderr)
        sys.exit(1)
    # Close at the price convention of the oldest open lot for this item.
    direction = open_positions[0].direction
    if direction == "traditional":
        _, sell_price = _resolve_paper_prices(entry, profile, "traditional")
    else:
        # Arbitrage positions sell at the bid (low). Fetch the raw guarded
        # pair and take the sell leg explicitly — never a live-price side.
        _buy, _sell = _resolve_paper_prices(entry, profile, "arbitrage")
        sell_price = _sell
    qty = args.qty if args.qty > 0 else sum(p.qty for p in open_positions)
    try:
        lots = close_positions(entry["id"], qty, sell_price, profile)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    for lot in lots:
        log_trade(entry["id"], lot["name"], lot["qty"], lot["buy_price"],
                  sell_price, note="paper", profile=profile, strategy="manual",
                  exit_reason="manual")
    profit = sum(l["profit"] for l in lots)
    tax = sum(l["tax_paid"] for l in lots)
    print(f"Closed {qty:,}x {entry['name']} at {sell_price:,} gp "
          f"({direction}) — profit: {profit:+,} gp (tax: {tax:,})")


def _trade_positions(args: argparse.Namespace) -> None:
    """List open paper positions with unrealized P&L at live prices."""
    from rshelper.positions import list_positions
    from rshelper.api import fetch_latest
    from rshelper.market import ge_tax
    profile = getattr(args, "profile", None)
    positions = list_positions(profile)
    latest = fetch_latest(profile) or {}
    rows = []
    for p in positions:
        price = latest.get(str(p.item_id))
        usable = isinstance(price, dict) and price_issue(price) is None
        sell = None
        unrealized = None
        if usable:
            sell = int(price.get("low", 0) or 0) if p.direction == "arbitrage" \
                else int(price.get("high", 0) or 0)
        if usable and sell and sell > 0:
            tax = ge_tax(sell)
            unrealized = (sell - p.buy_price) * p.qty - tax * p.qty
        rows.append({
            "id": p.id, "item_id": p.item_id, "name": p.name, "qty": p.qty,
            "buy_price": p.buy_price, "direction": p.direction,
            "opened_at": p.opened_at, "current": sell,
            "unrealized": unrealized, "note": p.note,
        })
    if args.json:
        print(json.dumps(rows, indent=2))
        return rows
    if not rows:
        print("No open positions.")
        return rows
    nw = max(len(r["name"]) for r in rows)
    nw = min(nw, 30)
    print(f"{'ID':<4} {'Item':<{nw}} {'Qty':>6} {'Buy':>10} {'Current':>10} "
          f"{'Unrealized':>12} {'Opened':<12}")
    print("-" * (66 + nw))
    for r in rows:
        cur = f"{r['current']:,}" if r["current"] else "-"
        unreal = f"{r['unrealized']:+,}" if r["unrealized"] is not None else "-"
        print(f"{r['id']:<4} {r['name'][:nw]:<{nw}} {r['qty']:>6,} "
              f"{r['buy_price']:>10,} {cur:>10} {unreal:>12} "
              f"{r['opened_at'][:10]}")
    return rows


def trade_status(args: argparse.Namespace) -> None:
    """One-shot summary: open positions, unrealized, realized P&L, trader."""
    from rshelper.positions import list_positions
    from rshelper.api import fetch_latest
    from rshelper.journal import compute_pnl
    from rshelper.market import ge_tax
    from rshelper.trader import trader_status
    profile = getattr(args, "profile", None)
    latest = fetch_latest(profile) or {}
    positions = list_positions(profile)
    rows = []
    unreal = 0
    for p in positions:
        price = latest.get(str(p.item_id))
        usable = isinstance(price, dict) and price_issue(price) is None
        sell = None
        unrealized = None
        if usable:
            sell = int(price.get("low", 0) or 0) if p.direction == "arbitrage" \
                else int(price.get("high", 0) or 0)
        if usable and sell and sell > 0:
            tax = ge_tax(sell)
            unrealized = (sell - p.buy_price) * p.qty - tax * p.qty
            unreal += unrealized
        rows.append({
            "id": p.id, "item_id": p.item_id, "name": p.name, "qty": p.qty,
            "buy_price": p.buy_price, "direction": p.direction,
            "opened_at": p.opened_at, "current": sell,
            "unrealized": unrealized, "note": p.note,
        })
    pnl = compute_pnl(profile=profile, strategy="auto")
    trader = trader_status(profile) or {"running": False}
    if args.json:
        print(json.dumps({
            "positions": rows,
            "unrealized": unreal,
            "realized_pnl": pnl.total_profit,
            "auto_trades": pnl.trade_count,
            "trader_running": bool(trader.get("running")),
            "trader": trader,
        }, indent=2))
        return
    print(f"\n  Trader: {'running' if trader.get('running') else 'not running'}"
          f" (profile {profile or 'default'})")
    print(f"  Realized P&L (auto): {pnl.total_profit:+,} gp "
          f"({pnl.trade_count} trades)")
    print(f"  Unrealized: {unreal:+,} gp "
          f"({len(rows)} open position{'s' if len(rows) != 1 else ''})")
    if not rows:
        print("\n  No open positions.")
        return
    nw = max(len(r["name"]) for r in rows)
    nw = min(nw, 30)
    print(f"\n  {'ID':<4} {'Item':<{nw}} {'Qty':>6} {'Buy':>10} "
          f"{'Current':>10} {'Unrealized':>12}")
    print("  " + "-" * (56 + nw))
    for r in rows:
        cur = f"{r['current']:,}" if r["current"] else "-"
        unreal_txt = f"{r['unrealized']:+,}" if r["unrealized"] is not None else "-"
        print(f"  {r['id']:<4} {r['name'][:nw]:<{nw}} {r['qty']:>6,} "
              f"{r['buy_price']:>10,} {cur:>10} {unreal_txt:>12}")


def history_cmd(args: argparse.Namespace) -> None:
    """Progression: daily buckets, tuning eras, and per-item P&L (dashboard parity)."""
    from rshelper.history import build_history
    profile = getattr(args, "profile", None)
    h = build_history(profile=profile, paper_only=not args.all,
                      strategy=args.strategy)
    if args.json:
        print(json.dumps(h, indent=2, default=str))
        return
    s = h["summary"]
    print(f"\n  History (paper {'all' if args.all else 'only'})")
    print("  " + "=" * 50)
    print(f"  Total profit:     {s['total_profit']:>+15,} gp")
    print(f"  ROI:              {s['roi_pct']:>14.2f}%")
    print(f"  Trades:           {s['trade_count']:>15}")
    print(f"  Win rate:         {s['win_rate']:>14.1f}%")
    print(f"  Items traded:     {s['items_traded']:>15}")
    print(f"  Active days:      {s['active_days']:>15}")
    buckets = h.get("buckets", [])
    if buckets:
        print(f"\n  {'Date':<12} {'Trades':>7} {'Profit':>12} {'Cum':>12} {'Win%':>7}")
        print("  " + "-" * 52)
        for b in buckets:
            wr = f"{b['win_rate']:.0f}%" if b.get("win_rate") is not None else "-"
            print(f"  {b['date']:<12} {b['trade_count']:>7,} "
                  f"{b['profit']:>+12,} {b['cumulative_profit']:>+12,} {wr:>7}")
    eras = h.get("eras", [])
    if eras:
        print(f"\n  {'Start':<12} {'End':<12} {'Trades':>7} {'Profit':>12} {'Win%':>7}")
        print("  " + "-" * 52)
        for e in eras:
            wr = f"{e['win_rate']:.0f}%" if e.get("win_rate") is not None else "-"
            print(f"  {e['start']:<12} {e['end']:<12} {e['trade_count']:>7,} "
                  f"{e['profit']:>+12,} {wr:>7}")
    items = h.get("items", [])
    if items:
        print(f"\n  {'Item':<28} {'Trades':>6} {'Qty':>9} {'Profit':>11} {'ROI':>7} {'Win%':>6}")
        print("  " + "-" * 68)
        for r in items[:20]:
            print(f"  {r['name'][:28]:<28} {r['trade_count']:>6} "
                  f"{r['qty']:>9,} {r['profit']:>+11,} "
                  f"{r['roi_pct']:>6.1f}% {r['win_rate']:>5.1f}%")
        if len(items) > 20:
            print(f"  ... and {len(items) - 20} more")
    print()


def auto_trade_cmd(args: argparse.Namespace) -> None:
    """Autonomous paper trader: find and execute paper trades on a loop."""
    from rshelper.trader import run_trader, stop_trader, trader_status
    profile = getattr(args, "profile", None)
    if args.stop:
        stopped = stop_trader(profile)
        print("Trader stopped." if stopped else "No trader running.",
              file=sys.stdout if stopped else sys.stderr)
        return
    if args.status:
        status = trader_status(profile)
        if not status:
            print("Trader: not running (no state yet)")
            return
        if args.json:
            print(json.dumps(status, indent=2))
            return
        running = "running" if status.get("running") else "not running"
        where = "this machine" if status.get("local") else "synced state (runs on Mac)"
        print(f"Trader: {running} ({where}, profile {status['profile']})")
        if status.get("pid"):
            print(f"  PID: {status['pid']}")
        print(f"  Started: {status.get('started_iso', '-')}")
        age = status.get("last_cycle_age_sec")
        age_s = f"{age:.0f}s ago" if age is not None else "-"
        print(f"  Last cycle: {status.get('last_cycle_iso', '-')} ({age_s})")
        if status.get("stale"):
            print("  WARNING: last cycle is stale (>15 min); the trader may "
                  "have stopped or the synced state is behind.", file=sys.stderr)
        print(f"  Realized P&L: {status.get('realized_pnl', 0):+,} gp")
        jpnl = status.get("journal_realized_pnl")
        if jpnl is not None:
            jcount = status.get("journal_auto_trades")
            label = f" ({jcount} auto trades)" if jcount is not None else ""
            print(f"  Journal P&L (auto): {jpnl:+,} gp{label}")
        print(f"  Cycles: {status.get('cycles', 0)}  "
              f"Errors: {status.get('errors', 0)}")
        exits = status.get("exits_by_reason") or {}
        if exits:
            for reason, row in sorted(exits.items()):
                print(f"  Exits [{reason}]: {row.get('count', 0)} "
                      f"(P&L {row.get('profit', 0):+,} gp)")
        if status.get("last_result"):
            r = status["last_result"]
            print(f"  Last result: candidates={r.get('candidates', 0)} "
                  f"opened={len(r.get('opened', []))} "
                  f"closed={len(r.get('closed', []))} "
                  f"error={r.get('error', 'none')}")
        return
    from rshelper.config import load_config
    cfg = load_config(profile)
    result = run_trader(cfg.trader, interval=args.interval or None,
                        profile=profile, once=args.once)
    if args.once and result:
        print(json.dumps(result, indent=2))


def margin_check(args: argparse.Namespace) -> None:
    """Fetch data, scan flips, then analyze timeseries history for confidence scoring."""
    mapping, latest, volume_5m, items = _fetch_bootstrap(args.profile)

    direction = getattr(args, "flip_direction", "arbitrage")
    # First: find profitable flips
    flip_scanner = FlipScanner(direction=direction, ge_slots=args.ge_slots)
    flips = flip_scanner.scan(
        items,
        members_only=args.members_only,
        min_volume=args.min_volume,
        min_margin=args.min_margin,
    )
    print(f"  {len(flips)} profitable flips ({direction} mode)", file=sys.stderr)

    # Apply --name filter before selecting candidates
    if args.name:
        flips = _filter_by_name(flips, args.name)
        print(f"  {len(flips)} after --name filter", file=sys.stderr)

    # Take top N candidates for timeseries analysis
    candidates = flips[:args.check]
    if not candidates:
        print("\nNo flip candidates to check.", file=sys.stderr)
        return

    # Build lookup: item_id -> Item (includes names for display)
    lookup = {item.id: item for item in items}

    print(f"\nFetching timeseries for top {len(candidates)} candidates...", file=sys.stderr)
    candidate_ids = [c.id for c in candidates]
    ts_data = fetch_timeseries_batch(
        candidate_ids,
        timestep="5m",
        on_progress=lambda cur, tot: print(
            f"  [{cur}/{tot}] fetching history...", end="\r", file=sys.stderr),
        workers=getattr(args, "workers", 4),
        profile=args.profile if hasattr(args, "profile") else None,
    )
    print(f"\n  {len(ts_data)}/{len(candidate_ids)} items have timeseries data", file=sys.stderr)

    if not ts_data:
        print("No timeseries data available.", file=sys.stderr)
        return

    # Analyze
    margin_scanner = MarginScanner()
    results = margin_scanner.scan(lookup, ts_data, members_only=args.members_only, direction=direction)
    print(f"  {len(results)} items analyzed\n", file=sys.stderr)

    if args.csv:
        from dataclasses import asdict
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=[
            "rank", "name", "item_id", "current_profit", "expected_gp_per_hour", "confidence", "reliability", "profitability_score",
            "avg_margin", "margin_consistency", "margin_volatility", "avg_spread_pct",
            "avg_volume", "spread_score", "volume_score", "volatility_score",
            "datapoints", "window_hours", "margin_trend",
        ], extrasaction='ignore')
        writer.writeheader()
        for i, a in enumerate(results[:args.top], 1):
            row = asdict(a)
            row["rank"] = i
            row["name"] = lookup[a.item_id].name if a.item_id in lookup else str(a.item_id)
            for k in ("confidence", "reliability", "profitability_score",
                      "margin_consistency", "avg_spread_pct"):
                row[k] = round(row[k], 4)
            row["avg_margin"] = round(row["avg_margin"], 0)
            row["margin_volatility"] = round(row["margin_volatility"], 4)
            row["avg_volume"] = round(row["avg_volume"], 0)
            row["window_hours"] = round(row["window_hours"], 1)
            writer.writerow(row)
        print(out.getvalue())
    elif args.json:
        out = []
        for i, a in enumerate(results[:args.top], 1):
            item = lookup.get(a.item_id)
            out.append({
                "rank": i,
                "name": item.name if item else str(a.item_id),
                "item_id": a.item_id,
                "current_profit": a.current_profit,
                "expected_gp_per_hour": a.expected_gp_per_hour,
                "confidence": round(a.confidence, 3),
                "reliability": round(a.reliability, 3),
                "profitability_score": round(a.profitability_score, 3),
                "avg_margin": round(a.avg_margin, 0),
                "margin_consistency": round(a.margin_consistency, 3),
                "current_vs_avg": round(a.current_vs_avg, 2),
                "margin_volatility": round(a.margin_volatility, 4),
                "avg_spread_pct": round(a.avg_spread_pct, 2),
                "avg_volume": round(a.avg_volume, 0),
                "datapoints": a.datapoints,
                "window_hours": round(a.window_hours, 1),
                "margin_trend": round(a.margin_trend, 3),
            })
        print(json.dumps(out, indent=2))
    else:
        risk = {}
        if getattr(args, 'risk', False) and ts_data:
            for item_id, ts in ts_data.items():
                margins = []
                for dp in ts:
                    h = dp.get("avgHighPrice")
                    l = dp.get("avgLowPrice")
                    if h and l:
                        h, l = int(h), int(l)
                        if max(h, l) > MAX_PRICE_RATIO * min(h, l):
                            continue
                        if direction == "traditional":
                            m = h - l - ge_tax(h)
                        else:
                            m = l - h - ge_tax(l)
                        margins.append(m)
                if margins:
                    mean = sum(margins) / len(margins)
                    var = sum((m - mean)**2 for m in margins) / len(margins)
                    risk[item_id] = {
                        "worst": min(margins),
                        "stability": math.sqrt(var) / max(1, abs(mean)) if mean != 0 else 0,
                    }
        print(_format_margin_table(results, args.top, lookup,
                                   getattr(args, 'capital', 0),
                                   risk if risk else None))

    if getattr(args, 'save_snapshot', False):
        _save_margin_snapshot(results[:args.top], lookup, args.profile)


def item_info(args: argparse.Namespace) -> None:
    """Look up a single item by name or ID."""
    removed = cleanup_stale_cache(args.profile if hasattr(args, "profile") else None)
    if removed:
        print(f"  Cleaned {removed} stale cache files", file=sys.stderr)

    if args.json:
        print("Fetching data...", file=sys.stderr)
    else:
        print("Fetching data...", file=sys.stderr)
    mapping = fetch_mapping(args.profile if hasattr(args, "profile") else None)
    if not mapping:
        print("Error: could not fetch item mapping.", file=sys.stderr)
        sys.exit(1)
    latest = fetch_latest(args.profile if hasattr(args, "profile") else None)
    if not latest:
        print("Error: could not fetch latest prices.", file=sys.stderr)
        sys.exit(1)

    # Find item — try exact ID first, then name match
    query = args.item.lower()
    matched: dict | None = None
    for entry in mapping:
        if str(entry.get("id")) == query:
            matched = entry
            break
    if matched is None:
        candidates = [e for e in mapping if query in (e.get("name") or "").lower()]
        if len(candidates) == 1:
            matched = candidates[0]
        elif len(candidates) > 1:
            if args.json:
                print(json.dumps([{"id": e["id"], "name": e["name"]} for e in candidates[:20]], indent=2))
            else:
                print(f"Multiple matches for '{args.item}':")
                for e in candidates[:20]:
                    print(f"  {e['id']:>6}  {e['name']}")
                if len(candidates) > 20:
                    print(f"  ... and {len(candidates) - 20} more")
            return
        else:
            print(f"No item found matching '{args.item}'", file=sys.stderr)
            sys.exit(1)

    item_id = matched["id"]
    name = matched.get("name", "")
    members = matched.get("members", False)
    buy_limit = int(matched.get("limit") or 0)
    alch_value = int(matched.get("highalch") or 0)

    price = latest.get(str(item_id), {})
    buy_price = int(price.get("high") or 0)
    sell_price = int(price.get("low") or 0)
    issue = price_issue(price)
    if issue:
        print(f"  Warning: price data for {name} is unusable ({issue}); "
              f"values may be stale or manipulated.", file=sys.stderr)

    if args.json:
        out = {
            "id": item_id, "name": name, "members": members,
            "buy_limit": buy_limit, "alch_value": alch_value,
            "buy_price": buy_price, "sell_price": sell_price,
            "price_warning": issue if issue else None,
        }
        # Alch
        nature_cost = _fetch_nature_rune_cost(mapping, latest)
        alch_profit = alch_value - buy_price - nature_cost
        out["alch_profit"] = alch_profit
        # Flip
        # Margin: buy-high minus sell-low (consistent with spread display)
        flip_margin = buy_price - sell_price
        tax_flip = ge_tax(buy_price)
        flip_profit = flip_margin - tax_flip
        out["flip_margin"] = flip_margin
        out["flip_tax"] = tax_flip
        out["flip_profit"] = flip_profit
        if getattr(args, "tax_curve", False) and buy_price > 0:
            steps = [1.00, 1.01, 1.02, 1.03, 1.05, 1.07, 1.10, 1.15, 1.20, 1.30, 1.50]
            out["tax_curve"] = [{"sell_price": int(buy_price * m),
                                 "tax": ge_tax(int(buy_price * m)),
                                 "profit": int(buy_price * m) - buy_price
                                 - ge_tax(int(buy_price * m))}
                                for m in steps]
        print(json.dumps(out, indent=2))
    else:
        tag = " (members)" if members else ""
        print(f"\n  {name}{tag}  [id={item_id}]")
        print(f"  Buy limit: {buy_limit:,} / 4h")
        print(f"  Alch value: {alch_value:,} gp")
        print(f"  Instant buy: {buy_price:,} gp")
        print(f"  Instant sell: {sell_price:,} gp")
        spread = buy_price - sell_price
        print(f"  Spread: {spread:,} gp")

        # Alch
        nature_cost = _fetch_nature_rune_cost(mapping, latest)
        alch_profit = alch_value - buy_price - nature_cost
        alch_line = f"  Alch profit: {alch_profit:,} gp/cast"
        if alch_profit <= 0:
            alch_line += " (not profitable)"
        print(alch_line)

        # Flip
        # Margin: buy-high minus sell-low (consistent with spread display)
        flip_margin = buy_price - sell_price
        tax_flip = ge_tax(buy_price)
        flip_profit = flip_margin - tax_flip
        flip_line = f"  Flip margin: {flip_margin:,} gp (tax: {tax_flip:,}, net: {flip_profit:,})"
        if flip_profit <= 0:
            flip_line += " (not profitable)"
        print(flip_line)


    # Wiki URL
    wiki_name = name.replace(" ", "_")
    wiki_url = f"https://oldschool.runescape.wiki/w/Exchange:{wiki_name}"
    if getattr(args, "wiki", False):
        print(f"\n  Wiki: {wiki_url}")
    if getattr(args, "wiki_open", False):
        import webbrowser
        webbrowser.open(wiki_url)
        print(f"  Opening {wiki_url}")

    # Tax curve: show profit at different sell prices
    if getattr(args, "tax_curve", False) and buy_price > 0:
        if not args.json:
            print(f"\n  Tax curve (buy at {buy_price:,} gp):")
            print(f"  {'Sell Price':>12}  {'Tax':>10}  {'Profit':>10}  {'ROI':>6}")
            print(f"  " + "-" * 45)
            steps = [1.00, 1.01, 1.02, 1.03, 1.05, 1.07, 1.10, 1.15, 1.20, 1.30, 1.50]
            for mult in steps:
                sp = int(buy_price * mult)
                tax = ge_tax(sp)
                profit = sp - buy_price - tax
                roi = profit / buy_price * 100 if buy_price > 0 else 0
                cap_mark = " *" if tax == 5_000_000 else ""
                print(f"  {sp:>12,}  {tax:>10,}  {profit:>+10,}  {roi:>5.1f}%{cap_mark}")
    # Timeseries if requested
    if args.timeseries or getattr(args, "predict", False):
        ts = fetch_timeseries(item_id, "5m", args.profile if hasattr(args, "profile") else None)
        if ts:
            from rshelper.analysis import analyze_timeseries
            analysis = analyze_timeseries(item_id, ts, buy_price, sell_price)
            if analysis:
                if args.json:
                    print()
                    print(json.dumps({
                        "timeseries_analysis": {
                            "confidence": round(analysis.confidence, 3),
                            "reliability": round(analysis.reliability, 3),
                            "profitability_score": round(analysis.profitability_score, 3),
                            "avg_margin": round(analysis.avg_margin, 0),
                            "margin_consistency": round(analysis.margin_consistency, 3),
                            "margin_volatility": round(analysis.margin_volatility, 4),
                            "avg_spread_pct": round(analysis.avg_spread_pct, 2),
                            "datapoints": analysis.datapoints,
                            "window_hours": round(analysis.window_hours, 1),
                        }
                    }, indent=2))
                else:
                    print(f"\n  Historical ({analysis.datapoints} windows, {analysis.window_hours:.0f}h):")
                    print(f"  Confidence: {analysis.confidence:.2f} (reliability: {analysis.reliability:.2f}, profitability: {analysis.profitability_score:.2f})")
                    print(f"  Avg margin: {analysis.avg_margin:,.0f} gp")
                    print(f"  Margin consistency: {analysis.margin_consistency:.0%}")
                    print(f"  Margin volatility: {analysis.margin_volatility:.4f}")
                    if getattr(args, "predict", False):
                        try:
                            from statistics import linear_regression
                            ts_pts = [(dp["timestamp"], dp["avgHighPrice"]) for dp in ts if dp.get("timestamp") and dp.get("avgHighPrice")]
                            if len(ts_pts) >= 6:
                                xs = [t - ts_pts[0][0] for t, _ in ts_pts]
                                ys = [float(p) for _, p in ts_pts]
                                slope, intercept = linear_regression(xs, ys)
                                mean = sum(ys) / len(ys)
                                pct_per_hr = (slope * 3600 / mean * 100) if mean > 0 else 0
                                ss_res = sum((y - (slope * x + intercept))**2 for x, y in zip(xs, ys))
                                ss_tot = sum((y - mean)**2 for y in ys)
                                r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                                direction = "up" if pct_per_hr > 0.05 else "down" if pct_per_hr < -0.05 else "flat"
                                arrow = "↗" if direction == "up" else "↘" if direction == "down" else "→"
                                conf = min(100, max(0, r2 * 100))
                                print(f"\n  Prediction: {arrow} likely {direction} ({pct_per_hr:+.2f}%/hr, R²={r2:.3f})")
                            else:
                                print("\n  Prediction: insufficient data (need ≥6 datapoints)")
                        except ImportError:
                            print("\n  Prediction: requires Python 3.10+ (statistics.linear_regression)")
                        except Exception:
                            print("\n  Prediction: could not compute")
            else:
                if not args.json:
                    print("\n  Not enough timeseries data for analysis.")
        elif not args.json:
            print("\n  No timeseries data available.")




def watch_add(args: argparse.Namespace) -> None:
    """Add an item to the watchlist by name or ID."""
    from rshelper.api import fetch_mapping
    print("Looking up item...", file=sys.stderr)
    mapping = fetch_mapping(args.profile if hasattr(args, "profile") else None)
    if not mapping:
        print("Error: could not fetch item mapping.", file=sys.stderr)
        sys.exit(1)

    query = str(args.item).lower()
    matched = None
    for entry in mapping:
        if str(entry.get("id")) == query:
            matched = entry
            break
    if matched is None:
        candidates = [e for e in mapping if query in (e.get("name") or "").lower()]
        if len(candidates) == 1:
            matched = candidates[0]
        elif len(candidates) > 1:
            print(f"Multiple matches for '{args.item}':", file=sys.stderr)
            for e in candidates[:10]:
                print(f"  {e['id']:>6}  {e['name']}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"No item found matching '{args.item}'", file=sys.stderr)
            sys.exit(1)

    item_id = matched["id"]
    name = matched["name"]
    watchlist.add(item_id, name,
                  alert_margin_above=args.alert_above,
                  alert_margin_below=args.alert_below,
                  profile=args.profile)
    print(f"Added '{name}' (id={item_id}) to watchlist.")


def watch_remove(args: argparse.Namespace) -> None:
    """Remove an item from the watchlist by ID."""
    ok = watchlist.remove(args.item_id, profile=args.profile if hasattr(args, "profile") else None)
    if ok:
        print(f"Removed item {args.item_id} from watchlist.")
    else:
        print(f"Item {args.item_id} was not on the watchlist.", file=sys.stderr)
        sys.exit(1)


def watch_list(args: argparse.Namespace) -> None:
    """List all watched items."""
    items = watchlist.list_all(profile=args.profile if hasattr(args, "profile") else None)
    if not items:
        print("Watchlist is empty.")
        return
    data = watchlist.load(profile=args.profile if hasattr(args, "profile") else None)
    print(f"{'ID':>6}  {'Name':<30}  {'Alert Above':>12}  {'Alert Below':>12}  Added")
    print("-" * 85)
    for item_id_str, entry in data["items"].items():
        above = entry.get("alert_margin_above") or "-"
        below = entry.get("alert_margin_below") or "-"
        added = entry.get("added", "")[:10]
        print(f"{item_id_str:>6}  {entry['name']:<30}  {str(above):>12}  {str(below):>12}  {added}")


def watch_check(args: argparse.Namespace) -> None:
    """Check all watched items against current prices."""
    from rshelper.api import fetch_latest
    from rshelper.scanner import FlipScanner
    import json as _json

    watched_ids = watchlist.get_watched_ids(profile=args.profile if hasattr(args, "profile") else None)
    if not watched_ids:
        print("Watchlist is empty.")
        return

    print("Fetching latest prices...", file=sys.stderr)
    latest = fetch_latest(args.profile if hasattr(args, "profile") else None)
    if not latest:
        print("Error: could not fetch prices.", file=sys.stderr)
        sys.exit(1)

    wl = watchlist.load(profile=args.profile)
    direction = getattr(args, "flip_direction", "arbitrage")
    alerts = []

    for item_id_str, entry in wl["items"].items():
        price = latest.get(item_id_str)
        if not price or not isinstance(price, dict):
            continue
        issue = price_issue(price)
        if issue:
            print(f"  Skipped {entry['name']}: price data {issue} "
                  f"(stale or manipulated)", file=sys.stderr)
            continue
        buy = int(price.get("high", 0) or 0)
        sell = int(price.get("low", 0) or 0)
        if buy <= 0 or sell <= 0:
            continue

        if direction == "traditional":
            margin = buy - sell
            tax = ge_tax(buy)
        else:
            margin = sell - buy
            tax = ge_tax(sell)
        profit = margin - tax

        above = entry.get("alert_margin_above")
        below = entry.get("alert_margin_below")

        triggered = False
        if above is not None and profit > above:
            alerts.append({"item_id": int(item_id_str), "name": entry["name"],
                          "reason": "above", "threshold": above, "current": profit})
            triggered = True
        if below is not None and profit < below:
            alerts.append({"item_id": int(item_id_str), "name": entry["name"],
                          "reason": "below", "threshold": below, "current": profit})
            triggered = True

        if args.verbose or triggered:
            flag = " *** ALERT ***" if triggered else ""
            print(f"  {entry['name']:<30} margin={profit:>8,} gp  " +
                  f"(above={above}, below={below}){flag}")

    if not alerts:
        print("No alerts triggered.")
        return

    if getattr(args, "json", False):
        print(json.dumps(alerts, indent=2))

    print(f"\n{len(alerts)} alert(s) triggered:")
    for a in alerts:
        print(f"  {a['name']}: margin {a['current']:,} gp {a['reason']} threshold {a['threshold']:,}")
    sys.exit(1)
def _save_alch_snapshot(results, profile: str | None = None):
    items = [{"item_id": r.id, "name": r.name, "buy_price": r.buy_price,
              "alch_value": r.alch_value, "profit": r.profit,
              "gp_per_hour": r.gp_per_hour, "volume": r.volume,
              "buy_limit": r.buy_limit}
             for r in results]
    path = snapshot.save("alch", items, profile)
    tuning.record_if_changed(profile)
    print(f"\nSnapshot saved: {path}", file=sys.stderr)


def _save_flip_snapshot(results, profile: str | None = None):
    items = [{"item_id": r.id, "name": r.name, "buy_price": r.buy_price,
              "sell_price": r.sell_price, "profit": r.profit,
              "gp_per_hour": r.gp_per_hour, "volume": r.volume,
              "buy_limit": r.buy_limit}
             for r in results]
    path = snapshot.save("flip", items, profile)
    tuning.record_if_changed(profile)
    print(f"\nSnapshot saved: {path}", file=sys.stderr)


def _save_margin_snapshot(results, lookup, profile: str | None = None):
    items = []
    for a in results:
        item = lookup.get(a.item_id)
        items.append({
            "item_id": a.item_id,
            "name": item.name if item else str(a.item_id),
            "buy_price": item.buy_price if item else 0,
            "sell_price": item.sell_price if item else 0,
            "confidence": round(a.confidence, 4),
            "profitability_score": round(a.profitability_score, 4),
            "avg_margin": round(a.avg_margin, 0),
            "margin_volatility": round(a.margin_volatility, 4),
        })
    path = snapshot.save("margin", items, profile)
    tuning.record_if_changed(profile)
    print(f"\nSnapshot saved: {path}", file=sys.stderr)


def diff_cmd(args: argparse.Namespace) -> None:
    """Compare today's scan with a previous one."""
    scan_type = args.scan_type or "flip"
    day = args.date

    today_str = date.today().isoformat()
    today_path = snapshot._snapshot_dir(args.profile if hasattr(args, 'profile') else None) / f"{scan_type}-{today_str}.json"
    if not today_path.exists():
        print(f"No snapshot for today ({today_str}). Run a scan with --save-snapshot first.",
              file=sys.stderr)
        sys.exit(1)

    result = snapshot.diff_scan_type(scan_type, day, args.profile if hasattr(args, 'profile') else None)
    if result is None:
        prev = snapshot.load(scan_type, day, args.profile if hasattr(args, 'profile') else None)
        if prev is None:
            print(f"No previous {scan_type} snapshot found.", file=sys.stderr)
        else:
            print(f"Could not compute diff.", file=sys.stderr)
        sys.exit(1)

    print(f"Diff: {scan_type} scan — {result['prev_date']} → {result['today_date']}")
    print(f"  {result['today_count']} items today, {result['prev_count']} previously")
    print()

    if result["new"]:
        print(f"  New ({len(result['new'])}):")
        for item in result["new"][:10]:
            name = item.get("name", item.get("item_id"))
            profit = item.get("profit", item.get("avg_margin", 0))
            print(f"    {name:<35} profit={profit:>10,}")
        if len(result["new"]) > 10:
            print(f"    ... and {len(result['new']) - 10} more")

    if result["improved"]:
        print(f"\n  Improved ({len(result['improved'])}):")
        for item in result["improved"][:10]:
            name = item.get("name", item.get("item_id"))
            profit = item.get("profit", item.get("avg_margin", 0))
            delta = item["delta"]
            gph = item.get("gp_per_hour")
            gph_str = f"  gp/hr={gph:>10,}" if gph is not None else ""
            print(f"    {name:<35} {profit:>10,}  (+{delta:>+10,}){gph_str}")
        if len(result["improved"]) > 10:
            print(f"    ... and {len(result['improved']) - 10} more")

    if result["fell_off"]:
        print(f"\n  Fell off ({len(result['fell_off'])}):")
        for item in result["fell_off"][:10]:
            name = item.get("name", item.get("item_id"))
            profit = item.get("profit", item.get("avg_margin", 0))
            delta = item["delta"]
            gph = item.get("gp_per_hour")
            gph_str = f"  gp/hr={gph:>10,}" if gph is not None else ""
            print(f"    {name:<35} {profit:>10,}  ({delta:>+10,}){gph_str}")
        if len(result["fell_off"]) > 10:
            print(f"    ... and {len(result['fell_off']) - 10} more")

    if result["removed"]:
        print(f"\n  No longer in top results ({len(result['removed'])}):")
        for item in result["removed"][:10]:
            name = item.get("name", item.get("item_id"))
            print(f"    {name}")
        if len(result["removed"]) > 10:
            print(f"    ... and {len(result['removed']) - 10} more")

    print(f"\n  {result['unchanged']} unchanged")


def snapshot_list(args: argparse.Namespace) -> None:
    """List saved snapshots."""
    paths = snapshot.list_snapshots(args.scan_type, args.profile if hasattr(args, 'profile') else None)
    if not paths:
        print("No snapshots found.")
        return
    for p in paths[:20]:
        try:
            data = json.loads(p.read_text())
            print(f"  {p.stem:<40} {data.get('date',''):<12} {data.get('count','?')} items")
        except Exception:
            print(f"  {p.stem}")


def config_show(args: argparse.Namespace) -> None:
    """Print the current config as JSON."""
    cfg = load_config()
    import dataclasses
    print(json.dumps(dataclasses.asdict(cfg), indent=2))


def config_path(args: argparse.Namespace) -> None:
    """Print the config file path."""
    p = resolve_config_path("config.toml", getattr(args, 'profile', None))
    print(p)

def signals_cmd(args: argparse.Namespace) -> None:
    """Fetch data, detect market signals, print results grouped by type."""
    monitor_interval = getattr(args, "monitor", 0) or 0

    def _scan_once():
        mapping, latest, volume_5m, items = _fetch_bootstrap(args.profile)
        direction = getattr(args, "flip_direction", "arbitrage")
        scanner = FlipScanner(direction=direction, ge_slots=2)
        flips = scanner.scan(
            items,
            members_only=args.members_only,
            min_volume=0,
            min_margin=0,
        )
        from rshelper.signals import detect_signals
        return detect_signals(flips, volume_5m, cooldown_sec=args.cooldown * 60)

    if monitor_interval:
        import time as _time
        seen: set[tuple] = set()
        print(f"[signals] live follow mode — re-scanning every {monitor_interval}s. "
              f"Ctrl-C to stop.", file=sys.stderr)
        try:
            while True:
                try:
                    signals = _scan_once()
                except SystemExit:
                    signals = []
                    print("[signals] data sources unavailable; retrying next cycle",
                          file=sys.stderr)
                for s in signals:
                    key = (s.type, s.item_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    print(f"[signal] {s.type} {s.severity} {s.name} "
                          f"{s.current_price:,} gp {s.message}")
                _time.sleep(max(1, monitor_interval))
        except KeyboardInterrupt:
            print("\n[signals] stopped.", file=sys.stderr)
            return

    signals = _scan_once()
    if not signals:
        print("\nNo active signals detected.")
        return

    if args.json:
        out = []
        for s in signals:
            out.append({
                "type": s.type,
                "item_id": s.item_id,
                "name": s.name,
                "severity": s.severity,
                "current_price": s.current_price,
                "deviation": s.deviation,
                "message": s.message,
            })
        print(json.dumps(out, indent=2))
        return

    # Group by type
    groups: dict[str, list[Signal]] = {}
    for s in signals:
        groups.setdefault(s.type, []).append(s)

    type_labels = {
        "CRASH": "CRASH — Severe price drops",
        "DUMP": "DUMP — Price dips below average",
        "SURGE": "SURGE — Unusual volume spikes",
        "FLIP": "FLIP — Wide spreads with liquidity",
    }

    print(f"\n  Signals ({len(signals)} active, cooldown: {args.cooldown} min)\n")
    for sig_type in ("CRASH", "DUMP", "SURGE", "FLIP"):
        group = groups.get(sig_type, [])
        if not group:
            continue
        label = type_labels.get(sig_type, sig_type)
        print(f"  {label}")
        print(f"  " + "-" * 70)
        if sig_type in ("CRASH", "DUMP"):
            print(f"  {'Sev':<7} {'Item':<28} {'Price':>10} {'Deviation':>10}  Suggested")
        elif sig_type == "SURGE":
            print(f"  {'Sev':<7} {'Item':<28} {'Price':>10} {'Vol Ratio':>10}")
        else:  # FLIP
            print(f"  {'Sev':<7} {'Item':<28} {'Price':>10} {'Spread':>8}  RS Score")
        for s in group:
            item = next((i for i in flips if i.id == s.item_id), None)
            rs = f"{item.rs_score:.0f}" if item else "—"
            if sig_type in ("CRASH", "DUMP"):
                suggestion = f"Buy at {s.current_price:,}"
                print(f"  {s.severity:<7} {s.name:<28} {s.current_price:>10,} {s.deviation:>+8.1f}%  {suggestion}")
            elif sig_type == "SURGE":
                print(f"  {s.severity:<7} {s.name:<28} {s.current_price:>10,} {s.deviation:>8.1f}x")
            else:
                print(f"  {s.severity:<7} {s.name:<28} {s.current_price:>10,} {s.deviation:>7.1f}%  RS={rs}")
        print()

def main() -> None:
    cfg = load_config()

    parser = argparse.ArgumentParser(
        prog="rshelper",
        description="RSHelper — OSRS Grand Exchange profit scanner",
    )
    parser.add_argument("--profile", type=str, default=None, help="Profile to use for this command")
    parser.add_argument("--quiet", action="store_true", help="Suppress status output (cron-friendly)")
    parser.add_argument("--version", action="version", version=f"rshelper {__version__}")
    sub = parser.add_subparsers(dest="command")

    alch = sub.add_parser("alch-scan", help="Scan for profitable high alchemy items")
    alch.add_argument("--nature-rune-cost", type=int, default=cfg.alch.nature_rune_cost,
                       help="GP cost of nature runes (default: auto-fetch from API)")
    alch.add_argument("--members-only", action=argparse.BooleanOptionalAction,
                       default=cfg.alch.members_only,
                       help="Filter to members items only")
    alch.add_argument("--min-volume", type=int, default=cfg.alch.min_volume,
                       help="Minimum 5-minute trade volume")
    alch.add_argument("--top", type=int, default=cfg.alch.top,
                       help="Number of results to show")
    alch.add_argument("--name", type=str, default="",
                       help="Filter by item name (substring match)")
    alch.add_argument("--json", action="store_true",
                       help="Output JSON instead of table")
    alch.add_argument("--csv", action="store_true",
                       help="Output CSV instead of table")
    alch.add_argument("--html", action="store_true",
                       help="Output self-contained sortable HTML")
    alch.add_argument("--save-snapshot", action="store_true",
                       help="Save results for later diff/trend comparison")

    flip = sub.add_parser("flip-scan", help="Scan for profitable GE flip margins")
    flip.add_argument("--members-only", action=argparse.BooleanOptionalAction,
                       default=cfg.flip.members_only,
                       help="Filter to members items only")
    flip.add_argument("--min-volume", type=int, default=cfg.flip.min_volume,
                       help="Minimum 5-minute trade volume")
    flip.add_argument("--min-margin", type=int, default=cfg.flip.min_margin,
                       help="Minimum flip margin per item")
    flip.add_argument("--top", type=int, default=cfg.flip.top,
                       help="Number of results to show")
    flip.add_argument("--capital", type=int, default=0,
                       help="Available GP for trade sizing (shows buy qty)")
    flip.add_argument("--flip-direction", type=str, default=cfg.flip.direction,
                       choices=["arbitrage", "traditional"],
                       help="Flip mode: arbitrage (low>high windows) or traditional (high-low-tax)")
    flip.add_argument("--name", type=str, default="",
                       help="Filter by item name (substring match)")
    flip.add_argument("--json", action="store_true",
                       help="Output JSON instead of table")
    flip.add_argument("--csv", action="store_true",
                       help="Output CSV instead of table")
    flip.add_argument("--html", action="store_true",
                       help="Output self-contained sortable HTML")
    flip.add_argument("--save-snapshot", action="store_true",
                       help="Save results for later diff/trend comparison")
    flip.add_argument("--ge-slots", type=int, default=2,
                       help="Number of GE slots to model for GP/hr (default: 2 for buy+sell)")

    process = sub.add_parser("process-scan", help="Scan profitable materials-processing recipes")
    process.add_argument("--members-only", action=argparse.BooleanOptionalAction,
                         default=cfg.process.members_only,
                         help="Filter to members-only recipes")
    process.add_argument("--skill", type=str, default="",
                         choices=["smithing", "fletching", "crafting", "cooking",
                                  "herblore", "construction", "runecrafting", "magic"],
                         help="Filter to one skill (default: all)")
    process.add_argument("--min-volume", type=int, default=cfg.process.min_volume,
                         help="Minimum 5-minute output volume")
    process.add_argument("--min-profit", type=int, default=cfg.process.min_profit,
                         help="Minimum profit per output unit")
    process.add_argument("--top", type=int, default=cfg.process.top,
                         help="Number of results to show")
    process.add_argument("--capital", type=int, default=cfg.process.capital,
                         help="Available GP; caps per-recipe throughput by budget")
    process.add_argument("--name", type=str, default="",
                         help="Filter by output name (substring match)")
    process.add_argument("--json", action="store_true",
                         help="Output JSON instead of table")
    process.add_argument("--csv", action="store_true",
                         help="Output CSV instead of table")
    process.add_argument("--html", action="store_true",
                         help="Output self-contained sortable HTML")
    process.add_argument("--save-snapshot", action="store_true",
                         help="Save results for later diff/trend comparison")

    info = sub.add_parser("item-info", help="Look up a single item by name or ID")
    info.add_argument("item", help="Item name or ID")
    info.add_argument("--timeseries", action="store_true",
                       help="Fetch and analyze timeseries history")
    info.add_argument("--json", action="store_true", help="Output JSON instead of text")
    info.add_argument("--tax-curve", action="store_true",
                       help="Show profit curve at different sell prices")
    info.add_argument("--wiki", action="store_true",
                       help="Print OSRS Wiki Exchange URL for this item")
    info.add_argument("--wiki-open", action="store_true",
                       help="Open OSRS Wiki Exchange page in browser")
    info.add_argument("--predict", action="store_true",
                       help="Predict short-term price direction from timeseries")


    # Monitor subcommand
    mon = sub.add_parser("monitor", help="Background monitor with desktop notifications")
    mon.add_argument("--interval", type=int, default=120,
                      help="Polling interval in seconds (default: 120)")
    mon.add_argument("--no-notify", action="store_true",
                      help="Suppress desktop notifications")
    mon.add_argument("--stop", action="store_true",
                      help="Stop a running monitor")
    mon.add_argument("--status", action="store_true", help="Show monitor status")

    # Auto-trader subcommand
    trader_p = sub.add_parser(
        "auto-trade", help="Autonomous paper trader (paper-only, no real GP)")
    trader_p.add_argument("--once", action="store_true",
                          help="Run a single cycle and exit")
    trader_p.add_argument("--interval", type=int, default=0,
                          help="Override poll interval (seconds)")
    trader_p.add_argument("--stop", action="store_true",
                          help="Stop a running trader")
    trader_p.add_argument("--status", action="store_true",
                          help="Show trader status")
    trader_p.add_argument("--json", action="store_true",
                          help="JSON status output")

    # Trade subcommand
    trade_p = sub.add_parser("trade", help="Trade journal and P&L tracking")
    trade_sub = trade_p.add_subparsers(dest="trade_action")
    trade_log = trade_sub.add_parser("log", help="Log a completed trade")
    trade_log.add_argument("item", help="Item name")
    trade_log.add_argument("qty", type=int, help="Quantity traded")
    trade_log.add_argument("buy_price", type=int, help="Buy price per unit (gp)")
    trade_log.add_argument("sell_price", type=int, help="Sell price per unit (gp)")
    trade_log.add_argument("--note", type=str, default="", help="Optional note")
    trade_paper = trade_sub.add_parser(
        "paper", help="Log a paper trade at live GE prices")
    trade_paper.add_argument("item", help="Item name")
    trade_paper.add_argument("qty", type=int, nargs="?", default=0,
                             help="Quantity (default: sized from --capital or 1)")
    trade_paper.add_argument("--capital", type=int, default=0,
                             help="GP to spend; sizes quantity within buy limit")
    trade_paper.add_argument("--flip-direction", type=str, default="arbitrage",
                             choices=["arbitrage", "traditional"],
                             help="arbitrage: instant buy/sell (default); "
                                  "traditional: buy at bid, sell at offer")
    trade_paper.add_argument("--note", type=str, default="",
                             help="Optional note")
    trade_open = trade_sub.add_parser(
        "open", help="Open a paper position (buy and hold at live price)")
    trade_open.add_argument("item", help="Item name")
    trade_open.add_argument("qty", type=int, nargs="?", default=0,
                            help="Quantity (default: sized from --capital or 1)")
    trade_open.add_argument("--capital", type=int, default=0,
                            help="GP to spend; sizes quantity within buy limit")
    trade_open.add_argument("--flip-direction", type=str, default="arbitrage",
                            choices=["arbitrage", "traditional"],
                            help="arbitrage: buy at instant-buy (default); "
                                 "traditional: buy at bid")
    trade_open.add_argument("--note", type=str, default="", help="Optional note")
    trade_close = trade_sub.add_parser(
        "close", help="Close open paper positions at live price (FIFO)")
    trade_close.add_argument("item", help="Item name")
    trade_close.add_argument("qty", type=int, nargs="?", default=0,
                             help="Units to close (default: all open)")
    trade_pos = trade_sub.add_parser(
        "positions", help="List open paper positions with unrealized P&L")
    trade_pos.add_argument("--json", action="store_true")
    trade_list = trade_sub.add_parser("list", help="List logged trades")
    trade_list.add_argument("--item", type=str, default="", help="Filter by item name")
    trade_list.add_argument("--since", type=str, default="", help="Filter from date (YYYY-MM-DD)")
    trade_list.add_argument("--top", type=int, default=0, help="Show top N most recent")
    trade_list.add_argument("--strategy", type=str, default="",
                            choices=["", "auto", "manual"],
                            help="Filter by strategy (auto=trader, manual=hand)")
    trade_list.add_argument("--json", action="store_true")
    trade_list.add_argument("--csv", action="store_true")
    trade_pnl = trade_sub.add_parser("pnl", help="Show P&L summary")
    trade_pnl.add_argument("--since", type=str, default="", help="Filter from date")
    trade_pnl.add_argument("--by-item", action="store_true",
                           help="Show per-item P&L breakdown instead of summary")
    trade_pnl.add_argument("--strategy", type=str, default="",
                           choices=["", "auto", "manual"],
                           help="Filter by strategy (auto=trader, manual=hand)")
    trade_pnl.add_argument("--json", action="store_true")
    trade_del = trade_sub.add_parser("delete", help="Delete a trade by ID")
    trade_del.add_argument("id", type=int, help="Trade ID to delete")
    trade_status_p = trade_sub.add_parser(
        "status", help="Positions + unrealized + realized P&L + trader in one view")
    trade_status_p.add_argument("--json", action="store_true")


    # Signals subcommand
    sig = sub.add_parser("signals", help="Detect market signals: dumps, crashes, surges, flips")
    sig.add_argument("--members-only", action=argparse.BooleanOptionalAction,
                      default=False,
                      help="Filter to members items only")
    sig.add_argument("--flip-direction", type=str, default="arbitrage",
                      choices=["arbitrage", "traditional"],
                      help="Flip mode for margin-based signals")
    sig.add_argument("--cooldown", type=int, default=15,
                      help="Signal cooldown in minutes (default: 15)")
    sig.add_argument("--json", action="store_true",
                      help="Output JSON instead of table")
    sig.add_argument("--monitor", type=int, nargs="?", const=30, default=0,
                     help="Live follow mode: re-scan every N seconds (default 30) "
                          "and print new signals as they appear")

    # Watchlist subcommand
    watch = sub.add_parser("watch", help="Manage item watchlist and check alerts")
    watch_sub = watch.add_subparsers(dest="watch_action")
    watch_add_p = watch_sub.add_parser("add", help="Add item to watchlist")
    watch_add_p.add_argument("item", help="Item name or ID")
    watch_add_p.add_argument("--alert-above", type=int, default=None,
                             help="Alert when margin exceeds this (gp)")
    watch_add_p.add_argument("--alert-below", type=int, default=None,
                             help="Alert when margin falls below this (gp)")
    watch_rm = watch_sub.add_parser("remove", help="Remove item from watchlist")
    watch_rm.add_argument("item_id", type=int, help="Item ID to remove")
    watch_sub.add_parser("list", help="List all watched items")
    watch_chk = watch_sub.add_parser("check", help="Check watchlist for triggered alerts")
    watch_chk.add_argument("--flip-direction", type=str, default="arbitrage",
                           choices=["arbitrage", "traditional"],
                           help="Flip mode for margin calculation")
    watch_chk.add_argument("--ge-slots", type=int, default=2,
                           help="GE slots (unused in check, accepted for consistency)")
    watch_chk.add_argument("-v", "--verbose", action="store_true",
                           help="Show all watched items, not just alerts")
    watch_chk.add_argument("--json", action="store_true",
                           help="Output alerts as JSON (exit 1 still fires on triggers)")

    # Diff subcommand
    diff_p = sub.add_parser("diff", help="Compare today's scan with a previous one")
    diff_p.add_argument("scan_type", nargs="?", default="flip",
                        choices=["alch", "flip", "margin", "process"],
                        help="Scan type to compare (default: flip)")
    diff_p.add_argument("--date", type=str, default=None,
                        help="Previous date to compare against (YYYY-MM-DD, default: most recent)")

    # Snapshots subcommand
    # Profile subcommand
    profile_p = sub.add_parser("profile", help="Manage multi-account profiles")
    profile_sub = profile_p.add_subparsers(dest="profile_action")
    profile_create = profile_sub.add_parser("create", help="Create a new profile")
    profile_create.add_argument("name", help="Profile name (alphanumeric, dashes, underscores, max 32 chars)")
    profile_switch = profile_sub.add_parser("switch", help="Switch active profile")
    profile_switch.add_argument("name", help="Profile name")
    profile_sub.add_parser("list", help="List all profiles")
    profile_del = profile_sub.add_parser("delete", help="Delete a profile")
    profile_del.add_argument("name", help="Profile name")
    profile_del.add_argument("--force", action="store_true", help="Delete even if profile has data")

    snap_p = sub.add_parser("snapshots", help="List saved scan snapshots")
    snap_p.add_argument("scan_type", nargs="?", default=None,
                        choices=["alch", "flip", "margin", "process"],
                        help="Filter by scan type (default: all)")

    # Config subcommand
    config_parser = sub.add_parser("config", help="View or show config file path")
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_sub.add_parser("show", help="Print current config as JSON")
    config_sub.add_parser("path", help="Print config file path")

    dash = sub.add_parser("dashboard", help="Launch local web dashboard")
    dash.add_argument("--port", type=int, default=5555)
    dash.add_argument("--bind", type=str, default="127.0.0.1")
    dash.add_argument("--open", action="store_true",
                      help="Open the dashboard in your browser")
    dash.add_argument("--control", action="store_true",
                      help="Enable daemon control endpoints (start/stop auto-trade "
                           "and monitor). Only use on trusted local sessions.")
    dash.add_argument("--profile", type=str, default=None,
                      help="Profile to serve (default: active profile)")

    hist = sub.add_parser("history", help="Progression: daily buckets, eras, per-item P&L")
    hist.add_argument("--all", action="store_true",
                      help="Include non-paper trades (default: paper only)")
    hist.add_argument("--strategy", type=str, default="",
                      choices=["", "auto", "manual"],
                      help="Filter by strategy (auto=trader, manual=hand)")
    hist.add_argument("--json", action="store_true", help="Output JSON instead of table")

    margin = sub.add_parser("margin-check", help="Analyze timeseries history for flip confidence scoring")
    margin.add_argument("--members-only", action=argparse.BooleanOptionalAction,
                       default=cfg.margin.members_only,
                       help="Filter to members items only")
    margin.add_argument("--min-volume", type=int, default=cfg.margin.min_volume,
                       help="Minimum 5-minute trade volume")
    margin.add_argument("--min-margin", type=int, default=cfg.margin.min_margin,
                       help="Minimum flip margin per item")
    margin.add_argument("--check", type=int, default=cfg.margin.check,
                       help="Number of top flip candidates to check")
    margin.add_argument("--top", type=int, default=cfg.margin.top,
                       help="Number of results to show")
    margin.add_argument("--capital", type=int, default=0,
                       help="Available GP for trade sizing")
    margin.add_argument("--flip-direction", type=str, default=cfg.margin.direction,
                        choices=["arbitrage", "traditional"],
                        help="Flip mode: arbitrage (low>high windows) or traditional (high-low-tax)")
    margin.add_argument("--name", type=str, default="",
                        help="Filter by item name (substring match)")
    margin.add_argument("--json", action="store_true",
                       help="Output JSON instead of table")
    margin.add_argument("--csv", action="store_true",
                       help="Output CSV instead of table")
    margin.add_argument("--ge-slots", type=int, default=2,
                         help="Number of GE slots to model for GP/hr (default: 2 for buy+sell)")
    margin.add_argument("--workers", type=int, default=4,
                         help="Concurrent timeseries fetchers (default: 4)")
    margin.add_argument("--risk", action="store_true",
                         help="Show worst-case margin and stability metrics")
    margin.add_argument("--save-snapshot", action="store_true",
                         help="Save results for later diff/trend comparison")

    args, unknown = parser.parse_known_args()
    if unknown:
        print(f"  Warning: ignored unknown arguments: {' '.join(unknown)}",
              file=sys.stderr)
    if args.quiet:
        import os
        sys.stderr = open(os.devnull, "w")
    if args.command == "item-info":
        item_info(args)
    elif args.command == "monitor":
        if args.stop:
            from rshelper.monitor import stop_monitor
            ok = stop_monitor(args.profile if hasattr(args, "profile") else None)
            print("Monitor stopped." if ok else "No monitor running.")
        elif args.status:
            from rshelper.monitor import monitor_status
            status = monitor_status()
            if status is None:
                print("No monitor running.")
            else:
                print(f"  Monitor: RUNNING")
                print(f"  PID: {status['pid']}")
                print(f"  Running since: ~{max(1, status['uptime_sec'] // 60)} min ago")
                print(f"  Last check: {status['last_check_iso'] or 'N/A'}")
        else:
            from rshelper.monitor import run_monitor
            run_monitor(interval_sec=args.interval, no_notify=args.no_notify, profile=args.profile)

    elif args.command == "auto-trade":
        auto_trade_cmd(args)

    elif args.command == "signals":
        signals_cmd(args)

    elif args.command == "history":
        history_cmd(args)

    elif args.command == "dashboard":
        from rshelper.dashboard.server import run
        run(bind=args.bind, port=args.port, control=args.control,
            open_browser=args.open, profile=args.profile)

    elif args.command == "margin-check":
        margin_check(args)
    elif args.command == "alch-scan":
        alch_scan(args)
    elif args.command == "flip-scan":
        flip_scan(args)
    elif args.command == "process-scan":
        process_scan(args)
    elif args.command == "watch":
        if args.watch_action == "add":
            watch_add(args)
        elif args.watch_action == "remove":
            watch_remove(args)
        elif args.watch_action == "list":
            watch_list(args)
        elif args.watch_action == "check":
            watch_check(args)
        else:
            parser.print_help()
            sys.exit(1)
    elif args.command == "trade":
        if args.trade_action == "log":
            from rshelper.journal import log_trade
            from rshelper.api import fetch_mapping
            profile = args.profile if hasattr(args, "profile") else None
            mapping = fetch_mapping(profile)
            item_id = 0
            if mapping:
                q = args.item.lower()
                for entry in mapping:
                    if (entry.get("name") or "").lower() == q:
                        item_id = entry["id"]
                        break
            trade = log_trade(item_id, args.item, args.qty, args.buy_price,
                              args.sell_price, args.note, profile=profile)
            if item_id == 0:
                print(f"Warning: '{args.item}' not found in item mapping; "
                      f"logged with item_id=0.", file=sys.stderr)
            print(f"Logged trade #{trade.id}: bought {trade.qty}x {trade.name} "
                  f"at {trade.buy_price:,} gp, sold at {trade.sell_price:,} gp "
                  f"— profit: {trade.profit:+,} gp (tax: {trade.tax_paid:,})")
        elif args.trade_action == "paper":
            _trade_paper(args)
        elif args.trade_action == "open":
            _trade_open(args)
        elif args.trade_action == "close":
            _trade_close(args)
        elif args.trade_action == "positions":
            _trade_positions(args)
        elif args.trade_action == "status":
            trade_status(args)
        elif args.trade_action == "list":
            from rshelper.journal import list_trades
            profile = args.profile if hasattr(args, "profile") else None
            trades = list_trades(item_name=args.item, since=args.since,
                                 top=args.top, profile=profile,
                                 strategy=args.strategy)
            if args.json:
                from dataclasses import asdict
                print(json.dumps([asdict(t) for t in trades], indent=2))
            elif args.csv:
                import csv, io
                out = io.StringIO()
                writer = csv.DictWriter(out, fieldnames=["id","item_id","name","qty","buy_price","sell_price","tax_paid","profit","timestamp","note","strategy","exit_reason","hold_minutes","quote_sell"])
                writer.writeheader()
                for t in trades:
                    writer.writerow({"id":t.id,"item_id":t.item_id,"name":t.name,"qty":t.qty,"buy_price":t.buy_price,"sell_price":t.sell_price,"tax_paid":t.tax_paid,"profit":t.profit,"timestamp":t.timestamp,"note":t.note,"strategy":t.strategy,"exit_reason":t.exit_reason,"hold_minutes":t.hold_minutes,"quote_sell":t.quote_sell})
                print(out.getvalue())
            else:
                if not trades:
                    print("No trades logged.")
                else:
                    nw = max(len(t.name) for t in trades)
                    nw = min(nw, 30)
                    print(f"{'ID':<5} {'Date':<12} {'Item':<{nw}} {'Qty':>6} {'Buy':>10} {'Sell':>10} {'Profit':>10}")
                    print("-" * (55 + nw))
                    for t in trades:
                        print(f"{t.id:<5} {t.timestamp[:10]:<12} {t.name[:nw]:<{nw}} {t.qty:>6,} {t.buy_price:>10,} {t.sell_price:>10,} {t.profit:>+10,}")
        elif args.trade_action == "pnl":
            from rshelper.journal import compute_pnl
            profile = args.profile if hasattr(args, "profile") else None
            if args.by_item:
                from rshelper.journal import compute_pnl_by_item
                rows = compute_pnl_by_item(since=args.since, profile=profile,
                                           strategy=args.strategy)
                if args.json:
                    print(json.dumps([
                        {"name": r.name, "item_id": r.item_id,
                         "trade_count": r.trade_count, "qty": r.qty,
                         "cost_basis": r.cost_basis, "profit": r.profit,
                         "roi_pct": round(r.roi_pct, 2),
                         "win_rate": round(r.win_rate, 1)}
                        for r in rows
                    ], indent=2))
                else:
                    if not rows:
                        print("No trades logged.")
                    else:
                        print(f"\n  P&L by item{' (since ' + args.since + ')' if args.since else ''}")
                        print("  " + "=" * 72)
                        print(f"  {'Item':<28} {'Trades':>6} {'Qty':>9} "
                              f"{'Cost':>11} {'Profit':>11} {'ROI':>7} {'Win%':>6}")
                        print("  " + "-" * 72)
                        for r in rows:
                            print(f"  {r.name[:28]:<28} {r.trade_count:>6} {r.qty:>9,} "
                                  f"{r.cost_basis:>11,} {r.profit:>+11,} "
                                  f"{r.roi_pct:>6.1f}% {r.win_rate:>5.1f}%")
                        print()
            else:
                pnl = compute_pnl(since=args.since, profile=profile,
                                  strategy=args.strategy)
                if args.json:
                    d = {"total_profit": pnl.total_profit, "total_tax_paid": pnl.total_tax_paid,
                         "total_cost_basis": pnl.total_cost_basis,
                         "roi_pct": round(pnl.roi_pct, 2),
                         "trade_count": pnl.trade_count, "winning_trades": pnl.winning_trades,
                         "losing_trades": pnl.losing_trades, "win_rate": round(pnl.win_rate, 1),
                         "active_gp_per_hour": pnl.active_gp_per_hour, "items_traded": pnl.items_traded,
                         "profit_factor": round(pnl.profit_factor, 2) if pnl.profit_factor != float("inf") else None,
                         "max_drawdown": pnl.max_drawdown}
                    if pnl.best_trade:
                        d["best_trade"] = pnl.best_trade.profit
                    if pnl.worst_trade:
                        d["worst_trade"] = pnl.worst_trade.profit
                    print(json.dumps(d, indent=2))
                else:
                    print(f"\n  P&L Summary{' (since ' + args.since + ')' if args.since else ' (all time)'}")
                    print(f"  " + "=" * 45)
                    print(f"  Total profit:     {pnl.total_profit:>+15,} gp")
                    print(f"  Cost basis:       {pnl.total_cost_basis:>15,} gp")
                    print(f"  ROI:              {pnl.roi_pct:>14.2f}%")
                    print(f"  Total tax paid:    {pnl.total_tax_paid:>15,} gp")
                    print(f"  Trades:            {pnl.trade_count:>15}")
                    print(f"  Win rate:          {pnl.win_rate:>14.1f}%")
                    if pnl.best_trade:
                        print(f"  Best trade:        {pnl.best_trade.name:<20} ({pnl.best_trade.profit:>+12,} gp)")
                    if pnl.worst_trade:
                        print(f"  Worst trade:       {pnl.worst_trade.name:<20} ({pnl.worst_trade.profit:>+12,} gp)")
                    print(f"  Items traded:      {pnl.items_traded:>15}")
                    print(f"  Active gp/hr:      {pnl.active_gp_per_hour:>15,}")
                    print(f"  Profit factor:     {pnl.profit_factor if pnl.profit_factor == float('inf') else round(pnl.profit_factor, 2):>15}")
                    print(f"  Max drawdown:      {pnl.max_drawdown:>15,} gp")
                    print()
        elif args.trade_action == "delete":
            from rshelper.journal import delete_trade
            profile = args.profile if hasattr(args, "profile") else None
            ok = delete_trade(args.id, profile=profile)
            print(f"Trade {args.id} deleted." if ok else f"Trade {args.id} not found.")
    elif args.command == "profile":
        from rshelper.profile import (get_active_profile, set_active_profile,
                                       create_profile, delete_profile, list_profiles,
                                       validate_profile_name)
        if args.profile_action == "create":
            if not validate_profile_name(args.name):
                print(f"Invalid profile name: {args.name}", file=sys.stderr)
                sys.exit(1)
            ok = create_profile(args.name)
            print(f"Profile '{args.name}' created." if ok else f"Profile '{args.name}' already exists.")
        elif args.profile_action == "switch":
            if args.name == "default":
                set_active_profile("default")
                print("Switched to default profile.")
            elif not validate_profile_name(args.name):
                print(f"Invalid profile name: {args.name}", file=sys.stderr)
                sys.exit(1)
            else:
                set_active_profile(args.name)
                print(f"Switched to profile '{args.name}'.")
        elif args.profile_action == "list":
            profiles = list_profiles()
            active = get_active_profile()
            for p in profiles:
                marker = " *" if p == active else ""
                print(f"  {p}{marker}")
        elif args.profile_action == "delete":
            ok = delete_profile(args.name, force=args.force)
            if ok:
                print(f"Profile '{args.name}' deleted.")
            else:
                # Check if it exists to give better error
                profiles = list_profiles()
                if args.name in profiles:
                    print(f"Profile '{args.name}' has data. Use --force to delete.", file=sys.stderr)
                else:
                    print(f"Profile '{args.name}' not found.", file=sys.stderr)
                sys.exit(1)
    elif args.command == "diff":
        diff_cmd(args)
    elif args.command == "snapshots":
        snapshot_list(args)
    elif args.command == "config":
        if args.config_action == "show":
            config_show(args)
        elif args.config_action == "path":
            config_path(args)
        else:
            parser.print_help()
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
