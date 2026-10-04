"""Tuning log: record config.toml parameter changes over time."""
import json
from datetime import datetime, timezone

from rshelper.config import effective_config_dict, load_config
from rshelper.profile import atomic_write_json, resolve_config_path
from rshelper.persistence import read_state, locked_state, StateCorruptionError


def params(profile: str | None = None) -> dict:
    """Effective tuning parameters as a JSON-safe dict."""
    return effective_config_dict(load_config(profile))


def log_path(profile: str | None = None):
    return resolve_config_path("tuning_log.json", profile)


def _load_log(profile: str | None = None) -> dict:
    path = log_path(profile)
    data = read_state(path, "generic")
    if not data:
        try:
            path.stat()
        except FileNotFoundError:
            return {"entries": []}
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise StateCorruptionError("tuning_log.json: entries must be a list; original bytes preserved")
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("ts"), str)
                or not isinstance(entry.get("params"), dict)
                or ("note" in entry and not isinstance(entry["note"], str))):
            raise StateCorruptionError("tuning_log.json: invalid tuning entry; original bytes preserved")
        try:
            datetime.fromisoformat(entry["ts"].replace("Z", "+00:00"))
        except ValueError:
            raise StateCorruptionError("tuning_log.json: invalid tuning timestamp; original bytes preserved") from None
    return data


def load_entries(profile: str | None = None) -> list[dict]:
    return _load_log(profile)["entries"]


def record_if_changed(profile: str | None = None, note: str = "auto") -> dict | None:
    """Append under a shared lock; failed reads preserve the existing log."""
    with locked_state(log_path(profile)):
        data = _load_log(profile)
        current = params(profile)
        entries = data["entries"]
        if entries and entries[-1]["params"] == current:
            return None
        entry = {"ts": datetime.now(timezone.utc).isoformat(),
                 "params": current, "note": note}
        entries.append(entry)
        atomic_write_json(log_path(profile), data)
        return entry


def config_at(day: str, entries: list[dict]) -> dict | None:
    """Params in effect on `day` (last entry on or before it), else None."""
    active = None
    for e in entries:
        if e["ts"][:10] <= day:
            active = e["params"]
    return active
