"""Background monitor: polling loop with macOS notifications."""
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from rshelper.market import ge_tax, price_issue, safe_int
from rshelper.profile import atomic_write_json, resolve_config_path
from rshelper.daemon import (LeaseBusy, LeaseError, acquire_lease, daemon_status,
                             install_stop_signal, read_private_json,
                             request_stop, restore_stop_signal)

MONITOR_DIR = Path.home() / ".config" / "rshelper"
PID_PATH = MONITOR_DIR / "monitor.pid"
STATE_PATH = MONITOR_DIR / "monitor_state.json"


def _pid_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return PID_PATH
    return resolve_config_path("monitor.pid", profile)


def _state_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return STATE_PATH
    return resolve_config_path("monitor_state.json", profile)


def _monitor_dir(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return MONITOR_DIR
    return resolve_config_path("", profile)


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
    from rshelper.profile import resolve_profile
    profile = resolve_profile(profile)
    prof_name = profile if profile else "default"
    p_path = _pid_path(profile)
    try:
        with acquire_lease("monitor", prof_name, pid_path=p_path) as lease:
            state = {"pid": lease.pid,
                     "started_iso": datetime.now(timezone.utc).isoformat(),
                     "last_check_iso": None, "profile": prof_name,
                     "running": True, "daemon_instance": lease.daemon_instance,
                     "supervisor": lease.supervisor_kind,
                     "desired_state": lease.desired_state, "ready": False}
            previous_handler = None
            state_written = False
            try:
                previous_handler = install_stop_signal(lease)
                _write_state(state, profile)
                state_written = True
                lease.mark_ready()
                state["ready"] = True
                _write_state(state, profile)
                print(f"[monitor] Started (PID {lease.pid}, interval {interval_sec}s)",
                      file=sys.stderr)
                while not lease.stop_event.is_set():
                    try:
                        _poll_cycle(no_notify, profile)
                        state["last_check_iso"] = datetime.now(timezone.utc).isoformat()
                    except Exception as e:
                        print(f"[monitor] Cycle error: {e}", file=sys.stderr)
                    _write_state(state, profile)
                    lease.stop_event.wait(max(0.1, interval_sec))
            except KeyboardInterrupt:
                print("\n[monitor] Shutting down...", file=sys.stderr)
            finally:
                if state_written:
                    state["running"] = False
                    state["ready"] = False
                    state["desired_state"] = lease.desired_state
                    state["stopped_iso"] = datetime.now(timezone.utc).isoformat()
                    _write_state(state, profile)
                if previous_handler is not None:
                    restore_stop_signal(previous_handler)
    except LeaseBusy as exc:
        print(f"[monitor] Start refused: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except LeaseError as exc:
        print(f"[monitor] Startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:
        print(f"[monitor] Startup failed: {exc}", file=sys.stderr)
        raise


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
            buy = safe_int(price.get("high", 0))
            sell = safe_int(price.get("low", 0))
            # Direction-aware margin, matching `watch check --flip-direction`
            # and the CLI convention: traditional sells at the offer (high),
            # so tax applies to `buy`; arbitrage sells at the bid (low).
            if cfg.flip.direction == "traditional":
                margin = buy - sell
                tax = ge_tax(buy)
            else:
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
    return request_stop("monitor", profile, pid_path=_pid_path(profile))["ok"]


def monitor_status(profile: str | None = None) -> dict | None:
    p_path = _pid_path(profile)
    s_path = _state_path(profile)
    try:
        state = read_private_json(s_path)
    except LeaseError:
        state = None
    status = daemon_status("monitor", profile, pid_path=p_path, state=state)
    if state is None and status["ownership"] == "synced_snapshot" and not status["running"]:
        return None
    result = {**(state or {}), **status}
    started = (state or {}).get("started_iso")
    uptime = 0
    if started:
        try:
            started_dt = datetime.fromisoformat(started)
            uptime = (datetime.now(timezone.utc) - started_dt).total_seconds()
        except (ValueError, TypeError):
            pass
    result["uptime_sec"] = int(uptime)
    result["last_check_iso"] = (state or {}).get("last_check_iso")
    return result


def _write_state(state: dict, profile: str | None = None) -> None:
    atomic_write_json(_state_path(profile), state)
