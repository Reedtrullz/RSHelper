#!/usr/bin/env python3
"""Merge repo-tracked RSHelper state over a live state volume.

The deployed site can write its own journal/positions/watchlist entries
(POST endpoints), so a naive seed overwrites those site-side writes on every
deploy. This script merges the staged repo copy with the volume copy:

  - trades.json / positions.json : union by numeric id (repo row wins ties)
  - watchlist.json              : union by item key (repo entry wins ties)
  - snapshots/ and other files  : repo/staged version wins outright
  - files only in the volume    : kept

Usage: merge_state.py STAGE_DIR VOLUME_DIR [--chown UID:GID]
"""

import json
import os
import shutil
import sys
import tempfile

LIST_FILES = {
    "trades.json": ("trades", "id"),
    "positions.json": ("positions", "id"),
}
DICT_FILES = {
    "watchlist.json": "items",
}


def _read_list(path: str, key: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get(key, []) if isinstance(data, dict) else []
        return [r for r in rows if isinstance(r, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def _read_dict(path: str, key: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get(key, {}) if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: str, payload: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                               prefix=os.path.basename(path) + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def merge_dir(stage: str, volume: str, chown: str | None) -> None:
    os.makedirs(volume, exist_ok=True)
    for name in sorted(os.listdir(stage)):
        src = os.path.join(stage, name)
        dst = os.path.join(volume, name)
        if os.path.isdir(src):
            merge_dir(src, dst, chown)
            if chown:
                uid, gid = (int(x) for x in chown.split(":"))
                os.chown(dst, uid, gid)
            continue
        if not os.path.isfile(src):
            continue
        if name in LIST_FILES:
            key, id_key = LIST_FILES[name]
            rows: dict = {}
            for row in _read_list(dst, key):
                rows[row.get(id_key)] = row
            for row in _read_list(src, key):
                rows[row.get(id_key)] = row  # repo wins on id ties
            ordered = sorted(rows, key=lambda k: (k is None, k))
            _write_json(dst, {key: [rows[k] for k in ordered]})
        elif name in DICT_FILES:
            key = DICT_FILES[name]
            merged = _read_dict(dst, key)
            merged.update(_read_dict(src, key))  # repo wins on key ties
            _write_json(dst, {key: merged})
        else:
            shutil.copy2(src, dst)
        if chown:
            uid, gid = (int(x) for x in chown.split(":"))
            os.chown(dst, uid, gid)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: merge_state.py STAGE_DIR VOLUME_DIR [--chown UID:GID]",
              file=sys.stderr)
        return 2
    stage, volume = argv[0], argv[1]
    chown = None
    if "--chown" in argv:
        idx = argv.index("--chown")
        if idx + 1 >= len(argv):
            print("error: --chown requires UID:GID", file=sys.stderr)
            return 2
        chown = argv[idx + 1]
    if not os.path.isdir(stage):
        print(f"error: stage dir {stage} does not exist", file=sys.stderr)
        return 2
    merge_dir(stage, volume, chown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
