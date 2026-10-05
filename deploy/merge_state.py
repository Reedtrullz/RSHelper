#!/usr/bin/env python3
"""Validate all staged/live state, then atomically merge staged state."""

import argparse
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

LIST_FILES = {"trades.json": ("trades", "id"), "alerts.json": ("alerts", "id")}
DICT_FILES = {"watchlist.json": "items"}
REPLACE_FILES = {"positions.json"}


def _validation_module(path=None):
    if path is None:
        # The API form is used by local tests; the standalone CLI requires the
        # explicit deployment copy and never falls back to this import.
        from rshelper import persistence
        return persistence
    module_path = Path(path)
    if module_path.is_symlink() or not module_path.is_file():
        raise ValueError("validation module must be a regular file")
    spec = importlib.util.spec_from_file_location("rshelper_deploy_persistence", module_path)
    if spec is None or spec.loader is None:
        raise ValueError("unable to load validation module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = ("StateCorruptionError", "read_state", "validate_state", "validate_writable_state", "locked_state")
    if any(not hasattr(module, name) for name in required):
        raise ValueError("validation module does not implement the state contract")
    return module


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _entries(root: Path) -> dict[str, Path]:
    """Enumerate regular files and directories while containing symlinks."""
    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise ValueError(f"state root is not a directory: {root}")
    found = {}
    pending = [(root, "")]
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as scan:
            children = sorted(scan, key=lambda entry: entry.name)
        for entry in children:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            candidate = Path(entry.path)
            target = candidate.resolve(strict=True)
            if not _inside(target, resolved_root):
                raise ValueError(f"state path escapes its root: {relative}")
            mode = target.stat().st_mode
            if stat.S_ISDIR(mode):
                if candidate.is_symlink():
                    raise ValueError(f"directory symlinks are not supported: {relative}")
                pending.append((candidate, relative))
            elif stat.S_ISREG(mode):
                found[relative] = candidate
            else:
                raise ValueError(f"state path is not a regular file: {relative}")
    return found


def _kind(relative: str) -> str | None:
    name = Path(relative).name
    if name == "watchlist.json":
        return "watchlist"
    if name in LIST_FILES:
        return LIST_FILES[name][0]
    if name in REPLACE_FILES:
        return "positions"
    if name.endswith(".json"):
        return "generic"
    return None


def _preflight(entries: dict[str, Path], validation) -> dict[str, dict]:
    parsed = {}
    for relative, path in entries.items():
        kind = _kind(relative)
        if kind is not None:
            parsed[relative] = validation.read_state(path.resolve(strict=True), kind)
    return parsed


def _merge_list(volume_rows: list[dict], stage_rows: list[dict], id_key: str) -> list[dict]:
    """Keep repo precedence and preserve different rows with colliding ids."""
    by_id = {}
    for row in volume_rows:
        by_id.setdefault(row[id_key], []).append(row)
    for row in stage_rows:
        rid = row[id_key]
        if rid in by_id:
            if row == by_id[rid][0]:
                continue
            by_id[rid].insert(0, row)
        else:
            by_id[rid] = [row]
    next_synthetic = max((row[id_key] for row in volume_rows + stage_rows), default=0) + 1
    merged = []
    for rid in sorted(by_id):
        group = by_id[rid]
        merged.append(group[0])
        for extra in group[1:]:
            clone = dict(extra)
            clone[id_key] = next_synthetic
            next_synthetic += 1
            merged.append(clone)
    return merged


def _merged_json(relative: str, stage_data: dict, volume_data: dict | None) -> dict:
    existing = volume_data or {}
    merged = {**existing, **stage_data}
    if relative.endswith("/alerts.json") or relative == "alerts.json":
        merged["alerts"] = _merge_list(existing.get("alerts", []), stage_data["alerts"], "id")
        triggered = dict(existing.get("watch_triggered", {}))
        for key, value in stage_data.get("watch_triggered", {}).items():
            triggered[key] = max(value, triggered.get(key, value))
        merged["watch_triggered"] = triggered
    elif Path(relative).name in LIST_FILES:
        key, id_key = LIST_FILES[Path(relative).name]
        merged[key] = _merge_list(existing.get(key, []), stage_data[key], id_key)
    elif Path(relative).name in REPLACE_FILES:
        merged["positions"] = stage_data["positions"]
    elif Path(relative).name in DICT_FILES:
        key = DICT_FILES[Path(relative).name]
        merged[key] = {**existing.get(key, {}), **stage_data[key]}
    return merged


def _atomic_bytes(path: Path, content: bytes, mode: int | None, chown: tuple[int, int] | None):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, stat.S_IMODE(mode))
        if chown is not None:
            os.chown(temporary, *chown)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _mode(path: Path) -> int | None:
    try:
        return path.stat().st_mode
    except FileNotFoundError:
        return None


def merge_dir(stage: str, volume: str, chown: str | None,
              validation_module=None) -> None:
    validation = _validation_module(validation_module)
    stage_root = Path(stage)
    volume_root = Path(volume)
    if not stage_root.is_dir():
        raise ValueError(f"stage dir {stage} does not exist")
    if stage_root.is_symlink() or volume_root.is_symlink():
        raise ValueError("state roots cannot be symlinks")
    staged = _entries(stage_root)
    live_exists = volume_root.exists()
    live = _entries(volume_root) if live_exists else {}
    staged_data = _preflight(staged, validation)
    live_data = _preflight(live, validation)
    owner = None
    if chown is not None:
        try:
            uid_text, gid_text = chown.split(":", 1)
            owner = (int(uid_text), int(gid_text))
            if min(owner) < 0:
                raise ValueError
        except ValueError as exc:
            raise ValueError("--chown must be UID:GID") from exc

    # Lock every JSON state file from both trees in the same canonical order.
    # Acquiring and validating completes before any destination write occurs.
    lock_paths = set()
    for entries in (staged, live):
        for relative, path in entries.items():
            if _kind(relative) is not None:
                lock_paths.add(path.resolve())
    for relative in staged:
        if _kind(relative) is not None:
            lock_paths.add((volume_root / relative).resolve())
    with ExitStack() as locks:
        for path in sorted(lock_paths, key=str):
            locks.enter_context(validation.locked_state(path))
            if owner is not None:
                os.chown(str(path) + ".lock", *owner)
        # Re-read after locking so a writer that completed while locks were
        # being acquired cannot be lost, and still fail before any merge write.
        staged_data = _preflight(staged, validation)
        live = _entries(volume_root) if volume_root.exists() else {}
        live_data = _preflight(live, validation)
        for sources in (staged_data, live_data):
            for relative, data in sources.items():
                validation.validate_writable_state(data, _kind(relative), relative)
        planned = []
        for relative in sorted(staged):
            src = staged[relative]
            dst = volume_root / relative
            write_dst = dst.resolve(strict=False)
            if not _inside(write_dst, volume_root.resolve()):
                raise ValueError(f"destination escapes its root: {relative}")
            kind = _kind(relative)
            if kind is None:
                planned.append((write_dst, src.read_bytes(), _mode(write_dst) or _mode(src)))
                continue
            output = _merged_json(relative, staged_data[relative], live_data.get(relative))
            # Validate and serialize every final union before any destination
            # directory or file is changed, so a late invalid union cannot
            # leave earlier state files replaced.
            validation.validate_state(output, kind, write_dst)
            payload = (json.dumps(output, ensure_ascii=False, allow_nan=False,
                                  separators=(",", ":")) + "\n").encode("utf-8")
            planned.append((write_dst, payload, _mode(write_dst) or _mode(src)))
        for write_dst, _, _ in planned:
            write_dst.parent.mkdir(parents=True, exist_ok=True)
        for write_dst, payload, mode in planned:
            _atomic_bytes(write_dst, payload, mode, owner)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage")
    parser.add_argument("volume")
    parser.add_argument("--chown", metavar="UID:GID")
    parser.add_argument("--validation-module", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code
    try:
        merge_dir(args.stage, args.volume, args.chown, args.validation_module)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
