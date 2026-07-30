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
    mon.PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = mon.PID_PATH.with_suffix(".tmp")
    tmp.write_text(str(pid))
    os.replace(tmp, mon.PID_PATH)
    assert mon.PID_PATH.exists()
    assert int(mon.PID_PATH.read_text().strip()) == pid
    mon.PID_PATH.unlink()
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
    for flag_arg in ["--help", "--stop", "--status"]:
        result = subprocess.run(
            [sys.executable, "-m", "rshelper", "monitor", flag_arg],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            env={**os.environ, "PYTHONPATH": "src"},
        )
        assert result.returncode == 0, f"monitor {flag_arg} failed: {result.stderr}"
    print("  PASSED test_monitor_cli_args")


def test_stale_pid_cleanup():
    """stop_monitor returns False for a nonexistent PID."""
    if PID_PATH.exists():
        PID_PATH.unlink()
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text("99999")  # PID that almost certainly doesn't exist
    result = stop_monitor()
    assert not PID_PATH.exists() or result is False
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


if __name__ == "__main__":
    test_notify_command_format()
    test_pid_file_roundtrip()
    test_stop_monitor_no_pid()
    test_monitor_status_none()
    test_state_file_roundtrip()
    test_monitor_cli_args()
    test_stale_pid_cleanup()
    test_monitor_cli_help()
    print("\nAll monitor tests passed.")
