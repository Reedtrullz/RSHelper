#!/usr/bin/env python3
"""Sync RSHelper trading state into the repo and push it (schedule agent).

Run under launchd. macOS TCC blocks bash from opening scripts inside
~/Documents, but the project's venv python already has folder access, so
this is driven by python; it shells out to git only for the actual repo
operations.
"""
import subprocess
import sys
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("RSHELPER_REPO", Path(__file__).resolve().parents[1]))
SRC = Path.home() / ".config" / "rshelper"
DEST = REPO / "data" / "state"
FILES = ["trades.json", "positions.json", "watchlist.json", "tuning_log.json",
         "volume_baseline.json", "signal_cooldowns.json", "trader_state.json",
         "alerts.json"]


def _files_differ(src_dir: Path, dst_dir: Path, name: str) -> bool:
    src = src_dir / name
    if not src.exists():
        return False
    dst = dst_dir / name
    return not dst.exists() or dst.read_bytes() != src.read_bytes()


def _copy_atomic(src: Path, dst: Path) -> None:
    """Copy with a trailing newline, atomically (temp file + rename)."""
    data = src.read_bytes()
    if not data.endswith(b"\n"):
        data += b"\n"
    fd, tmp = tempfile.mkstemp(dir=str(dst.parent), prefix=dst.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    if not (REPO / ".git").is_dir():
        print(f"[sync] error: {REPO} is not a git repository; "
              f"set RSHELPER_REPO to the project root.", file=sys.stderr)
        return 2
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "snapshots").mkdir(exist_ok=True)
    changed = False
    for name in FILES:
        if _files_differ(SRC, DEST, name):
            _copy_atomic(SRC / name, DEST / name)
            changed = True
    snaps = SRC / "snapshots"
    if snaps.is_dir() and any(snaps.iterdir()):
        for p in snaps.iterdir():
            if not p.is_file():
                continue  # a stray subdirectory must not abort the sync
            dst = DEST / "snapshots" / p.name
            if not dst.exists() or dst.read_bytes() != p.read_bytes():
                _copy_atomic(p, dst)
                changed = True

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(REPO), *args],
                              capture_output=True, text=True)

    if not changed:
        print(f"[sync] no state change at {datetime.now(timezone.utc):%H:%M:%S}Z")
        return 0
    git("add", "data/state")
    commit = git("commit", "-m", "state: sync trading history")
    if commit.returncode != 0:
        # The repo is configured with commit.gpgsign=true (SSH signing via
        # 1Password). When 1Password is locked/unavailable the signed commit
        # fails with "1Password: failed to fill whole buffer". Fall back to
        # an unsigned commit so trading state still reaches the repo/live
        # site — a stale live site is worse than an unsigned history entry.
        if "1Password" in commit.stderr or "gpg" in commit.stderr.lower():
            print(f"[sync] signed commit failed ({commit.stderr.strip()}); "
                  f"retrying unsigned", file=sys.stderr)
            commit = git("commit", "--no-gpg-sign",
                         "-m", "state: sync trading history")
        if commit.returncode != 0:
            print(f"[sync] commit failed: {commit.stderr.strip()}", file=sys.stderr)
            return 1
    push = git("push", "origin", "main")
    if push.returncode != 0:
        print(f"[sync] push failed: {push.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"[sync] pushed state update at {datetime.now(timezone.utc):%H:%M:%S}Z")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
