#!/usr/bin/env python3
"""Merge repo-tracked RSHelper state over a live state volume.

The deployed site can write its own journal/positions/watchlist entries
(POST endpoints), so a naive seed overwrites those site-side writes on every
deploy. This script merges the staged repo copy with the volume copy:

  - trades.json               : union by numeric id (repo row wins ties)
  - positions.json            : repo/staged version wins outright — the
                                trader is the sole writer of open positions,
                                so volume rows for already-closed positions
                                are stale ghosts that must be pruned, not
                                unioned back in
  - watchlist.json            : union by item key (repo entry wins ties)
  - snapshots/ and other files: repo/staged version wins outright
  - files only in the volume  : kept

Usage: merge_state.py STAGE_DIR VOLUME_DIR [--chown UID:GID]
"""

import json
import os
import shutil
import sys
import tempfile

LIST_FILES = {
    "trades.json": ("trades", "id"),
    "alerts.json": ("alerts", "id"),
}
DICT_FILES = {
    "watchlist.json": "items",
}
# Files where the repo/staged copy is the source of truth and the volume
# copy must be replaced wholesale (no union) — positions are trader-owned,
# so a volume row for a closed position is a ghost that must disappear.
REPLACE_FILES = {"positions.json"}


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
        if name == "alerts.json":
            # alerts carry a watch_triggered dedupe map alongside the feed;
            # the union must preserve it (max ts per item wins) or every
            # deploy would reset the 15-min window and re-fire alerts.
            _merge_alerts(src, dst)
        elif name in LIST_FILES:
            key, id_key = LIST_FILES[name]
            # Union by id. Unlike the plain dict-union, an id present in
            # BOTH copies with DIFFERENT content must keep both rows: the
            # Mac and the VPS each number trades/alerts from max+1, so a
            # cross-process id collision means two different rows, not a
            # duplicate. The repo row wins the id; the volume row is kept
            # with a synthetic id. (A dict-union would silently drop it.)
            vol_rows = _read_list(dst, key)
            src_rows = _read_list(src, key)
            by_id: dict = {}
            for row in vol_rows:
                rid = row.get(id_key)
                if rid is None:
                    continue  # malformed row: no id to union on; skip
                by_id.setdefault(rid, []).append(row)
            for row in src_rows:
                rid = row.get(id_key)
                if rid is None:
                    continue
                if rid in by_id:
                    # Only a DIFFERENT row with the same id is a true
                    # cross-process collision (Mac and VPS each numbered #N
                    # for different rows). Identical rows (the common case:
                    # the same state synced twice) must collapse to one.
                    if row == by_id[rid][0]:
                        continue
                    by_id[rid].insert(0, row)
                else:
                    by_id[rid] = [row]
            merged = []
            next_synthetic = max(
                (r.get("id", 0) or 0) for r in vol_rows + src_rows
            ) + 1 if (vol_rows or src_rows) else 1
            for rid in sorted(by_id, key=lambda k: (k is None, k)):
                group = by_id[rid]
                merged.append(group[0])
                for extra in group[1:]:
                    # Volume-side collision: renumber so both survive.
                    extra = dict(extra)
                    extra["id"] = next_synthetic
                    next_synthetic += 1
                    merged.append(extra)
            _write_json(dst, {key: merged})
        elif name in REPLACE_FILES:
            # The staged copy is the source of truth: replace the volume
            # file wholesale so closed positions are pruned (no ghosts).
            shutil.copy2(src, dst)
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


def _merge_alerts(src: str, dst: str) -> None:
    """Union alerts by id (repo wins ties) and merge watch_triggered by max ts.

    Alerts can also collide across machines (each side numbers from max+1),
    so a collided id keeps BOTH rows — the repo row wins the id and the
    volume row is renumbered (same as LIST_FILES).
    """
    def _read(path: str) -> dict:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    a, b = _read(dst), _read(src)
    vol_rows = [r for r in a.get("alerts", []) if isinstance(r, dict)]
    src_rows = [r for r in b.get("alerts", []) if isinstance(r, dict)]
    by_id: dict = {}
    for row in vol_rows:
        rid = row.get("id")
        if rid is None:
            continue
        by_id.setdefault(rid, []).append(row)
    for row in src_rows:
        rid = row.get("id")
        if rid is None:
            continue
        if rid in by_id:
            # Identical rows collapse; only a DIFFERENT row is a true
            # cross-process collision that must be preserved (renumbered).
            if row == by_id[rid][0]:
                continue
            by_id[rid].insert(0, row)  # repo wins the id
        else:
            by_id[rid] = [row]
    ordered = []
    next_synthetic = max(
        (r.get("id", 0) or 0) for r in vol_rows + src_rows
    ) + 1 if (vol_rows or src_rows) else 1
    for rid in sorted(by_id, key=lambda k: (k is None, k)):
        group = by_id[rid]
        ordered.append(group[0])
        for extra in group[1:]:
            extra = dict(extra)
            extra["id"] = next_synthetic
            next_synthetic += 1
            ordered.append(extra)
    watch_a = a.get("watch_triggered", {}) or {}
    watch_b = b.get("watch_triggered", {}) or {}
    watch = dict(watch_a)
    for k, v in watch_b.items():
        try:
            if float(v) > float(watch.get(k, 0)):
                watch[k] = v
        except (TypeError, ValueError):
            pass
    _write_json(dst, {"alerts": ordered,
                      "watch_triggered": watch})


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
