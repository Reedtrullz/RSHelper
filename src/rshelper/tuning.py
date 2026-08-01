"""Tuning log: record config.toml parameter changes over time."""
import json
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone

from rshelper.config import load_config
from rshelper.profile import atomic_write_json, resolve_config_path

_TUNING_LOCK = threading.Lock()


def params(profile: str | None = None) -> dict:
    """Effective tuning parameters as a JSON-safe dict."""
    cfg = load_config(profile)
    return {"alch": asdict(cfg.alch), "flip": asdict(cfg.flip),
            "margin": asdict(cfg.margin), "trader": asdict(cfg.trader)}


def log_path(profile: str | None = None):
    return resolve_config_path("tuning_log.json", profile)


def load_entries(profile: str | None = None) -> list[dict]:
    path = log_path(profile)
    try:
        if path.exists():
            return json.loads(path.read_text()).get("entries", [])
    except (json.JSONDecodeError, OSError):
        pass
    return []


def record_if_changed(profile: str | None = None, note: str = "auto") -> dict | None:
    """Append a tuning entry when effective params changed. Returns the entry or None."""
    with _TUNING_LOCK:
        current = params(profile)
        entries = load_entries(profile)
        if entries and entries[-1]["params"] == current:
            return None
        entry = {"ts": datetime.now(timezone.utc).isoformat(),
                 "params": current, "note": note}
        entries.append(entry)
        atomic_write_json(log_path(profile), {"entries": entries})
        return entry


def config_at(day: str, entries: list[dict]) -> dict | None:
    """Params in effect on `day` (last entry on or before it), else None."""
    active = None
    for e in entries:
        if e["ts"][:10] <= day:
            active = e["params"]
    return active
