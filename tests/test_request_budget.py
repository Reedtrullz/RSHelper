"""Offline regressions for the shared, process-wide API request budget."""

import json
import email.utils
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import api


class _ArrivalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _ArrivalHandler)
        self.arrivals = []
        self.arrival_lock = threading.Lock()
        self.release = threading.Event()
        self.first_arrived = threading.Event()
        self.first_response_release = threading.Event()
        self.first_response_release.set()
        self.retry_after = '0'
        self.fail_first = True


class _ArrivalHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.release.wait(10)
        with self.server.arrival_lock:
            self.server.arrivals.append(time.monotonic())
            first = len(self.server.arrivals) == 1
        if first and self.server.fail_first:
            self.server.first_arrived.set()
            self.server.first_response_release.wait(10)
            self.send_response(503)
            self.send_header("Retry-After", self.server.retry_after)
            self.end_headers()
            return
        body = b'{"data":{}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def _fetch_in_child(url, barrier, home, paused=None, dispatch_gate=None):
    code = """
import os, time
from pathlib import Path
from rshelper import api
barrier = Path(os.environ['RSHELPER_BARRIER'])
deadline = time.monotonic() + 15
while not barrier.exists():
    if time.monotonic() > deadline:
        raise SystemExit(3)
    time.sleep(0.01)
api.BASE_URL = os.environ['RSHELPER_TEST_URL']
if os.environ.get('RSHELPER_DISPATCH_GATE'):
    original_wait = api._wait_for_reservation
    def hold_dispatch(slot):
        original_wait(slot)
        gate = Path(os.environ['RSHELPER_DISPATCH_GATE'])
        (gate / str(os.getpid())).touch()
        deadline = time.monotonic() + 15
        while not (gate / 'release').exists():
            if time.monotonic() > deadline: raise SystemExit(6)
            time.sleep(.01)
    api._wait_for_reservation = hold_dispatch
if os.environ.get('RSHELPER_PAUSE'):
    original_wait = api._wait_for_reservation
    def pause_dispatch(slot):
        original_wait(slot)
        marker = Path(os.environ['RSHELPER_PAUSE'])
        marker.touch()
        deadline = time.monotonic() + 15
        while not marker.with_suffix('.release').exists():
            if time.monotonic() > deadline: raise SystemExit(5)
            time.sleep(.01)
    api._wait_for_reservation = pause_dispatch
result = api._get('latest', retries=1)
raise SystemExit(0 if result == {'data': {}} else 4)
"""
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / '.config'),
        "XDG_CACHE_HOME": str(home / '.cache'),
        "RSHELPER_TEST_URL": url,
        "RSHELPER_BARRIER": str(barrier),
        'RSHELPER_PAUSE': str(paused) if paused else '',
        'RSHELPER_DISPATCH_GATE': str(dispatch_gate) if dispatch_gate else '',
        "PYTHONPATH": os.pathsep.join(filter(None, [str(Path(__file__).resolve().parents[1] / "src"),
                                        os.environ.get("PYTHONPATH", "")])),
    }
    return subprocess.Popen([sys.executable, "-c", code], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


class RequestBudgetTest(unittest.TestCase):
    def test_paused_dispatch_cannot_reuse_stale_slot(self):
        server = _ArrivalServer(); server.fail_first = False; server.release.set()
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        children = []
        try:
            with tempfile.TemporaryDirectory(prefix='request-budget-paused-') as folder:
                root = Path(folder); home = root/'home'; home.mkdir()
                go = root/'go'; go.touch(); marker = root/'paused'
                url = f'http://127.0.0.1:{server.server_port}'
                children.append(_fetch_in_child(url, go, home, marker))
                deadline = time.monotonic() + 5
                while not marker.exists():
                    self.assertLess(time.monotonic(), deadline); time.sleep(.01)
                children.append(_fetch_in_child(url, go, home))
                self.assertEqual(children[1].wait(timeout=10), 0)
                marker.with_suffix('.release').touch()
                self.assertEqual(children[0].wait(timeout=10), 0)
                arrivals = sorted(server.arrivals)
                self.assertEqual(len(arrivals), 2)
                self.assertGreaterEqual(arrivals[1]-arrivals[0], .85)
        finally:
            for child in children:
                if child.poll() is None: child.terminate(); child.wait(timeout=5)
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_legacy_timestamp_migrates_and_queue_bound_abstains(self):
        with tempfile.TemporaryDirectory(prefix='request-budget-upgrade-') as folder:
            cache = Path(folder)
            (cache / '.throttle').write_text('100')
            with mock.patch.object(api, 'CACHE_DIR', cache):
                self.assertEqual(api._reserve_request(100.0, 1.0), 101.0)
                state = json.loads((cache / '.throttle').read_text())
                self.assertEqual(state['next_at'], 102.0)
                for _ in range(118):
                    api._reserve_request(100.0, 1.0)
                before = (cache / '.throttle').read_bytes()
                with self.assertRaises(api.RequestBudgetUnavailable):
                    api._reserve_request(100.0, 1.0)
                self.assertEqual((cache / '.throttle').read_bytes(), before)

    def test_aliased_or_oversized_budget_and_lock_failure_abstain(self):
        import io
        for kind in ('stamp-alias', 'lock-alias', 'oversized', 'lock-failure', 'write-failure'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='request-budget-invalid-file-') as folder:
                root = Path(folder); cache = root / 'cache'; cache.mkdir()
                outside = root / 'outside'; outside.write_text('1')
                if kind == 'stamp-alias': (cache / '.throttle').symlink_to(outside)
                if kind == 'lock-alias': (cache / '.throttle.lock').symlink_to(outside)
                if kind == 'oversized': (cache / '.throttle').write_text('1' + ' ' * 8192)
                with mock.patch.object(api, 'CACHE_DIR', cache), \
                     mock.patch.object(api.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"data":{}}')) as fetch:
                    if kind == 'write-failure':
                        with mock.patch.object(api.os, 'replace', side_effect=OSError('fixture')):
                            result = api._get('latest', retries=0)
                    elif kind == 'lock-failure':
                        with mock.patch.object(api.fcntl, 'flock', side_effect=OSError('fixture')):
                            result = api._get('latest', retries=0)
                    else:
                        result = api._get('latest', retries=0)
                self.assertIsNone(result)
                fetch.assert_not_called()
                self.assertEqual(outside.read_text(), '1')

    def test_retry_after_defers_already_reserved_other_processes(self):
        server = _ArrivalServer()
        server.retry_after = '3'
        server.first_response_release.clear()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        children = []
        try:
            with tempfile.TemporaryDirectory(prefix='request-budget-cooldown-') as folder:
                home = Path(folder) / 'home'; home.mkdir()
                barrier = Path(folder) / 'go'
                url = f'http://127.0.0.1:{server.server_port}'
                gate = Path(folder)/'dispatch'; gate.mkdir()
                children = [_fetch_in_child(url, barrier, home, dispatch_gate=gate) for _ in range(3)]
                barrier.touch(); server.release.set()
                deadline = time.monotonic() + 5
                while len(list(gate.iterdir())) < 3:
                    self.assertLess(time.monotonic(), deadline, 'other processes did not reserve slots')
                    time.sleep(.01)
                (gate/'release').touch()
                self.assertTrue(server.first_arrived.wait(5))
                server.first_response_release.set()
                codes = [child.wait(timeout=20) for child in children]
                self.assertEqual(codes, [0, 0, 0], [child.stderr.read().decode() for child in children])
                arrivals = sorted(server.arrivals)
                self.assertEqual(len(arrivals), 4)
                self.assertGreaterEqual(arrivals[1] - arrivals[0], 2.85,
                                        'a pre-reserved process ignored shared Retry-After')
                self.assertTrue(all(b-a >= .85 for a,b in zip(arrivals[1:],arrivals[2:])))
        finally:
            server.first_response_release.set(); server.release.set()
            for child in children:
                if child.poll() is None: child.terminate(); child.wait(timeout=5)
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_lock_wait_is_not_misdiagnosed_as_clock_reversal(self):
        import io
        with tempfile.TemporaryDirectory(prefix='request-budget-lock-wait-') as folder:
            cache = Path(folder)
            clock = [100.0]
            real_flock = api.fcntl.flock
            def competing_reservation(fd, operation):
                real_flock(fd, operation)
                if operation == api.fcntl.LOCK_EX:
                    (cache / '.throttle').write_text(json.dumps({
                        'version': 1, 'last_now': 100.5, 'next_at': 100.6}))
                    clock[0] = 101.0
            with mock.patch.object(api, 'CACHE_DIR', cache), \
                 mock.patch.object(api.time, 'time', side_effect=lambda: clock[0]), \
                 mock.patch.object(api.fcntl, 'flock', side_effect=competing_reservation), \
                 mock.patch.object(api.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"data":{}}')) as upstream:
                result = api._fetch_url('http://127.0.0.1/fixture', retries=0)
            self.assertEqual(result, {'data': {}})
            upstream.assert_called_once()

    def test_multiprocess_attempt_spacing_includes_retries(self):
        """Every first attempt and retry must reserve a process-shared slot."""
        server = _ArrivalServer()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        children = []
        try:
            with tempfile.TemporaryDirectory(prefix="request-budget-") as folder:
                barrier = Path(folder) / "go"
                home = Path(folder) / "home"
                home.mkdir()
                url = f"http://127.0.0.1:{server.server_port}"
                children = [_fetch_in_child(url, barrier, home) for _ in range(3)]
                barrier.touch()
                server.release.set()
                codes = [child.wait(timeout=20) for child in children]
        finally:
            for child in children:
                if child.poll() is None: child.terminate(); child.wait(timeout=5)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(codes, [0, 0, 0], [child.stderr.read().decode() for child in children])
        arrivals = sorted(server.arrivals)
        self.assertEqual(len(arrivals), 4)
        self.assertTrue(all(later - earlier >= 0.85
                            for earlier, later in zip(arrivals, arrivals[1:])),
                        "loopback server observed attempts inside the 1-second budget")

    def test_unwritable_budget_makes_zero_upstream_attempts(self):
        server = _ArrivalServer()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        server.release.set()
        with tempfile.TemporaryDirectory(prefix="request-budget-locked-") as folder:
            blocked = Path(folder) / "not-a-directory"
            blocked.write_text("x")
            with mock.patch.object(api, "CACHE_DIR", blocked), \
                    mock.patch.object(api, "BASE_URL", f"http://127.0.0.1:{server.server_port}"):
                result = api._get("latest", retries=0)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        self.assertIsNone(result)
        self.assertEqual(server.arrivals, [], "budget failure must abstain before network I/O")

    def test_corrupt_or_nonfinite_budget_makes_zero_upstream_attempts(self):
        for value in ("not-a-timestamp", "NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                server = _ArrivalServer()
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                server.release.set()
                with tempfile.TemporaryDirectory(prefix="request-budget-corrupt-") as folder:
                    cache_dir = Path(folder)
                    cache_dir.mkdir(exist_ok=True)
                    (cache_dir / ".throttle").write_text(value)
                    with mock.patch.object(api, "CACHE_DIR", cache_dir), \
                            mock.patch.object(api, "BASE_URL", f"http://127.0.0.1:{server.server_port}"):
                        result = api._get("latest", retries=0)
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                self.assertIsNone(result)
                self.assertEqual(server.arrivals, [],
                                 "invalid shared state must fail closed before network I/O")

    def test_clock_reversal_abstains_instead_of_reserving_an_early_slot(self):
        with tempfile.TemporaryDirectory(prefix="request-budget-clock-") as folder:
            with mock.patch.object(api, "CACHE_DIR", Path(folder)):
                first = api._reserve_request(100.0, 1.0)
                self.assertEqual(first, 100.0)
                with self.assertRaises(api.RequestBudgetUnavailable):
                    api._reserve_request(99.0, 1.0)

    def test_retry_after_parsing_is_finite_and_bounded(self):
        for raw in (None, '', '-1', 'Infinity', '-Infinity',
                    email.utils.formatdate(time.time() - 10, usegmt=True)):
            self.assertEqual(api._parse_retry_after(raw), 0.0)
        self.assertEqual(api._parse_retry_after("3"), 3.0)
        self.assertEqual(api._parse_retry_after("999999999"), 60.0)
        self.assertEqual(api._parse_retry_after("NaN"), 0.0)
        self.assertEqual(api._parse_retry_after("not a date"), 0.0)
        http_date = email.utils.formatdate(time.time() + 10, usegmt=True)
        self.assertGreater(api._parse_retry_after(http_date), 0.0)
        self.assertLessEqual(api._parse_retry_after(http_date), 10.0)
        self.assertEqual(api._parse_retry_after(email.utils.formatdate(time.time()+3600, usegmt=True)), 60.0)


if __name__ == "__main__":
    unittest.main()
