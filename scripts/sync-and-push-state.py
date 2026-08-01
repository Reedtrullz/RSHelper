#!/usr/bin/env bash
#!/usr/bin/env python3
"""Sync RSHelper trading state into the repo and push it (schedule agent).

Run under launchd. macOS TCC blocks bash from opening scripts inside
~/Documents, but the project's venv python already has folder access, so
this is driven by python; it shells out to git only for the actual repo
operations.
"""
import shutil
import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("RSHELPER_REPO", Path(__file__).resolve().parents[1]))
SRC = Path.home() / ".config" / "rshelper"
DEST = REPO / "data" / "state"
FILES = ["trades.json", "positions.json", "watchlist.json", "tuning_log.json",
         "volume_baseline.json", "signal_cooldowns.json", "trader_state.json"]


def _files_differ(src_dir: Path, dst_dir: Path, name: str) -> bool:
    src = src_dir / name
    if not src.exists():
        return False
    dst = dst_dir / name
    return not dst.exists() or dst.read_bytes() != src.read_bytes()


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "snapshots").mkdir(exist_ok=True)
    changed = False
    for name in FILES:
        if _files_differ(SRC, DEST, name):
            shutil.copy2(SRC / name, DEST / name)
            changed = True
    snaps = SRC / "snapshots"
    if snaps.is_dir() and any(snaps.iterdir()):
        for p in snaps.iterdir():
            dst = DEST / "snapshots" / p.name
            if not dst.exists() or dst.read_bytes() != p.read_bytes():
                shutil.copy2(p, dst)
                changed = True

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(REPO), *args],
                              capture_output=True, text=True)

    if not changed:
        print(f"[sync] no state change at {datetime.now(timezone.utc):%H:%M:%S}Z")
        return 0
    git("add", "data/state")
    git("commit", "-m", "state: sync trading history")
    push = git("push", "origin", "main")
    if push.returncode != 0:
        print(f"[sync] push failed: {push.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"[sync] pushed state update at {datetime.now(timezone.utc):%H:%M:%S}Z")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
