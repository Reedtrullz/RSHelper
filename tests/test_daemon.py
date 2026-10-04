"""Behavioral tests for daemon ownership and stop requests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
_SOCKET_TEMP = None
if not os.environ.get("RSHELPER_DAEMON_SOCKET_ROOT"):
    _SOCKET_TEMP = tempfile.TemporaryDirectory(prefix="rsh-offline-", dir='/private/tmp' if sys.platform == 'darwin' else '/tmp')
    os.environ["RSHELPER_DAEMON_SOCKET_ROOT"] = _SOCKET_TEMP.name


def _daemon():
    try:
        import rshelper.daemon as daemon
    except ImportError:
        daemon = None
    assert daemon is not None, "daemon lease boundary has not been implemented"
    return daemon


def test_two_processes_have_one_lifetime_lease_owner():
    _daemon()  # Keep the initial red run a direct feature-missing assertion.
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        root = Path(folder)
        pid_path = root / "monitor.pid"
        state_path = root / "monitor-state.json"
        ready = root / "ready"
        start = root / "start"
        release = root / "release"
        child = r'''import json, os, sys, time
from pathlib import Path
from rshelper.daemon import acquire_lease, LeaseBusy
root = Path(sys.argv[1])
name = sys.argv[2]
(root / "ready" / name).touch()
while not (root / "start").exists():
    time.sleep(0.005)
try:
    with acquire_lease("monitor", "default", pid_path=root / "monitor.pid"):
        (root / "monitor-state.json").write_text(json.dumps({"owner": name}))
        print("OWNER " + name, flush=True)
        while not (root / "release").exists():
            time.sleep(0.01)
except LeaseBusy:
    print("BUSY " + name, flush=True)
'''
        (root / "ready").mkdir()
        env = {**os.environ, "HOME": folder,
               "XDG_CONFIG_HOME": str(root / ".config"),
               "PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"}
        children = [subprocess.Popen(
            [sys.executable, "-c", child, folder, name], env=env,
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for name in ("one", "two")]
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if all((ready / name).exists() for name in ("one", "two")):
                    break
                time.sleep(0.01)
            assert all((ready / name).exists() for name in ("one", "two")), \
                "both child processes must reach the start barrier"
            start.touch()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not state_path.exists():
                time.sleep(0.01)
            assert state_path.exists(), "the lease owner must enter the work cycle"
            owner_before_release = json.loads(state_path.read_text())["owner"]
            time.sleep(0.1)
            assert json.loads(state_path.read_text())["owner"] == owner_before_release, \
                "a failed claimant must not overwrite state while the owner holds the lease"
            release.touch()
            outputs = [proc.communicate(timeout=5) for proc in children]
            lines = [line for stdout, _stderr in outputs for line in stdout.splitlines()]
            assert sorted(line.split()[0] for line in lines) == ["BUSY", "OWNER"], lines
            assert sum(line == "OWNER " + owner_before_release for line in lines) == 1, lines
        finally:
            release.touch()
            for proc in children:
                if proc.poll() is None:
                    try:
                        proc.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.communicate(timeout=5)


def test_legacy_pid_record_never_authorizes_a_signal_or_cleanup():
    daemon = _daemon()
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        pid_path = Path(folder) / "monitor.pid"
        pid_path.write_text(str(os.getpid()))
        before = pid_path.read_bytes()
        with mock.patch.object(daemon.os, "kill", side_effect=AssertionError("must not signal PID")):
            status = daemon.daemon_status("monitor", "default", pid_path=pid_path)
            result = daemon.request_stop("monitor", "default", pid_path=pid_path)
        assert status["ownership"] == "legacy_unverified", status
        assert result["ok"] is False, result
        assert pid_path.read_bytes() == before, "unverified legacy artifacts must be preserved"


def test_reused_pid_identity_refuses_control_without_signalling():
    daemon = _daemon()
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        pid_path = Path(folder) / "monitor.pid"
        with daemon.acquire_lease("monitor", "default", pid_path=pid_path):
            with mock.patch.object(daemon, "process_identity", return_value="different-process"):
                with mock.patch.object(
                        daemon.os, "kill",
                        side_effect=AssertionError("must not signal PID")):
                    result = daemon.request_stop(
                        "monitor", "default", pid_path=pid_path, timeout=0.01)
            assert result["requested"] is False and result["stopped"] is False, result
            assert result["ownership"] == "legacy_unverified", result


def test_supervised_stop_disables_before_bootout():
    daemon = _daemon()

    class FakeSupervisor:
        def __init__(self):
            self.calls = []

        def disable(self, domain, label):
            self.calls.append(("disable", domain, label))

        def bootout(self, domain, label):
            self.calls.append(("bootout", domain, label))

    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        pid_path = Path(folder) / "trader.pid"
        supervisor = FakeSupervisor()
        with daemon.acquire_lease(
                "trader", "default", pid_path=pid_path,
                supervisor_kind="launchd", service_domain="gui/501",
                service_label="com.reidar.rshelper-trader") as lease:
            result = daemon.request_stop(
                "trader", "default", pid_path=pid_path,
                supervisor_adapter=supervisor, timeout=0.02)
            assert lease.stop_event.is_set()
            assert lease.desired_state == "disabled"
        assert supervisor.calls == [
            ("disable", "gui/501", "com.reidar.rshelper-trader"),
            ("bootout", "gui/501", "com.reidar.rshelper-trader"),
        ], supervisor.calls
        assert result["ok"] is True and result["desired_state"] == "disabled", result
        assert result["requested"] is True and result["stopped"] is False, result
        assert result["running"] is True, result


def test_interrupted_owner_releases_lease_and_preserves_lock_inode():
    daemon = _daemon()
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        pid_path = Path(folder) / "monitor.pid"
        persistent_path = daemon.lease_path(pid_path)
        try:
            with daemon.acquire_lease("monitor", "default", pid_path=pid_path):
                inode = persistent_path.stat().st_ino
                raise RuntimeError("simulated startup interruption")
        except RuntimeError as exc:
            assert str(exc) == "simulated startup interruption"
        assert persistent_path.exists(), "the flock inode must remain persistent"
        assert persistent_path.stat().st_ino == inode
        with daemon.acquire_lease("monitor", "default", pid_path=pid_path):
            pass
        assert persistent_path.stat().st_ino == inode


def test_lease_acquisition_alone_is_not_a_readiness_receipt():
    daemon = _daemon()
    from rshelper.profile import atomic_write_json
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        root = Path(folder)
        pid_path = root / "monitor.pid"
        state_path = root / "monitor-state.json"
        with daemon.acquire_lease("monitor", "default", pid_path=pid_path) as lease:
            starting = daemon.wait_for_ready(
                "monitor", "default", pid_path=pid_path, state_path=state_path,
                timeout=0.03, poll_interval=0.01)
            assert starting["ready"] is False and starting["running"] is True, starting
            atomic_write_json(state_path, {
                "daemon_instance": lease.daemon_instance,
                "ready": False,
                "startup_status": "ready", "last_check_iso": "2026-10-05T00:00:00+00:00"})
            lease.mark_ready()
            atomic_write_json(state_path, {
                "daemon_instance": lease.daemon_instance,
                "ready": True,
                "startup_status": "ready", "last_check_iso": "2026-10-05T00:00:00+00:00"})
            ready = daemon.wait_for_ready(
                "monitor", "default", pid_path=pid_path, state_path=state_path,
                timeout=0.1, poll_interval=0.01)
            assert ready["ready"] is True and ready["running"] is True, ready


def test_stop_receipt_distinguishes_acceptance_from_release():
    daemon = _daemon()
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        pid_path = Path(folder) / "monitor.pid"
        with daemon.acquire_lease("monitor", "default", pid_path=pid_path) as lease:
            result = daemon.request_stop(
                "monitor", "default", pid_path=pid_path, timeout=0.02)
            assert result["requested"] is True, result
            assert result["stopped"] is False and result["running"] is True, result
            assert result["desired_state"] == "stopped", result
            assert lease.stop_event.is_set()


def test_stop_receipt_waits_for_child_to_release_lease():
    daemon = _daemon()
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        root = Path(folder)
        pid_path = root / "monitor.pid"
        state_path = root / "monitor_state.json"
        ready_path = root / "child-ready"
        child = r'''import sys, time
from pathlib import Path
from rshelper.daemon import acquire_lease
from rshelper.profile import atomic_write_json
root = Path(sys.argv[1])
pid_path = root / "monitor.pid"
state_path = root / "monitor_state.json"
with acquire_lease("monitor", "default", pid_path=pid_path) as lease:
    state = {"daemon_instance": lease.daemon_instance, "ready": False}
    atomic_write_json(state_path, state)
    lease.mark_ready()
    state["ready"] = True
    atomic_write_json(state_path, state)
    (root / "child-ready").touch()
    while not lease.stop_event.wait(0.02):
        pass
'''
        env = {**os.environ, "HOME": folder,
               "XDG_CONFIG_HOME": str(root / ".config"),
               "PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"}
        process = subprocess.Popen(
            [sys.executable, "-c", child, folder], env=env, cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            ready = daemon.wait_for_ready(
                "monitor", "default", pid_path=pid_path, state_path=state_path,
                expected_pid=process.pid, process=process, timeout=3)
            assert ready["ready"] is True, ready
            assert ready_path.exists()
            receipt = daemon.request_stop(
                "monitor", "default", pid_path=pid_path, timeout=3)
            stderr = process.communicate(timeout=3)[1]
            assert process.returncode == 0, stderr
            assert receipt["requested"] is True, receipt
            assert receipt["stopped"] is True and receipt["running"] is False, receipt
            assert receipt["timed_out"] is False, receipt
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)


def test_launchd_disabled_state_survives_bootout_failure():
    daemon = _daemon()

    class FailingSupervisor:
        def __init__(self):
            self.calls = []

        def disable(self, domain, label):
            self.calls.append(("disable", domain, label))

        def bootout(self, domain, label):
            self.calls.append(("bootout", domain, label))
            raise OSError("fixture bootout failure")

    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        pid_path = Path(folder) / "trader.pid"
        supervisor = FailingSupervisor()
        with daemon.acquire_lease(
                "trader", "default", pid_path=pid_path,
                supervisor_kind="launchd", service_domain="gui/501",
                service_label="com.reidar.rshelper-trader"):
            result = daemon.request_stop(
                "trader", "default", pid_path=pid_path,
                supervisor_adapter=supervisor, timeout=0.02)
            assert result["desired_state"] == "disabled", result
            assert result["requested"] is True, result
            assert result["stopped"] is False and result["running"] is True, result
            assert "bootout failure" in result["error"], result
        assert [call[0] for call in supervisor.calls] == ["disable", "bootout"]


def test_long_profile_path_uses_short_private_socket_root():
    daemon = _daemon()
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        pid_path = (Path(folder) / ("profile-" + "x" * 60)
                    / ("nested-" + "y" * 60)
                    / ("config-" + "z" * 60) / "monitor.pid")
        with daemon.acquire_lease("monitor", "long-profile", pid_path=pid_path) as lease:
            assert len(os.fsencode(lease.control_path)) < 104, lease.control_path
            assert lease.control_path.parent == Path(
                os.environ["RSHELPER_DAEMON_SOCKET_ROOT"])


def test_failed_supervisor_start_disables_and_boots_out_service():
    daemon = _daemon()

    class FakeSupervisor:
        def __init__(self):
            self.calls = []

        def enable(self, domain, label):
            self.calls.append(("enable", domain, label))

        def bootstrap(self, domain, label):
            self.calls.append(("bootstrap", domain, label))

        def disable(self, domain, label):
            self.calls.append(("disable", domain, label))

        def bootout(self, domain, label):
            self.calls.append(("bootout", domain, label))

    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        root = Path(folder)
        pid_path = root / "trader.pid"
        state_path = root / "trader_state.json"
        with daemon.acquire_lease(
                "trader", "default", pid_path=pid_path,
                supervisor_kind="launchd", service_domain="gui/501",
                service_label="com.reidar.rshelper-trader") as lease:
            lease.mark_ready()
        supervisor = FakeSupervisor()
        result = daemon.start_supervised_daemon(
            "trader", "default", pid_path=pid_path, state_path=state_path,
            supervisor_adapter=supervisor, timeout=0)
        record = daemon.read_private_json(daemon.lease_path(pid_path))
        assert supervisor.calls == [
            ("enable", "gui/501", "com.reidar.rshelper-trader"),
            ("bootstrap", "gui/501", "com.reidar.rshelper-trader"),
            ("disable", "gui/501", "com.reidar.rshelper-trader"),
            ("bootout", "gui/501", "com.reidar.rshelper-trader"),
        ], supervisor.calls
        assert result["requested"] is True and result["ready"] is False, result
        assert result["desired_state"] == "disabled", result
        assert record["desired_state"] == "disabled", record

        assert result["cleanup_complete"] is True and result["ok"] is False, result


def test_failed_supervisor_cleanup_reports_disable_failure_truthfully():
    daemon = _daemon()
    class Supervisor:
        def enable(self, *args): pass
        def bootstrap(self, *args): raise OSError("bootstrap fixture failure")
        def disable(self, *args): raise OSError("disable fixture failure")
        def bootout(self, *args): pass
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        pid_path = Path(folder) / "trader.pid"
        with daemon.acquire_lease("trader", "default", pid_path=pid_path,
                supervisor_kind="launchd", service_domain="gui/501",
                service_label="com.reidar.rshelper-trader"):
            pass
        result = daemon.start_supervised_daemon("trader", pid_path=pid_path,
            state_path=Path(folder)/"state.json", supervisor_adapter=Supervisor(), timeout=0)
        assert result["ok"] is False and result["cleanup_complete"] is False, result
        assert result["desired_state"] == "enabled", result
        assert "disable fixture failure" in result["cleanup_errors"][0], result


def test_ready_supervised_start_keeps_service_enabled():
    daemon = _daemon()
    class Supervisor:
        def enable(self, *args): pass
        def bootstrap(self, *args): pass
        def disable(self, *args): raise AssertionError("ready service must stay enabled")
        def bootout(self, *args): raise AssertionError("ready service must stay loaded")
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        pid_path = Path(folder) / "trader.pid"
        with daemon.acquire_lease("trader", "default", pid_path=pid_path,
                supervisor_kind="launchd", service_domain="gui/501",
                service_label="com.reidar.rshelper-trader"):
            pass
        with mock.patch.object(daemon, "wait_for_ready", return_value={"ready":True,"running":True}):
            result = daemon.start_supervised_daemon("trader", pid_path=pid_path,
                state_path=Path(folder)/"state.json", supervisor_adapter=Supervisor())
        assert result["ok"] is True and result["desired_state"] == "enabled", result


def test_failed_start_reports_live_lease_after_owned_stop_request():
    daemon = _daemon()
    class Supervisor:
        lease = None
        def enable(self, *args): pass
        def bootstrap(self, *args):
            self.lease = daemon.acquire_lease("trader", "default", pid_path=pid_path,
                supervisor_kind="launchd", service_domain="gui/501",
                service_label="com.reidar.rshelper-trader")
            self.lease.__enter__()
        def disable(self, *args): pass
        def bootout(self, *args): pass
    with tempfile.TemporaryDirectory(prefix="rsd-") as folder:
        pid_path = Path(folder)/"trader.pid"
        with daemon.acquire_lease("trader", "default", pid_path=pid_path,
                supervisor_kind="launchd", service_domain="gui/501",
                service_label="com.reidar.rshelper-trader"):
            pass
        supervisor = Supervisor()
        try:
            result = daemon.start_supervised_daemon("trader", pid_path=pid_path,
                state_path=Path(folder)/"state.json", supervisor_adapter=supervisor, timeout=0)
            assert result["ok"] is False and result["running"] is True, result
            assert result["cleanup_complete"] is False and result["desired_state"] == "disabled", result
            assert supervisor.lease.stop_event.is_set(), result
        finally:
            if supervisor.lease: supervisor.lease.__exit__(None, None, None)


if __name__ == "__main__":
    for test in (test_two_processes_have_one_lifetime_lease_owner,
                 test_legacy_pid_record_never_authorizes_a_signal_or_cleanup,
                 test_reused_pid_identity_refuses_control_without_signalling,
                 test_supervised_stop_disables_before_bootout,
                 test_interrupted_owner_releases_lease_and_preserves_lock_inode,
                 test_lease_acquisition_alone_is_not_a_readiness_receipt,
                 test_stop_receipt_distinguishes_acceptance_from_release,
                 test_stop_receipt_waits_for_child_to_release_lease,
                 test_launchd_disabled_state_survives_bootout_failure,
                 test_long_profile_path_uses_short_private_socket_root,
                 test_failed_supervisor_start_disables_and_boots_out_service,
                 test_failed_supervisor_cleanup_reports_disable_failure_truthfully,
                 test_ready_supervised_start_keeps_service_enabled,
                 test_failed_start_reports_live_lease_after_owned_stop_request):
        test()
    print("\nAll daemon lease tests passed.")
