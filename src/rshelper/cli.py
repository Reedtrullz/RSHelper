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
from rshelper.config import load_config
from rshelper import snapshot, watchlist


def _fetch_bootstrap():
    """Shared fetch-bootstrap: mapping, latest, 5m volume, and built items."""
    removed = cleanup_stale_cache()
    if removed:
        print(f"  Cleaned {removed} stale cache files", file=sys.stderr)

    print("Fetching OSRS Wiki prices...", file=sys.stderr)
    mapping = fetch_mapping()
    if not mapping:
        print("Error: could not fetch item mapping.", file=sys.stderr)
        sys.exit(1)
    latest = fetch_latest()
    if not latest:
        print("Error: could not fetch latest prices.", file=sys.stderr)
        sys.exit(1)
    volume_5m = fetch_5m() or {}

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
    header = f"{'Rank':<5} {'Item':<{name_width}} {'Buy':>10} {'Alch':>10} {'Profit':>8} {'GP/hr':>10} {'Limit':>7}"
    sep = "-" * len(header)
    lines = [header, sep]
    for i, item in enumerate(rows, 1):
        name = item.name[:name_width]
        lines.append(
            f"{i:<5} {name:<{name_width}} {item.buy_price:>10,} {item.alch_value:>10,} "
            f"{item.profit:>8,} {item.gp_per_hour:>10,} {item.buy_limit:>7,}"
        )
    return "\n".join(lines)


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
            f"{'Margin':>7} {'GP/hr':>9} {'Qty':>6} {'Limit':>6}"
        )
    else:
        header = (
            f"{'Rank':<4} {'Item':<{name_width}} {'Buy':>9} {'Sell':>9} "
            f"{'Margin':>7} {'GP/hr':>9} {'Limit':>7}"
        )
    sep = "-" * len(header)
    lines = [header, sep]
    for i, item in enumerate(rows, 1):
        name = item.name[:name_width]
        if has_qty:
            qty = trade_size(item, capital)
            lines.append(
                f"{i:<4} {name:<{name_width}} {item.buy_price:>9,} {item.sell_price:>9,} "
                f"{item.profit:>7,} {item.gp_per_hour:>9,} {qty:>6,} {item.buy_limit:>6,}"
            )
        else:
            lines.append(
                f"{i:<4} {name:<{name_width}} {item.buy_price:>9,} {item.sell_price:>9,} "
                f"{item.profit:>7,} {item.gp_per_hour:>9,} {item.buy_limit:>7,}"
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
    mapping, latest, volume_5m, items = _fetch_bootstrap()

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
        print(f"  {len(results)} after --name filter\n")
    else:
        print()

    if args.csv:
        fields = ["rank", "name", "buy_price", "alch_value", "profit", "gp_per_hour", "sell_price", "volume", "buy_limit"]
        fm = {f: (lambda r, f=f: getattr(r, f, "")) for f in fields if f != "rank"}
        print(_csv_output(results, args.top, fields, fm))
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
             "GP/hr": f"{r.gp_per_hour:,}", "Limit": f"{r.buy_limit:,}"}
            for i, r in enumerate(results[:args.top])
        ], ["Rank", "Item", "Buy", "Alch", "Profit", "GP/hr", "Limit"], "Alchemy Scan"))
    else:
        print(_format_table(results, args.top))

    if getattr(args, 'save_snapshot', False):
        _save_alch_snapshot(results[:args.top])


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
    mapping, latest, volume_5m, items = _fetch_bootstrap()

    direction = getattr(args, "flip_direction", "arbitrage")
    scanner = FlipScanner(direction=direction, ge_slots=args.ge_slots)
    results = scanner.scan(
        items,
        members_only=args.members_only,
        min_volume=args.min_volume,
        min_margin=args.min_margin,
    )
    print(f"  {len(results)} profitable flips ({direction} mode)")
    if args.name:
        results = _filter_by_name(results, args.name)
        print(f"  {len(results)} after --name filter\n")
    else:
        print()

    if args.csv:
        from dataclasses import asdict
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=[
            "rank", "name", "buy_price", "sell_price", "profit", "gp_per_hour",
            "volume", "buy_limit",
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
                "sell_price": r.sell_price,
                "margin": r.profit,
                "gp_per_hour": r.gp_per_hour,
                "volume": r.volume,
                "buy_limit": r.buy_limit,
            }
            for i, r in enumerate(results[:args.top])
        ], indent=2))
    elif args.html:
        capital = getattr(args, 'capital', 0)
        cols = ["Rank", "Item", "Buy", "Sell", "Margin", "GP/hr", "Limit"]
        rows = [{"Rank": i + 1, "Item": r.name, "Buy": f"{r.buy_price:,}",
                 "Sell": f"{r.sell_price:,}", "Margin": f"{r.profit:,}",
                 "GP/hr": f"{r.gp_per_hour:,}", "Limit": f"{r.buy_limit:,}"}
                for i, r in enumerate(results[:args.top])]
        if capital:
            cols.insert(-1, "Qty")
            for i, row in enumerate(rows):
                row["Qty"] = f"{trade_size(results[i], capital):,}"
        print(_html_output(rows, cols, "Flip Scan"))
    else:
        print(_format_flip_table(results, args.top, getattr(args, 'capital', 0)))

    if getattr(args, 'save_snapshot', False):
        _save_flip_snapshot(results[:args.top])


def _format_margin_table(results, top: int, lookup: dict, capital: int = 0,
                         risk_metrics: dict | None = None) -> str:
    """Render margin-check results as an aligned text table."""
    rows = results[:top]
    if not rows:
        return "No items with sufficient timeseries data."
    name_width = max((len(lookup[a.item_id].name) for a in rows if a.item_id in lookup), default=10)
    name_width = min(name_width, 24)
    name_width = max(name_width, 6)
    has_qty = capital > 0
    has_risk = risk_metrics is not None
    if has_risk and has_qty:
        header = (
            f"{'Rank':<4} {'Item':<{name_width}} {'Buy':>9} {'Sell':>9} "
            f"{'Conf':>5} {'Rel':>5} {'Prof':>5} {'AvgMar':>8} {'Qty':>6} "
            f"{'Worst':>8} {'Stab':>5} {'Hrs':>5}"
        )
    elif has_risk:
        header = (
            f"{'Rank':<4} {'Item':<{name_width}} {'Buy':>9} {'Sell':>9} "
            f"{'Conf':>5} {'Rel':>5} {'Prof':>5} {'AvgMar':>8} "
            f"{'Worst':>8} {'Stab':>5} {'Hrs':>5}"
        )
    elif has_qty:
        header = (
            f"{'Rank':<4} {'Item':<{name_width}} {'Buy':>9} {'Sell':>9} "
            f"{'Conf':>5} {'Rel':>5} {'Prof':>5} {'AvgMar':>8} {'Qty':>6} {'Hrs':>5}"
        )
    else:
        header = (
            f"{'Rank':<4} {'Item':<{name_width}} {'Buy':>9} {'Sell':>9} "
            f"{'Conf':>5} {'Rel':>5} {'Prof':>5} {'AvgMar':>8} {'Hrs':>5}"
        )
    sep = "-" * len(header)
    lines = [header, sep]
    for i, a in enumerate(rows, 1):
        item = lookup.get(a.item_id)
        name = item.name[:name_width] if item else str(a.item_id)
        buy = item.buy_price if item else 0
        sell = item.sell_price if item else 0
        risk = risk_metrics.get(a.item_id) if risk_metrics else None
        if has_risk and has_qty:
            qty = trade_size(item, capital) if item else 0
            worst = risk["worst"] if risk else 0
            stab = risk["stability"] if risk else 0
            lines.append(
                f"{i:<4} {name:<{name_width}} {buy:>9,} {sell:>9,} "
                f"{a.confidence:>5.2f} {a.reliability:>5.2f} {a.profitability_score:>5.2f} "
                f"{a.avg_margin:>8,.0f} {qty:>6,} {worst:>8,} {stab:>5.2f} {a.window_hours:>5.0f}"
            )
        elif has_risk:
            worst = risk["worst"] if risk else 0
            stab = risk["stability"] if risk else 0
            lines.append(
                f"{i:<4} {name:<{name_width}} {buy:>9,} {sell:>9,} "
                f"{a.confidence:>5.2f} {a.reliability:>5.2f} {a.profitability_score:>5.2f} "
                f"{a.avg_margin:>8,.0f} {worst:>8,} {stab:>5.2f} {a.window_hours:>5.0f}"
            )
        elif has_qty:
            qty = trade_size(item, capital) if item else 0
            lines.append(
                f"{i:<4} {name:<{name_width}} {buy:>9,} {sell:>9,} "
                f"{a.confidence:>5.2f} {a.reliability:>5.2f} {a.profitability_score:>5.2f} "
                f"{a.avg_margin:>8,.0f} {qty:>6,} {a.window_hours:>5.0f}"
            )
        else:
            lines.append(
                f"{i:<4} {name:<{name_width}} {buy:>9,} {sell:>9,} "
                f"{a.confidence:>5.2f} {a.reliability:>5.2f} {a.profitability_score:>5.2f} "
                f"{a.avg_margin:>8,.0f} {a.window_hours:>5.0f}"
            )
    return "\n".join(lines)


def margin_check(args: argparse.Namespace) -> None:
    """Fetch data, scan flips, then analyze timeseries history for confidence scoring."""
    mapping, latest, volume_5m, items = _fetch_bootstrap()

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
        print("\nNo flip candidates to check.")
        return

    # Build lookup: item_id -> Item (includes names for display)
    lookup = {item.id: item for item in items}

    print(f"\nFetching timeseries for top {len(candidates)} candidates...", file=sys.stderr)
    candidate_ids = [c.id for c in candidates]
    ts_data = fetch_timeseries_batch(
        candidate_ids,
        timestep="5m",
        on_progress=lambda cur, tot: print(f"  [{cur}/{tot}] fetching history...", end="\r"),
        workers=getattr(args, "workers", 4),
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
            "rank", "name", "item_id", "confidence", "reliability", "profitability_score",
            "avg_margin", "margin_consistency", "margin_volatility", "avg_spread_pct",
            "avg_volume", "spread_score", "volume_score", "volatility_score",
            "datapoints", "window_hours",
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
                        if direction == "traditional":
                            m = h - l - max(1, int(h * 0.02))
                        else:
                            m = l - h - max(1, int(l * 0.02))
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
        _save_margin_snapshot(results[:args.top], lookup)


def item_info(args: argparse.Namespace) -> None:
    """Look up a single item by name or ID."""
    removed = cleanup_stale_cache()
    if removed:
        print(f"  Cleaned {removed} stale cache files")

    if args.json:
        print("Fetching data...", file=sys.stderr)
    else:
        print("Fetching data...")
    mapping = fetch_mapping()
    if not mapping:
        print("Error: could not fetch item mapping.", file=sys.stderr)
        sys.exit(1)
    latest = fetch_latest()
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

    if args.json:
        out = {
            "id": item_id, "name": name, "members": members,
            "buy_limit": buy_limit, "alch_value": alch_value,
            "buy_price": buy_price, "sell_price": sell_price,
        }
        # Alch
        nature_cost = _fetch_nature_rune_cost(mapping, latest)
        alch_profit = alch_value - buy_price - nature_cost
        out["alch_profit"] = alch_profit
        # Flip
        # Margin: buy-high minus sell-low (consistent with spread display)
        flip_margin = buy_price - sell_price
        tax_flip = max(1, int(buy_price * 0.02))
        flip_profit = flip_margin - tax_flip
        out["flip_margin"] = flip_margin
        out["flip_tax"] = tax_flip
        out["flip_profit"] = flip_profit
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
        tax_flip = max(1, int(buy_price * 0.02))
        flip_profit = flip_margin - tax_flip
        flip_line = f"  Flip margin: {flip_margin:,} gp (tax: {tax_flip:,}, net: {flip_profit:,})"
        if flip_profit <= 0:
            flip_line += " (not profitable)"
        print(flip_line)

    # Timeseries if requested
    if args.timeseries:
        ts = fetch_timeseries(item_id, "5m")
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
            else:
                if not args.json:
                    print("\n  Not enough timeseries data for analysis.")
        elif not args.json:
            print("\n  No timeseries data available.")




def watch_add(args: argparse.Namespace) -> None:
    """Add an item to the watchlist by name or ID."""
    from rshelper.api import fetch_mapping
    print("Looking up item...", file=sys.stderr)
    mapping = fetch_mapping()
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
                  alert_margin_below=args.alert_below)
    print(f"Added '{name}' (id={item_id}) to watchlist.")


def watch_remove(args: argparse.Namespace) -> None:
    """Remove an item from the watchlist by ID."""
    ok = watchlist.remove(args.item_id)
    if ok:
        print(f"Removed item {args.item_id} from watchlist.")
    else:
        print(f"Item {args.item_id} was not on the watchlist.", file=sys.stderr)
        sys.exit(1)


def watch_list(args: argparse.Namespace) -> None:
    """List all watched items."""
    items = watchlist.list_all()
    if not items:
        print("Watchlist is empty.")
        return
    data = watchlist.load()
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

    watched_ids = watchlist.get_watched_ids()
    if not watched_ids:
        print("Watchlist is empty.")
        return

    print("Fetching latest prices...")
    latest = fetch_latest()
    if not latest:
        print("Error: could not fetch prices.", file=sys.stderr)
        sys.exit(1)

    wl = watchlist.load()
    direction = getattr(args, "flip_direction", "arbitrage")
    flip = FlipScanner(direction=direction, ge_slots=getattr(args, "ge_slots", 2))
    alerts = []

    for item_id_str, entry in wl["items"].items():
        price = latest.get(item_id_str)
        if not price or not isinstance(price, dict):
            continue
        buy = int(price.get("high", 0) or 0)
        sell = int(price.get("low", 0) or 0)
        if buy <= 0 or sell <= 0:
            continue

        if direction == "traditional":
            margin = buy - sell
            tax = max(1, int(buy * 0.02))
        else:
            margin = sell - buy
            tax = max(1, int(sell * 0.02))
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

    print(f"\n{len(alerts)} alert(s) triggered:")
    for a in alerts:
        print(f"  {a['name']}: margin {a['current']:,} gp {a['reason']} threshold {a['threshold']:,}")
    sys.exit(1)
def _save_alch_snapshot(results):
    items = [{"item_id": r.id, "name": r.name, "buy_price": r.buy_price,
              "alch_value": r.alch_value, "profit": r.profit,
              "gp_per_hour": r.gp_per_hour, "volume": r.volume,
              "buy_limit": r.buy_limit}
             for r in results]
    path = snapshot.save("alch", items)
    print(f"\nSnapshot saved: {path}", file=sys.stderr)


def _save_flip_snapshot(results):
    items = [{"item_id": r.id, "name": r.name, "buy_price": r.buy_price,
              "sell_price": r.sell_price, "profit": r.profit,
              "gp_per_hour": r.gp_per_hour, "volume": r.volume,
              "buy_limit": r.buy_limit}
             for r in results]
    path = snapshot.save("flip", items)
    print(f"\nSnapshot saved: {path}", file=sys.stderr)


def _save_margin_snapshot(results, lookup):
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
    path = snapshot.save("margin", items)
    print(f"\nSnapshot saved: {path}", file=sys.stderr)


def diff_cmd(args: argparse.Namespace) -> None:
    """Compare today's scan with a previous one."""
    scan_type = args.scan_type or "flip"
    day = args.date

    today_str = date.today().isoformat()
    today_path = snapshot.SNAPSHOT_DIR / f"{scan_type}-{today_str}.json"
    if not today_path.exists():
        print(f"No snapshot for today ({today_str}). Run a scan with --save-snapshot first.",
              file=sys.stderr)
        sys.exit(1)

    result = snapshot.diff_scan_type(scan_type, day)
    if result is None:
        prev = snapshot.load(scan_type, day)
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
            print(f"    {name:<35} {profit:>10,}  (+{delta:>+10,})")
        if len(result["improved"]) > 10:
            print(f"    ... and {len(result['improved']) - 10} more")

    if result["fell_off"]:
        print(f"\n  Fell off ({len(result['fell_off'])}):")
        for item in result["fell_off"][:10]:
            name = item.get("name", item.get("item_id"))
            profit = item.get("profit", item.get("avg_margin", 0))
            delta = item["delta"]
            print(f"    {name:<35} {profit:>10,}  ({delta:>+10,})")
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
    paths = snapshot.list_snapshots(args.scan_type)
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
    from rshelper.config import CONFIG_PATH
    print(CONFIG_PATH)

def main() -> None:
    cfg = load_config()

    parser = argparse.ArgumentParser(
        prog="rshelper",
        description="RSHelper — OSRS Grand Exchange profit scanner",
    )
    sub = parser.add_subparsers(dest="command")

    alch = sub.add_parser("alch-scan", help="Scan for profitable high alchemy items")
    alch.add_argument("--nature-rune-cost", type=int, default=cfg.alch.nature_rune_cost,
                       help="GP cost of nature runes (default: auto-fetch from API)")
    alch.add_argument("--members-only", action="store_true",
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
    flip.add_argument("--members-only", action="store_true",
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

    info = sub.add_parser("item-info", help="Look up a single item by name or ID")
    info.add_argument("item", help="Item name or ID")
    info.add_argument("--timeseries", action="store_true",
                       help="Fetch and analyze timeseries history")
    info.add_argument("--json", action="store_true",
                       help="Output JSON instead of text")


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

    # Diff subcommand
    diff_p = sub.add_parser("diff", help="Compare today's scan with a previous one")
    diff_p.add_argument("scan_type", nargs="?", default="flip",
                        choices=["alch", "flip", "margin"],
                        help="Scan type to compare (default: flip)")
    diff_p.add_argument("--date", type=str, default=None,
                        help="Previous date to compare against (YYYY-MM-DD, default: most recent)")

    # Snapshots subcommand
    snap_p = sub.add_parser("snapshots", help="List saved scan snapshots")
    snap_p.add_argument("scan_type", nargs="?", default=None,
                        choices=["alch", "flip", "margin"],
                        help="Filter by scan type (default: all)")

    # Config subcommand
    config_parser = sub.add_parser("config", help="View or show config file path")
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_sub.add_parser("show", help="Print current config as JSON")
    config_sub.add_parser("path", help="Print config file path")

    margin = sub.add_parser("margin-check", help="Analyze timeseries history for flip confidence scoring")
    margin.add_argument("--members-only", action="store_true",
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

    args = parser.parse_args()
    if args.command == "item-info":
        item_info(args)
    elif args.command == "margin-check":
        margin_check(args)
    elif args.command == "alch-scan":
        alch_scan(args)
    elif args.command == "flip-scan":
        flip_scan(args)
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
