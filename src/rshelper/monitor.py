"""Background monitor: polling loop with macOS notifications."""
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from rshelper.market import ge_tax, price_issue
from rshelper.profile import atomic_write_json, resolve_config_path

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
    safe_msg = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe_msg}" with title "{safe_title}"'],
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
    # Claim the pid file with O_EXCL so a second monitor cannot silently
    # clobber a live one (mirrors the trader's single-instance guard). The
    # pid is written+fsynced while the O_EXCL fd is held so a concurrent
    # claimant never reads a partial file and unlinks a live claim.
    for _ in range(2):
        try:
            fd = os.open(p_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(str(pid))
                f.flush()
                os.fsync(f.fileno())
            break
        except FileExistsError:
            try:
                old_pid = int(p_path.read_text().strip())
                os.kill(old_pid, 0)
            except (ValueError, OSError):
                p_path.unlink(missing_ok=True)  # stale pid; retry the claim
                continue
            print(f"[monitor] Already running (PID {old_pid}); "
                  f"use --stop first.", file=sys.stderr)
            sys.exit(1)
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
    from rshelper.config import load_config
    from rshelper import watchlist

    _mapping, _latest, vol_5m, items = _fetch_bootstrap(profile)
    cfg = load_config(profile)
    scanner = FlipScanner(direction=cfg.flip.direction)
    flips = scanner.scan(items, members_only=cfg.flip.members_only,
                         min_volume=cfg.flip.min_volume,
                         min_margin=cfg.flip.min_margin)
    # DUMP/CRASH/SURGE must see the full priced universe, not just items that
    # are currently profitable flips; FLIP stays restricted to the scanned
    # candidates (they carry an RS score from the scanner).
    signals = detect_signals(items, vol_5m, flip_ids={f.id for f in flips},
                             profile=profile)
    if signals:
        try:
            from rshelper.alerts import push_alert
            for s in signals:
                push_alert("signal", s.severity, s.item_id, s.name, s.type,
                           s.message, profile=profile,
                           data={"deviation": s.deviation,
                                 "current_price": s.current_price})
        except Exception:
            pass  # alert delivery must never break a poll cycle
        if not no_notify:
            high = [s for s in signals if s.severity == "HIGH"]
            notify("RSHelper Alert", f"{len(high)} high-severity signal(s)" if high else f"{len(signals)} signal(s)")

    watched_ids = watchlist.get_watched_ids(profile)
    if watched_ids:
        wl = watchlist.load(profile)
        for item_id_str, entry in wl["items"].items():
            price = _latest.get(item_id_str)
            if not price or not isinstance(price, dict):
                continue
            issue = price_issue(price)
            if issue:
                print(f"[monitor] Skipped watchlist {entry['name']}: {issue} prices",
                      file=sys.stderr)
                continue
            buy = int(price.get("high", 0) or 0)
            sell = int(price.get("low", 0) or 0)
            margin = sell - buy
            tax = ge_tax(sell)
            profit = margin - tax
            above, below = entry.get("alert_margin_above"), entry.get("alert_margin_below")
            if (above is not None and profit > above) or (below is not None and profit < below):
                # Dedupe like the dashboard: a threshold crossing fires once
                # per 15-min window, not every poll cycle (which would spam
                # the feed + notifications every 2 minutes).
                from rshelper.alerts import push_alert, watch_triggered, set_watch_triggered
                item_id = int(item_id_str)
                if watch_triggered(item_id, profile):
                    continue
                try:
                    hit = (f"margin {profit:,} gp above {above:,}" if above is not None and profit > above
                           else f"margin {profit:,} gp below {below:,}")
                    push_alert("watch", "HIGH", item_id,
                               entry.get("name", item_id_str),
                               "Watchlist alert", f"{entry.get('name', '')}: {hit}",
                               profile=profile)
                    set_watch_triggered(item_id, profile)
                except Exception:
                    pass
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
        deadline = time.time() + 3
        exited = False
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                exited = True
                break  # process exited
            time.sleep(0.1)
        if not exited:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            time.sleep(0.2)
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
    atomic_write_json(_state_path(profile), state)


def _cleanup(profile: str | None = None) -> None:
    _pid_path(profile).unlink(missing_ok=True)
    _state_path(profile).unlink(missing_ok=True)
