"""Tests for daemon monitor."""
import sys
import os
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.monitor import notify, stop_monitor, monitor_status, PID_PATH, STATE_PATH, _write_state


def test_notify_command_format():
    notify("Test", "This is a test notification")
    print("  PASSED test_notify_command_format")


def test_pid_file_roundtrip():
    import rshelper.monitor as mon
    pid = os.getpid()
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = mon.PID_PATH.with_suffix(".tmp")
    tmp.write_text(str(pid))
    os.replace(tmp, PID_PATH)
    assert mon.PID_PATH.exists()
    assert int(mon.PID_PATH.read_text().strip()) == pid
    PID_PATH.unlink()
    print("  PASSED test_pid_file_roundtrip")


def test_stop_monitor_no_pid():
    if PID_PATH.exists():
        PID_PATH.unlink()
    assert stop_monitor() is False
    print("  PASSED test_stop_monitor_no_pid")


def test_monitor_status_none():
    if PID_PATH.exists():
        PID_PATH.unlink()
    assert monitor_status() is None
    print("  PASSED test_monitor_status_none")


def test_state_file_roundtrip():
    state = {"pid": 99999, "started_iso": "2026-01-01T00:00:00Z",
             "last_check_iso": "2026-01-01T00:01:00Z", "profile": "default"}
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_state(state)
    assert STATE_PATH.exists()
    loaded = json.loads(STATE_PATH.read_text())
    assert loaded == state
    STATE_PATH.unlink()
    print("  PASSED test_state_file_roundtrip")


def test_monitor_cli_args():
    import subprocess
    for flag_arg in ["--help", "--status"]:
        result = subprocess.run(
            [sys.executable, "-m", "rshelper", "monitor", flag_arg],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            env={**os.environ, "PYTHONPATH": "src"},
        )
        assert result.returncode == 0, f"monitor {flag_arg} failed: {result.stderr}"
    # --stop with nothing running exits 1 (new contract: scripts can detect
    # "nothing was stopped").
    result = subprocess.run(
        [sys.executable, "-m", "rshelper", "monitor", "--stop"],
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert result.returncode == 1, f"monitor --stop should exit 1, got {result.returncode}"
    print("  PASSED test_monitor_cli_args")


def test_stale_pid_cleanup():
    """stop_monitor returns False for a nonexistent PID and cleans up file."""
    if PID_PATH.exists():
        PID_PATH.unlink()
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text("99999")  # PID that almost certainly doesn't exist
    result = stop_monitor()
    # After cleanup, PID file should be gone AND result should be False
    assert not PID_PATH.exists(), "PID file should be cleaned up"
    assert result is False, "stop_monitor should return False for stale PID"
    print("  PASSED test_stale_pid_cleanup")


def test_monitor_cli_help():
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "rshelper", "monitor", "--help"],
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert result.returncode == 0
    assert "interval" in result.stdout.lower()
    print("  PASSED test_monitor_cli_help")


def test_signals_receive_full_universe():
    """DUMP/CRASH/SURGE must see the full item list, FLIP only scan ids."""
    from unittest import mock
    from rshelper.models import Item
    items = [
        Item(id=1, name="A", members=False, buy_limit=100, alch_value=0,
             buy_price=100, sell_price=90, volume=500),
        Item(id=2, name="B", members=False, buy_limit=100, alch_value=0,
             buy_price=100, sell_price=95, volume=500),
    ]
    flips = [items[0]]
    captured = {}

    def fake_detect(items_arg, vol_5m, flip_ids=None, profile=None):
        captured["items"] = items_arg
        captured["flip_ids"] = flip_ids
        return []

    class FakeScanner:
        def __init__(self, **kw):
            pass

        def scan(self, items, **kw):
            return flips

    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], {}, {}, items)), \
            mock.patch("rshelper.scanner.FlipScanner", FakeScanner), \
            mock.patch("rshelper.signals.detect_signals",
                       side_effect=fake_detect):
        from rshelper.monitor import _poll_cycle
        _poll_cycle(no_notify=True)
    assert captured.get("items") is items, \
        "signals must see the full priced universe, not just flips"
    assert captured.get("flip_ids") == {1}, \
        f"flip_ids must be the scanned candidate ids, got {captured}"
    print("  PASSED test_signals_receive_full_universe")


def test_monitor_single_instance_guard():
    """A live monitor pid must block a second instance (O_EXCL claim)."""
    import os
    import sys
    import tempfile
    from pathlib import Path
    from unittest import mock
    import rshelper.monitor as mon
    tmp = Path(tempfile.mkdtemp())
    old_pid, old_state = mon.PID_PATH, mon.STATE_PATH
    mon.PID_PATH = tmp / "monitor.pid"
    mon.STATE_PATH = tmp / "monitor_state.json"
    try:
        mon.PID_PATH.write_text(str(os.getpid()))  # live pid
        try:
            with mock.patch.object(mon, "_poll_cycle", return_value=None):
                mon.run_monitor(interval_sec=1)
            assert False, "expected SystemExit for a live second instance"
        except SystemExit:
            pass
        assert mon.PID_PATH.read_text().strip() == str(os.getpid()), \
            "the live instance's pid file must not be clobbered"
        # a stale pid is replaced and the monitor runs until interrupted
        mon.PID_PATH.write_text("99999999")
        with mock.patch.object(mon, "_poll_cycle", side_effect=KeyboardInterrupt):
            mon.run_monitor(interval_sec=1)
        assert not mon.PID_PATH.exists(), "cleanup must remove the pid file"
    finally:
        mon.PID_PATH, mon.STATE_PATH = old_pid, old_state
    print("  PASSED test_monitor_single_instance_guard")


if __name__ == "__main__":
    test_notify_command_format()
    test_pid_file_roundtrip()
    test_stop_monitor_no_pid()
    test_monitor_status_none()
    test_state_file_roundtrip()
    test_monitor_cli_args()
    test_stale_pid_cleanup()
    test_monitor_cli_help()
    test_signals_receive_full_universe()
    test_monitor_single_instance_guard()
    print("\nAll monitor tests passed.")
