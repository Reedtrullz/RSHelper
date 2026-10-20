"""Daily history for the dashboard Progression view."""
import json
import re
import math
from collections import defaultdict
from bisect import bisect_right
from datetime import datetime, timezone

from rshelper import snapshot, tuning, trade_reviews
from rshelper.journal import compute_pnl, compute_pnl_by_item, list_trades, _utc


def build_history(profile: str | None = None, paper_only: bool = True,
                  strategy: str = "", *, trades=None) -> dict:
    """Join trades, snapshots, and tuning entries into daily buckets and eras."""
    note = "paper" if paper_only else ""
    if trades is None:
        trades = list_trades(note=note, profile=profile, strategy=strategy)
    pnl = compute_pnl(trades=trades)
    items = compute_pnl_by_item(trades=trades)
    entries = tuning.load_entries(profile)

    daily: dict[str, list] = defaultdict(list)
    for t in trades:
        daily[_utc(t.timestamp).date().isoformat()].append(t)

    snaps_by_day: dict[str, list] = defaultdict(list)
    equity_points={}
    for path in snapshot.list_snapshots(profile=profile):
        match=re.fullmatch(r'(?:alch|flip|margin|process|equity)-(\d{4}-\d{2}-\d{2})(?:T\d{6}\.\d{6}Z)?',path.stem)
        if match is None:
            # Malformed snapshot filename: skip instead of corrupting the
            # daily buckets with a phantom key.
            continue
        day=match.group(1)
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data,dict):continue
        if data.get('scan_type')=='equity':
            equity=data.get('equity')
            try:
                instant=tuning._instant(data['saved_at'])
            except (KeyError,ValueError,TypeError,AttributeError):continue
            if not isinstance(equity,dict) or equity.get('scope')!='whole-profile':continue
            value=equity.get('marked_equity')
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value)):
                continue
            equity_points[instant]={'date':instant.isoformat(),'marked_equity':value,
                                    'equity':equity,'config_id':data.get('config_id')}
        vals = [i.get("profit") if i.get("profit") is not None else i.get("avg_margin")
                for i in data.get("items", [])]
        vals = [v for v in vals if v is not None]
        snaps_by_day[day].append({
            "scan_type": data.get("scan_type"),
            'manifest':data.get('manifest'),
            'comparison':snapshot.compare_manifests(data,data),
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

    today = datetime.now(timezone.utc).date().isoformat()
    last_day = days[-1] if days else today
    eras = []
    timed=[]
    for entry in entries:
        try:timed.append((tuning._instant(entry['ts']),entry))
        except (ValueError,TypeError,AttributeError):continue
    timed.sort(key=lambda pair:pair[0])
    by_instant=defaultdict(list)
    for instant,entry in timed:by_instant[instant].append(entry)
    timed=[]
    for instant,group in sorted(by_instant.items()):
        unique={tuning.config_id(entry['params']) for entry in group}
        timed.append((instant,group[0] if len(unique)==1 else
                      {'params':{},'note':'conflicting configuration evidence','unknown':True}))
    era_starts = [instant for instant, _ in timed]
    trades_by_era = [[] for _ in timed]
    if timed:
        for trade in trades:
            index = bisect_right(era_starts, _utc(trade.timestamp)) - 1
            if index >= 0:
                trades_by_era[index].append(trade)
    for i, (instant,e) in enumerate(timed):
        end_instant=timed[i+1][0] if i+1<len(timed) else None
        start=instant.isoformat()
        end=end_instant.isoformat() if end_instant else None
        era_trades = trades_by_era[i]
        cost = sum(t.buy_price * t.qty for t in era_trades)
        profit = sum(t.profit for t in era_trades)
        wins = sum(1 for t in era_trades if t.profit > 0)
        losses = sum(1 for t in era_trades if t.profit < 0)
        gross_profit = sum(t.profit for t in era_trades if t.profit > 0)
        gross_loss = abs(sum(t.profit for t in era_trades if t.profit < 0))
        active_days = len({_utc(t.timestamp).date() for t in era_trades})
        eras.append({
            "start": start,
            "end": end,
            "config": e["params"],
            "config_id":None if e.get('unknown') else tuning.config_id(e['params']),
            "attribution_basis":"unknown-exit-context" if e.get('unknown') else "exit-time-context",
            "note": e.get("note", "auto"),
            "trade_count": len(era_trades),
            "profit": profit,
            "win_rate": round(wins / len(era_trades) * 100, 1) if era_trades else None,
            "roi_pct": round(profit / cost * 100, 2) if cost else None,
            "turnover_roi_pct":round(profit / cost * 100, 2) if cost else None,
            "trades_per_day": round(len(era_trades) / active_days, 1) if active_days else 0,
            "profit_factor": (round(gross_profit / gross_loss, 2)
                              if gross_loss > 0 else
                              None if gross_profit > 0 else None),
            "loss_trades": losses,
        })

    strategy_groups={}
    for trade in trades:
        evidence=trade.entry_config
        key=evidence['config_id'] if evidence else 'unknown'
        group=strategy_groups.setdefault(key,{'config_id':None if key=='unknown' else key,
                'entry_config':evidence,'trade_count':0,'profit':0,'cost_basis':0,
                'attribution_basis':'immutable-entry-configuration' if evidence else 'unknown-legacy-entry'})
        group['trade_count']+=1
        group['profit']+=trade.profit
        group['cost_basis']+=trade.qty*trade.buy_price
    curve=[]
    previous=None
    for instant,point in sorted(equity_points.items()):
        point['gap_before']=previous is not None and (instant-previous).total_seconds()>86400
        point['config_changed']=any((previous is None or previous<ts) and ts<=instant for ts,_ in timed)
        curve.append(point)
        previous=instant
    return {
        'reviews':trade_reviews.review_queue(profile,trades,note=note,strategy=strategy),
        'strategy_eras':list(strategy_groups.values()),
        'equity_curve':curve,
        'equity_scope':'whole-profile; independent of trade filters',
        'equity_sampling':'observed only; gaps over 24 hours are disconnected; missing marks unknown',
        "summary": {
            "total_profit": pnl.total_profit,
            "win_rate": round(pnl.win_rate, 1),
            "roi_pct": round(pnl.roi_pct, 2),
            "turnover_roi_pct":round(pnl.roi_pct,2),
            "trade_count": pnl.trade_count,
            "items_traded": pnl.items_traded,
            "active_days": len({_utc(t.timestamp).date() for t in trades}),
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
