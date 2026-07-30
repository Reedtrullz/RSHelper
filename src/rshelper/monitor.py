"""Background monitor: polling loop with macOS notifications."""
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MONITOR_DIR = Path.home() / ".config" / "rshelper"
PID_PATH = MONITOR_DIR / "monitor.pid"
STATE_PATH = MONITOR_DIR / "monitor_state.json"


def _pid_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return PID_PATH
    return Path.home() / ".config" / "rshelper" / "profiles" / profile / "monitor.pid"


def _state_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return STATE_PATH
    return Path.home() / ".config" / "rshelper" / "profiles" / profile / "monitor_state.json"


def _monitor_dir(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return MONITOR_DIR
    return Path.home() / ".config" / "rshelper" / "profiles" / profile


def notify(title: str, message: str) -> None:
    """Fire macOS notification via osascript. No-op on failure."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}"'],
            capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass


def run_monitor(interval_sec: int = 120, no_notify: bool = False,
                profile: str | None = None) -> None:
    """Main polling loop. Blocks until KeyboardInterrupt."""
    prof_name = profile if profile else "default"
    mon_dir = _monitor_dir(profile)
    mon_dir.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    started = datetime.now(timezone.utc).isoformat()
    p_path = _pid_path(profile)
    tmp = p_path.with_suffix(".tmp")
    tmp.write_text(str(pid))
    os.replace(tmp, p_path)
    state = {"pid": pid, "started_iso": started, "last_check_iso": None, "profile": prof_name}
    _write_state(state, profile)
    print(f"[monitor] Started (PID {pid}, interval {interval_sec}s)", file=sys.stderr)
    try:
        while True:
            try:
                _poll_cycle(no_notify, profile)
                state["last_check_iso"] = datetime.now(timezone.utc).isoformat()
                _write_state(state, profile)
            except Exception as e:
                print(f"[monitor] Cycle error: {e}", file=sys.stderr)
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n[monitor] Shutting down...", file=sys.stderr)
    finally:
        _cleanup(profile)


def _poll_cycle(no_notify: bool, profile: str | None = None) -> None:
    from rshelper.cli import _fetch_bootstrap
    from rshelper.scanner import FlipScanner
    from rshelper.signals import detect_signals
    from rshelper import watchlist

    _mapping, _latest, vol_5m, items = _fetch_bootstrap(profile)
    scanner = FlipScanner(direction="arbitrage")
    flips = scanner.scan(items)
    signals = detect_signals(flips, vol_5m)
    if signals and not no_notify:
        high = [s for s in signals if s.severity == "HIGH"]
        notify("RSHelper Alert", f"{len(high)} high-severity signal(s)" if high else f"{len(signals)} signal(s)")

    watched_ids = watchlist.get_watched_ids(profile)
    if watched_ids:
        wl = watchlist.load(profile)
        for item_id_str, entry in wl["items"].items():
            price = _latest.get(item_id_str)
            if not price or not isinstance(price, dict):
                continue
            buy = int(price.get("high", 0) or 0)
            sell = int(price.get("low", 0) or 0)
            if buy <= 0 or sell <= 0:
                continue
            margin = sell - buy
            tax = min(5_000_000, max(1, int(sell * 0.02)))
            profit = margin - tax
            above, below = entry.get("alert_margin_above"), entry.get("alert_margin_below")
            if (above is not None and profit > above) or (below is not None and profit < below):
                if not no_notify:
                    notify("RSHelper Watchlist", f"{entry['name']}: margin {profit:,} gp")


def stop_monitor(profile: str | None = None) -> bool:
    p_path = _pid_path(profile)
    if not p_path.exists():
        return False
    try:
        pid = int(p_path.read_text().strip())
    except (ValueError, OSError):
        p_path.unlink(missing_ok=True)
        s_path = _state_path(profile)
        s_path.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        p_path.unlink(missing_ok=True)
        s_path = _state_path(profile)
        s_path.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        p_path.unlink(missing_ok=True)
        s_path = _state_path(profile)
        s_path.unlink(missing_ok=True)
        return True
    except OSError:
        p_path.unlink(missing_ok=True)
        s_path = _state_path(profile)
        s_path.unlink(missing_ok=True)
        return False


def monitor_status(profile: str | None = None) -> dict | None:
    p_path = _pid_path(profile)
    s_path = _state_path(profile)
    if not p_path.exists() or not s_path.exists():
        return None
    try:
        pid = int(p_path.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    try:
        state = json.loads(s_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    started = state.get("started_iso")
    uptime = 0
    if started:
        try:
            started_dt = datetime.fromisoformat(started)
            uptime = (datetime.now(timezone.utc) - started_dt).total_seconds()
        except (ValueError, TypeError):
            pass
    return {"running": True, "pid": pid, "uptime_sec": int(uptime),
            "last_check_iso": state.get("last_check_iso"),
            "profile": state.get("profile", "default")}


def _write_state(state: dict, profile: str | None = None) -> None:
    s_path = _state_path(profile)
    s_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = s_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, s_path)


def _cleanup(profile: str | None = None) -> None:
    _pid_path(profile).unlink(missing_ok=True)
    _state_path(profile).unlink(missing_ok=True)
