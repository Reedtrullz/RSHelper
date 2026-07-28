"""CLI entry point for RSHelper."""

import argparse
import csv
import io
import json
import sys

from rshelper.api import fetch_mapping, fetch_latest, fetch_5m, cleanup_stale_cache, fetch_timeseries_batch, fetch_timeseries
from rshelper.scanner import AlchScanner, FlipScanner, MarginScanner, build_items_from_api


def _fetch_bootstrap():
    """Shared fetch-bootstrap: mapping, latest, 5m volume, and built items."""
    removed = cleanup_stale_cache()
    if removed:
        print(f"  Cleaned {removed} stale cache files")

    print("Fetching OSRS Wiki prices...")
    mapping = fetch_mapping()
    if not mapping:
        print("Error: could not fetch item mapping.", file=sys.stderr)
        sys.exit(1)
    latest = fetch_latest()
    if not latest:
        print("Error: could not fetch latest prices.", file=sys.stderr)
        sys.exit(1)
    volume_5m = fetch_5m() or {}

    print("Building item list...")
    items = build_items_from_api(mapping, latest, volume_5m)
    print(f"  {len(items)} items with price data")
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


def _format_flip_table(results, top: int) -> str:
    """Render flip results as an aligned text table."""
    rows = results[:top]
    if not rows:
        return "No profitable flips found."
    name_width = max(len(r.name) for r in rows)
    name_width = min(name_width, 40)
    name_width = max(name_width, 10)
    header = f"{'Rank':<5} {'Item':<{name_width}} {'Buy':>10} {'Sell':>9} {'Margin':>8} {'GP/hr':>10} {'Limit':>7}"
    sep = "-" * len(header)
    lines = [header, sep]
    for i, item in enumerate(rows, 1):
        name = item.name[:name_width]
        lines.append(
            f"{i:<5} {name:<{name_width}} {item.buy_price:>10,} {item.sell_price:>9,} "
            f"{item.profit:>8,} {item.gp_per_hour:>10,} {item.buy_limit:>7,}"
        )
    return "\n".join(lines)

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
        print(f"  Nature rune: {nature_cost} gp")

    scanner = AlchScanner(nature_rune_cost=nature_cost)
    results = scanner.scan(
        items,
        members_only=args.members_only,
        min_volume=args.min_volume,
    )
    print(f"  {len(results)} profitable alchs")
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
    else:
        print(_format_table(results, args.top))


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
    scanner = FlipScanner(direction=direction)
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
        fields = ["rank", "name", "buy_price", "sell_price", "profit", "gp_per_hour", "volume", "buy_limit"]
        fm = {}
        for f in fields:
            if f == "profit":
                fm[f] = lambda r: r.profit
            elif f != "rank":
                fm[f] = lambda r, f=f: getattr(r, f, "")
        print(_csv_output(results, args.top, fields, fm))
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
    else:
        print(_format_flip_table(results, args.top))


def _format_margin_table(results, top: int, lookup: dict) -> str:
    """Render margin-check results as an aligned text table."""
    rows = results[:top]
    if not rows:
        return "No items with sufficient timeseries data."
    name_width = max(len(lookup[a.item_id].name) for a in rows if a.item_id in lookup)
    name_width = min(name_width, 24)
    name_width = max(name_width, 6)
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
    flip_scanner = FlipScanner(direction=direction)
    flips = flip_scanner.scan(
        items,
        members_only=args.members_only,
        min_volume=args.min_volume,
        min_margin=args.min_margin,
    )
    print(f"  {len(flips)} profitable flips ({direction} mode)")

    # Apply --name filter before selecting candidates
    if args.name:
        flips = _filter_by_name(flips, args.name)
        print(f"  {len(flips)} after --name filter")

    # Take top N candidates for timeseries analysis
    candidates = flips[:args.check]
    if not candidates:
        print("\nNo flip candidates to check.")
        return

    # Build lookup: item_id -> Item (includes names for display)
    lookup = {item.id: item for item in items}

    print(f"\nFetching timeseries for top {len(candidates)} candidates...")
    candidate_ids = [c.id for c in candidates]
    ts_data = fetch_timeseries_batch(
        candidate_ids,
        timestep="5m",
        on_progress=lambda cur, tot: print(f"  [{cur}/{tot}] fetching history...", end="\r"),
    )
    print(f"\n  {len(ts_data)}/{len(candidate_ids)} items have timeseries data")

    if not ts_data:
        print("No timeseries data available.")
        return

    # Analyze
    margin_scanner = MarginScanner()
    results = margin_scanner.scan(lookup, ts_data, members_only=args.members_only)
    print(f"  {len(results)} items analyzed\n")

    if args.csv:
        fields = ["rank", "name", "item_id", "confidence", "reliability", "profitability_score",
                   "avg_margin", "margin_consistency", "margin_volatility", "avg_spread_pct",
                   "avg_volume", "datapoints", "window_hours"]
        fm = {}
        for f in fields:
            if f == "name":
                fm[f] = lambda a: lookup[a.item_id].name if a.item_id in lookup else str(a.item_id)
            elif f not in ("rank",):
                fm[f] = lambda a, f=f: round(getattr(a, f, 0), 4) if isinstance(getattr(a, f, 0), float) else getattr(a, f, 0)
        print(_csv_output(results, args.top, fields, fm))
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
        print(_format_margin_table(results, args.top, lookup))


def item_info(args: argparse.Namespace) -> None:
    """Look up a single item by name or ID."""
    removed = cleanup_stale_cache()
    if removed:
        print(f"  Cleaned {removed} stale cache files")

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
        flip_margin = sell_price - buy_price
        tax_flip = max(1, int(sell_price * 0.02))
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
        flip_margin = sell_price - buy_price
        tax_flip = max(1, int(sell_price * 0.02))
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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rshelper",
        description="RSHelper — OSRS Grand Exchange profit scanner",
    )
    sub = parser.add_subparsers(dest="command")

    alch = sub.add_parser("alch-scan", help="Scan for profitable high alchemy items")
    alch.add_argument("--nature-rune-cost", type=int, default=0,
                       help="GP cost of nature runes (default: auto-fetch from API)")
    alch.add_argument("--members-only", action="store_true",
                       help="Filter to members items only")
    alch.add_argument("--min-volume", type=int, default=0,
                       help="Minimum 5-minute trade volume")
    alch.add_argument("--top", type=int, default=50,
                       help="Number of results to show")
    alch.add_argument("--name", type=str, default="",
                       help="Filter by item name (substring match)")
    alch.add_argument("--json", action="store_true",
                       help="Output JSON instead of table")
    alch.add_argument("--csv", action="store_true",
                       help="Output CSV instead of table")

    flip = sub.add_parser("flip-scan", help="Scan for profitable GE flip margins")
    flip.add_argument("--members-only", action="store_true",
                       help="Filter to members items only")
    flip.add_argument("--min-volume", type=int, default=0,
                       help="Minimum 5-minute trade volume")
    flip.add_argument("--min-margin", type=int, default=0,
                       help="Minimum flip margin per item")
    flip.add_argument("--top", type=int, default=50,
                       help="Number of results to show")
    flip.add_argument("--flip-direction", type=str, default="arbitrage",
                       choices=["arbitrage", "traditional"],
                       help="Flip mode: arbitrage (low>high windows) or traditional (high-low-tax)")
    flip.add_argument("--name", type=str, default="",
                       help="Filter by item name (substring match)")
    flip.add_argument("--json", action="store_true",
                       help="Output JSON instead of table")
    flip.add_argument("--csv", action="store_true",
                       help="Output CSV instead of table")

    info = sub.add_parser("item-info", help="Look up a single item by name or ID")
    info.add_argument("item", help="Item name or ID")
    info.add_argument("--timeseries", action="store_true",
                       help="Fetch and analyze timeseries history")
    info.add_argument("--json", action="store_true",
                       help="Output JSON instead of text")

    margin = sub.add_parser("margin-check", help="Analyze timeseries history for flip confidence scoring")
    margin.add_argument("--members-only", action="store_true",
                       help="Filter to members items only")
    margin.add_argument("--min-volume", type=int, default=0,
                       help="Minimum 5-minute trade volume")
    margin.add_argument("--min-margin", type=int, default=0,
                       help="Minimum flip margin per item")
    margin.add_argument("--check", type=int, default=20,
                       help="Number of top flip candidates to check (default: 20)")
    margin.add_argument("--top", type=int, default=20,
                       help="Number of results to show")
    margin.add_argument("--flip-direction", type=str, default="arbitrage",
                        choices=["arbitrage", "traditional"],
                        help="Flip mode: arbitrage (low>high windows) or traditional (high-low-tax)")
    margin.add_argument("--name", type=str, default="",
                        help="Filter by item name (substring match)")
    margin.add_argument("--json", action="store_true",
                       help="Output JSON instead of table")
    margin.add_argument("--csv", action="store_true",
                       help="Output CSV instead of table")

    args = parser.parse_args()
    if args.command == "item-info":
        item_info(args)
    elif args.command == "margin-check":
        margin_check(args)
    elif args.command == "alch-scan":
        alch_scan(args)
    elif args.command == "flip-scan":
        flip_scan(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
