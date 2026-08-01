"""Daily history for the dashboard Progression view."""
import json
import re
from collections import defaultdict
from datetime import date

from rshelper import snapshot, tuning
from rshelper.journal import compute_pnl, compute_pnl_by_item, list_trades


def build_history(profile: str | None = None, paper_only: bool = True,
                  strategy: str = "") -> dict:
    """Join trades, snapshots, and tuning entries into daily buckets and eras."""
    note = "paper" if paper_only else ""
    trades = list_trades(note=note, profile=profile, strategy=strategy)
    pnl = compute_pnl(note=note, profile=profile, strategy=strategy)
    items = compute_pnl_by_item(note=note, profile=profile, strategy=strategy)
    entries = tuning.load_entries(profile)

    daily: dict[str, list] = defaultdict(list)
    for t in trades:
        daily[t.timestamp[:10]].append(t)

    snaps_by_day: dict[str, list] = defaultdict(list)
    for path in snapshot.list_snapshots(profile=profile):
        day = path.stem[-10:]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            # Malformed snapshot filename: skip instead of corrupting the
            # daily buckets with a phantom key.
            continue
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        vals = [i.get("profit") if i.get("profit") is not None else i.get("avg_margin")
                for i in data.get("items", [])]
        vals = [v for v in vals if v is not None]
        snaps_by_day[day].append({
            "scan_type": data.get("scan_type"),
            "count": data.get("count", 0),
            "avg_value": round(sum(vals) / len(vals)) if vals else None,
        })

    days = sorted(set(daily) | set(snaps_by_day))
    buckets = []
    cumulative = 0
    for day in days:
        day_trades = daily.get(day, [])
        profit = sum(t.profit for t in day_trades)
        wins = sum(1 for t in day_trades if t.profit > 0)
        cumulative += profit
        buckets.append({
            "date": day,
            "trade_count": len(day_trades),
            "profit": profit,
            "cumulative_profit": cumulative,
            "win_rate": round(wins / len(day_trades) * 100, 1) if day_trades else None,
            "avg_profit_per_trade": round(profit / len(day_trades)) if day_trades else None,
            "snapshots": snaps_by_day.get(day, []),
            "config": tuning.config_at(day, entries),
            "config_changed": any(e["ts"][:10] == day for e in entries),
        })

    today = date.today().isoformat()
    last_day = days[-1] if days else today
    eras = []
    for i, e in enumerate(entries):
        start = e["ts"][:10]
        final_era = i + 1 == len(entries)
        if final_era:
            end = last_day
            # The last era runs through the most recent traded day inclusive;
            # a strict '<' would silently drop today's trades from all
            # performance summaries whenever the config did not change today.
            era_trades = [t for t in trades
                          if start <= t.timestamp[:10] <= last_day]
        else:
            end = entries[i + 1]["ts"][:10]
            if end <= start:
                # Two entries on the same day: day-level buckets cannot split
                # the day, so the earlier era is empty. The later entry owns
                # the whole day, matching the "last entry on or before the
                # trade day wins" rule used by config_at.
                era_trades = []
            else:
                era_trades = [t for t in trades
                              if start <= t.timestamp[:10] < end]
        cost = sum(t.buy_price * t.qty for t in era_trades)
        profit = sum(t.profit for t in era_trades)
        wins = sum(1 for t in era_trades if t.profit > 0)
        active_days = len({t.timestamp[:10] for t in era_trades})
        eras.append({
            "start": start,
            "end": end,
            "config": e["params"],
            "note": e.get("note", "auto"),
            "trade_count": len(era_trades),
            "profit": profit,
            "win_rate": round(wins / len(era_trades) * 100, 1) if era_trades else None,
            "roi_pct": round(profit / cost * 100, 2) if cost else None,
            "trades_per_day": round(len(era_trades) / active_days, 1) if active_days else 0,
        })

    return {
        "summary": {
            "total_profit": pnl.total_profit,
            "win_rate": round(pnl.win_rate, 1),
            "roi_pct": round(pnl.roi_pct, 2),
            "trade_count": pnl.trade_count,
            "items_traded": pnl.items_traded,
            "active_days": len({t.timestamp[:10] for t in trades}),
        },
        "buckets": buckets,
        "eras": eras,
        "items": [
            {"item_id": i.item_id, "name": i.name, "trade_count": i.trade_count,
             "qty": i.qty, "cost_basis": i.cost_basis, "profit": i.profit,
             "roi_pct": round(i.roi_pct, 2), "win_rate": round(i.win_rate, 1)}
            for i in items
        ],
    }
