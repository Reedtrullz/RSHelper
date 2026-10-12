"""Tuning log: record config.toml parameter changes over time."""
import json
import hashlib
import math
import time
from datetime import datetime, timezone

from rshelper.config import effective_config_dict, load_config, validate_config
from rshelper.profile import atomic_write_json, resolve_config_path
from rshelper.persistence import read_state, locked_state, StateCorruptionError


def params(profile: str | None = None) -> dict:
    """Effective tuning parameters as a JSON-safe dict."""
    return effective_config_dict(load_config(profile))


def config_id(values):
    return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':'),
                                    allow_nan=False).encode()).hexdigest()


def _instant(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.utcoffset() is None:raise ValueError('configuration instant requires a timezone')
    return parsed.astimezone(timezone.utc)


def config_at_timestamp(timestamp,entries):
    try:target=_instant(timestamp)
    except (ValueError,TypeError,AttributeError):return None
    candidates=[]
    for entry in entries:
        try:instant=_instant(entry['ts'])
        except (ValueError,TypeError,AttributeError,KeyError):continue
        if instant<=target:candidates.append((instant,entry['params']))
    if not candidates:return None
    latest=max(instant for instant,_ in candidates)
    active=[value for instant,value in candidates if instant==latest]
    if len({config_id(value) for value in active})!=1:return None
    return active[0]


def config_evidence(profile,*,now=None,trader_config=None):
    now=time.time() if now is None else now
    if type(now) not in (int,float) or not math.isfinite(now) or now<0:
        raise ValueError('invalid configuration evidence time')
    current=load_config(profile)
    if trader_config is not None:current.trader=trader_config
    validate_config(current)
    values=effective_config_dict(current)
    return {'config_id':config_id(values),'params':values,
            'effective_at':datetime.fromtimestamp(now,timezone.utc).isoformat()}


def validate_config_evidence(evidence):
    if evidence is None:return None
    if (not isinstance(evidence,dict) or set(evidence)!={'config_id','params','effective_at'}
            or not isinstance(evidence['params'],dict)
            or evidence['config_id']!=config_id(evidence['params'])
            or _instant(evidence['effective_at']).isoformat()!=evidence['effective_at']):
        raise ValueError('invalid configuration evidence')
    return evidence


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
        if 'config_id' in entry:
            try:
                if entry['config_id'] != config_id(entry['params']):
                    raise ValueError('configuration fingerprint mismatch')
                _instant(entry['ts'])
            except (ValueError,TypeError,AttributeError):
                raise StateCorruptionError('tuning_log.json: invalid configuration evidence; original bytes preserved') from None
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
                 "params": current, "note": note,"config_id":config_id(current)}
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
