"""Daily scan snapshots for diff/trend comparison."""

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from rshelper.profile import CONFIG_DIR, atomic_write_json

SNAPSHOT_DIR = CONFIG_DIR / "snapshots"


def _snapshot_dir(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return SNAPSHOT_DIR
    return CONFIG_DIR / "profiles" / profile / "snapshots"


def save(scan_type: str, results: list[dict], profile: str | None = None) -> Path:
    """Save a snapshot for today. Returns the file path."""
    from rshelper.tuning import params
    snap_dir = _snapshot_dir(profile)
    snap_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path = snap_dir / f"{scan_type}-{today}.json"

    payload = {
        "scan_type": scan_type,
        "date": today,
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(results),
        "config": params(profile),
        "items": results,
    }

    # Atomic write
    atomic_write_json(path, payload)
    return path


def load(scan_type: str, day: str | None = None, profile: str | None = None) -> dict | None:
    """Load a snapshot. If day is None, loads the most recent before today."""
    snap_dir = _snapshot_dir(profile)
    snap_dir.mkdir(parents=True, exist_ok=True)
    if day:
        path = snap_dir / f"{scan_type}-{day}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    # Find most recent snapshot
    prefix = f"{scan_type}-"
    candidates = []
    for p in snap_dir.glob(f"{prefix}*.json"):
        day_str = p.stem[len(prefix):]
        candidates.append((day_str, p))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return json.loads(candidates[0][1].read_text())


def diff_scan_type(scan_type: str, day: str | None = None, profile: str | None = None) -> dict | None:
    """Compare today's snapshot with a previous one.

    Returns None if either snapshot is missing.
    """
    snap_dir = _snapshot_dir(profile)
    today_str = date.today().isoformat()
    today_path = snap_dir / f"{scan_type}-{today_str}.json"
    if not today_path.exists():
        return None

    today_data = json.loads(today_path.read_text())

    # Get previous snapshot: explicit date, or most recent before today
    if day:
        prev_data = load(scan_type, day, profile)
    else:
        today = date.today().isoformat()
        prefix = f"{scan_type}-"
        candidates = []
        for p in snap_dir.glob(f"{prefix}*.json"):
            day_str = p.stem[len(prefix):]
            if day_str < today:
                candidates.append((day_str, p))
        if candidates:
            candidates.sort(reverse=True)
            prev_data = json.loads(candidates[0][1].read_text())
        else:
            prev_data = None

    if prev_data is None:
        return None

    # Build lookup by item_id
    prev_by_id = {}
    for item in prev_data["items"]:
        prev_by_id[item["item_id"]] = item

    new_items = []
    improved = []
    fell_off = []
    unchanged = 0

    # Determine the value key: 'profit' for alch/flip, 'avg_margin' for margin scans
    sample = today_data["items"][0] if today_data["items"] else {}
    value_key = "profit" if "profit" in sample else "avg_margin"

    for item in today_data["items"]:
        iid = item["item_id"]
        prev = prev_by_id.get(iid)
        if prev is None:
            new_items.append(item)
        elif value_key in item and value_key in prev:
            delta = item[value_key] - prev[value_key]
            if delta > 0:
                improved.append({**item, "delta": delta, "prev_value": prev[value_key]})
            elif delta < 0:
                fell_off.append({**item, "delta": delta, "prev_value": prev[value_key]})
            else:
                unchanged += 1
        else:
            unchanged += 1

    prev_ids = set(prev_by_id)
    today_ids = {item["item_id"] for item in today_data["items"]}
    removed_ids = prev_ids - today_ids
    removed = [prev_by_id[iid] for iid in removed_ids]

    return {
        "scan_type": scan_type,
        "today_date": today_data["date"],
        "prev_date": prev_data["date"],
        "today_count": len(today_data["items"]),
        "prev_count": len(prev_data["items"]),
        "new": sorted(new_items, key=lambda x: -x.get("profit", 0)),
        "improved": sorted(improved, key=lambda x: -x["delta"]),
        "fell_off": sorted(fell_off, key=lambda x: x["delta"]),
        "removed": removed,
        "unchanged": unchanged,
    }


def list_snapshots(scan_type: str | None = None, profile: str | None = None) -> list[Path]:
    """List all snapshot files, newest first."""
    snap_dir = _snapshot_dir(profile)
    snap_dir.mkdir(parents=True, exist_ok=True)
    pattern = f"{scan_type}-*.json" if scan_type else "*.json"
    paths = sorted(snap_dir.glob(pattern), reverse=True)
    return paths
