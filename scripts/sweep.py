#!/usr/bin/env python3
"""Compare explicit simulated configs; never change production configuration."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from replay import ReplayConfig, load_data, simulate, selected_config, decode_json


def _sweep() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    ap.add_argument('--data',required=True)
    ap.add_argument('--mapping',required=True)
    ap.add_argument('--config',required=True,choices=('runtime-defaults','historical-baseline'))
    ap.add_argument('--config-file')
    ap.add_argument('--slots',required=True,type=int,choices=(3,8))
    args = ap.parse_args()

    try:
        data=load_data(args.data)
        mapping=Path(args.mapping)
        if mapping.stat().st_size>64*1024*1024:raise ValueError('mapping exceeds 64 MiB')
        metadata=decode_json(mapping.read_text())
        base=selected_config(args.config,args.config_file)
        if not 1<=args.top<=100:raise ValueError('top must be 1..100')
    except (OSError,ValueError,TypeError) as exc:
        print(str(exc),file=sys.stderr);return 1
    if not data:
        print("no data; run the fetch first", file=sys.stderr)
        return 1

    # Sweep grid: one variable at a time around the current defaults, then a
    # few combined best candidates. Key = config field name.
    sweeps = {
        "min_spread_pct": [3.0, 3.5, 4.0, 4.5, 5.0],
        "dip_depth_pct": [1.0, 2.0, 3.0],
        "max_dip_pct": [8.0, 10.0, 15.0],
        "stop_loss_pct": [-1.0, -1.5, -2.0, -2.5],
        "take_profit_pct": [2.0, 3.0, 4.0, 5.0],
        "stop_grace_minutes": [0, 5, 10, 20],
        "spread_collapse_exit_minutes": [30, 60, 90, 120],
        "max_hold_minutes": [120, 180, 240],
    }
    results = []

    def run(cfg: ReplayConfig, label: str) -> dict:
        r = simulate(data, cfg,metadata=metadata,slot_limit=args.slots,trace_limit=0)
        r["label"] = label
        r["cfg"] = asdict(cfg)
        results.append(r)
        return r

    run(base, "baseline")

    # One-variable sweeps
    for var, vals in sweeps.items():
        for v in vals:
            cfg = ReplayConfig(**{**base.__dict__, var: v})
            run(cfg, f"{var}={v}")

    # A few combined candidates from the best singles
    combined_candidates = [
        {"min_spread_pct": 4.5, "stop_loss_pct": -2.0, "take_profit_pct": 4.0},
        {"min_spread_pct": 4.0, "stop_loss_pct": -2.0, "take_profit_pct": 4.0,
         "spread_collapse_exit_minutes": 90},
        {"min_spread_pct": 4.0, "dip_depth_pct": 3.0, "stop_loss_pct": -2.0},
        {"min_spread_pct": 5.0, "stop_loss_pct": -2.0, "stop_grace_minutes": 20},
    ]
    for combo in combined_candidates:
        cfg = ReplayConfig(**{**base.__dict__, **combo})
        run(cfg, f"combo:{','.join(f'{k}={v}' for k, v in combo.items())}")

    # Rank by ROI (only configs that produced trades)
    ranked = [r for r in results if r.get("trades", 0) > 0]
    ranked.sort(key=lambda r: r.get("roi_pct", -999), reverse=True)
    stream = sys.stderr if args.json else sys.stdout
    print(f"=== Top {args.top} configs by ROI (from {len(ranked)} runs) ===", file=stream)
    for r in ranked[:args.top]:
        print(f"  {r['label']:45s} roi={r['roi_pct']:6.2f}% win={r['win_rate']:5.1f}% "
              f"trades={r['trades']:4d} pf={r['profit_factor']} max_dd={r['max_drawdown']}", file=stream)
    if args.json:
        print(json.dumps(ranked[:args.top],allow_nan=False,indent=2))
    return 0


def main() -> int:
    try:return _sweep()
    except (OSError,ValueError,TypeError) as exc:
        print(str(exc),file=sys.stderr);return 1


if __name__ == "__main__":
    raise SystemExit(main())
