"""Daily scan snapshots for diff/trend comparison."""

import json
import hashlib
import os
from datetime import date, datetime, timezone
from pathlib import Path

from rshelper.profile import CONFIG_DIR, atomic_write_json

SNAPSHOT_DIR = CONFIG_DIR / "snapshots"


def _snapshot_dir(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return SNAPSHOT_DIR
    return CONFIG_DIR / "profiles" / profile / "snapshots"


def _specification_hash(spec):
    return hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':'),
                                    allow_nan=False).encode()).hexdigest()


def compare_manifests(current, previous):
    if (current.get('scan_type') is not None and previous.get('scan_type') is not None
            and current.get('scan_type') != previous.get('scan_type')):
        return {'status':'incompatible','reasons':['scan_type changed']}
    manifests = [current.get('manifest'),previous.get('manifest')]
    if any(value is None for value in manifests):
        return {'status':'partially-comparable','reasons':['legacy scan specification or market provenance unknown']}
    for manifest in manifests:
        if (not isinstance(manifest,dict) or manifest.get('schema_version') != 1
                or set(manifest) != {'schema_version','scan_spec','specification_sha256','market_metadata'}):
            return {'status':'incompatible','reasons':['invalid or unsupported scan manifest']}
        try:
            if manifest['specification_sha256'] != _specification_hash(manifest['scan_spec']):
                raise ValueError('fingerprint mismatch')
        except (TypeError,ValueError):
            return {'status':'incompatible','reasons':['scan specification fingerprint invalid']}
    specs = [manifest['scan_spec'] for manifest in manifests]
    if any(not isinstance(spec,dict) for spec in specs):
        return {'status':'partially-comparable','reasons':['scan specification unknown']}
    changed = [key for key in sorted(set(specs[0])|set(specs[1]))
               if key not in specs[0] or key not in specs[1] or specs[0][key] != specs[1][key]]
    if changed:
        return {'status':'incompatible','reasons':[key+' changed' for key in changed]}
    reasons = []
    if specs[0].get('units','').startswith('illustrative-'):
        reasons.append('processing timing, yield or eligibility evidence remains illustrative')
    if not {'direction','units','members_only','min_volume','capital','top','selection'} <= set(specs[0]):
        reasons.append('effective scan settings incomplete')
    metadata = [manifest['market_metadata'] for manifest in manifests]
    for endpoint in ('latest','5m'):
        records = [value.get(endpoint) if isinstance(value,dict) else None for value in metadata]
        if any(not isinstance(row,dict) or row.get('source') not in ('wiki','ge-tracker')
               or row.get('stale') is not False or not isinstance(row.get('coverage'),dict)
               or (endpoint=='5m' and row.get('volume_kind') not in ('executed-trades','standing-orders'))
               for row in records):
            reasons.append(endpoint+' provenance unknown or stale')
        elif any(records[0].get(key) != records[1].get(key) for key in ('source','volume_kind','coverage')):
            reasons.append(endpoint+' source, volume quality or coverage changed')
    return {'status':'partially-comparable' if reasons else 'compatible','reasons':reasons}


def save(scan_type: str, results: list[dict], profile: str | None = None,
         *, scan_spec=None, market_metadata=None) -> Path:
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
        'manifest':{'schema_version':1,'scan_spec':scan_spec,
                    'specification_sha256':_specification_hash(scan_spec),
                    'market_metadata':market_metadata},
    }

    # Atomic write
    atomic_write_json(path, payload)
    return path


def _read_snapshot(path: Path) -> dict | None:
    """Load a snapshot JSON, returning None on missing/corrupt."""
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def load(scan_type: str, day: str | None = None, profile: str | None = None) -> dict | None:
    """Load a snapshot. If day is None, loads the most recent before today."""
    snap_dir = _snapshot_dir(profile)
    snap_dir.mkdir(parents=True, exist_ok=True)
    if day:
        path = snap_dir / f"{scan_type}-{day}.json"
        return _read_snapshot(path)

    # Find most recent snapshot
    prefix = f"{scan_type}-"
    candidates = []
    for p in snap_dir.glob(f"{prefix}*.json"):
        day_str = p.stem[len(prefix):]
        candidates.append((day_str, p))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return _read_snapshot(candidates[0][1])


def diff_scan_type(scan_type: str, day: str | None = None, profile: str | None = None) -> dict | None:
    """Compare today's snapshot with a previous one.

    Returns None if either snapshot is missing.
    """
    snap_dir = _snapshot_dir(profile)
    today_str = date.today().isoformat()
    today_path = snap_dir / f"{scan_type}-{today_str}.json"
    today_data = _read_snapshot(today_path)
    if today_data is None:
        return None

    # Get previous snapshot: explicit date, or most recent before today
    if day:
        prev_data = _read_snapshot(snap_dir / f"{scan_type}-{day}.json")
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
            prev_data = _read_snapshot(candidates[0][1])
        else:
            prev_data = None

    if prev_data is None:
        return None

    comparison = compare_manifests(today_data,prev_data)

    # Build lookup by item_id
    prev_by_id = {}
    for item in prev_data.get("items", []):
        prev_by_id[item["item_id"]] = item

    new_items = []
    improved = []
    fell_off = []
    unchanged = 0

    # Determine the value key: 'profit' for alch/flip, 'avg_margin' for margin scans
    sample = today_data.get("items", [{}])[0] if today_data.get("items") else {}
    value_key = "profit" if "profit" in sample else "avg_margin"

    for item in today_data.get("items", []):
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
    today_ids = {item["item_id"] for item in today_data.get("items", [])}
    removed_ids = prev_ids - today_ids
    removed = [{**prev_by_id[iid],'removal_reason':'unknown: absent from saved selection'}
               for iid in sorted(removed_ids)]
    if comparison['status']=='incompatible':
        improved = []
        fell_off = []

    return {
        "scan_type": scan_type,
        'comparison':comparison,
        "today_date": today_data.get("date"),
        "prev_date": prev_data.get("date"),
        "today_count": len(today_data.get("items", [])),
        "prev_count": len(prev_data.get("items", [])),
        "new": sorted(new_items, key=lambda x: -x.get(value_key, x.get("profit", 0))),
        "improved": sorted(improved, key=lambda x: -x["delta"]),
        "fell_off": sorted(fell_off, key=lambda x: x["delta"]),
        "removed": removed,
        "unchanged": unchanged,
    }


def list_snapshots(scan_type: str | None = None, profile: str | None = None) -> list[Path]:
    """List all snapshot files, newest first (by mtime)."""
    snap_dir = _snapshot_dir(profile)
    snap_dir.mkdir(parents=True, exist_ok=True)
    pattern = f"{scan_type}-*.json" if scan_type else "*.json"
    paths = sorted(snap_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return paths
