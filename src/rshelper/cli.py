"""CLI entry point for RSHelper."""

import argparse
import json
import sys

from rshelper.api import fetch_mapping, fetch_latest, fetch_5m
from rshelper.scanner import AlchScanner, build_items_from_api


def _format_table(results, top: int) -> str:
    """Render results as an aligned text table."""
    rows = results[:top]
    if not rows:
        return "No profitable alchs found."
    header = f"{'Rank':<5} {'Item':<30} {'Buy':>10} {'Alch':>10} {'Profit':>8} {'GP/hr':>10} {'Limit':>7}"
    sep = "-" * len(header)
    lines = [header, sep]
    for i, item in enumerate(rows, 1):
        lines.append(
            f"{i:<5} {item.name:<30} {item.buy_price:>10,} {item.alch_value:>10,} "
            f"{item.profit:>8,} {item.gp_per_hour:>10,} {item.buy_limit:>7,}"
        )
    return "\n".join(lines)


def alch_scan(args: argparse.Namespace) -> None:
    """Fetch data, scan for profitable alchs, print results."""
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

    scanner = AlchScanner(nature_rune_cost=args.nature_rune_cost)
    results = scanner.scan(
        items,
        members_only=args.members_only,
        min_volume=args.min_volume,
    )
    print(f"  {len(results)} profitable alchs\n")

    if args.json:
        print(json.dumps([
            {
                "rank": i + 1,
                "name": r.name,
                "buy_price": r.buy_price,
                "alch_value": r.alch_value,
                "profit": r.profit,
                "gp_per_hour": r.gp_per_hour,
                "buy_limit": r.buy_limit,
            }
            for i, r in enumerate(results[:args.top])
        ], indent=2))
    else:
        print(_format_table(results, args.top))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rshelper",
        description="RSHelper — OSRS Grand Exchange profit scanner",
    )
    sub = parser.add_subparsers(dest="command")

    alch = sub.add_parser("alch-scan", help="Scan for profitable high alchemy items")
    alch.add_argument("--nature-rune-cost", type=int, default=147, help="GP cost of nature runes (default: 147)")
    alch.add_argument("--members-only", action="store_true", help="Filter to members items only")
    alch.add_argument("--min-volume", type=int, default=0, help="Minimum 5-minute trade volume")
    alch.add_argument("--top", type=int, default=50, help="Number of results to show")
    alch.add_argument("--json", action="store_true", help="Output JSON instead of table")

    args = parser.parse_args()
    if args.command == "alch-scan":
        alch_scan(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
