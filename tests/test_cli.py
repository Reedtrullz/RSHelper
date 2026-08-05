"""E2E CLI tests: subprocess invocations of rshelper commands."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

RSHELPER = [sys.executable, "-m", "rshelper"]
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
ENV = {**os.environ, "PYTHONPATH": os.path.join(_TEST_DIR, "..", "src")}
CWD = os.path.join(_TEST_DIR, "..")


def run(*args):
    return subprocess.run(
        RSHELPER + list(args),
        capture_output=True, text=True, env=ENV, cwd=CWD, timeout=30,
    )


class TestCLI(unittest.TestCase):

    def test_help(self):
        r = run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage:", r.stdout.lower())
        self.assertNotIn("Traceback", r.stderr)

    def test_config_path(self):
        r = run("config", "path")
        self.assertEqual(r.returncode, 0)
        path = r.stdout.strip()
        self.assertTrue(path.endswith("config.toml"), f"Got: {path}")

    def test_config_show(self):
        r = run("config", "show")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIn("alch", data)
        self.assertIn("flip", data)
        self.assertIn("margin", data)

    def test_config_no_subcommand_shows_help(self):
        r = run("config")
        self.assertNotEqual(r.returncode, 0)

    def test_unknown_command(self):
        r = run("nonexistent")
        self.assertNotEqual(r.returncode, 0)

    def test_item_info_nonexistent(self):
        r = run("item-info", "zzzz_nonexistent_zzzz")
        self.assertNotEqual(r.returncode, 0)

    def test_alch_scan_no_crash(self):
        r = run("alch-scan", "--top", "1", "--json")
        # May fail without network, but shouldn't traceback
        self.assertNotIn("Traceback", r.stderr)

    def test_flip_scan_help(self):
        r = run("flip-scan", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--ge-slots", r.stdout)

    def test_version_flag(self):
        r = run("--version")
        self.assertEqual(r.returncode, 0)
        sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        from rshelper import __version__
        self.assertIn(f"rshelper {__version__}", r.stdout)

    def test_members_boolean_optional(self):
        r = run("flip-scan", "--help")
        self.assertIn("--no-members-only", r.stdout)

    def test_margin_check_help(self):
        r = run("margin-check", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--ge-slots", r.stdout)

    def test_dashboard_help(self):
        r = run("dashboard", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--port", r.stdout)
        self.assertIn("--bind", r.stdout)

    def test_flip_table_roi_column(self):
        sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        from rshelper.models import Item
        from rshelper.cli import _format_flip_table
        items = [
            Item(id=1, name="Cheap flip", members=False, buy_limit=1000,
                 alch_value=0, buy_price=100, sell_price=150, volume=500,
                 profit=47, gp_per_hour=10000, rs_score=80),
            Item(id=2, name="Expensive flip", members=False, buy_limit=10,
                 alch_value=0, buy_price=100_000, sell_price=120_000, volume=50,
                 profit=19_600, gp_per_hour=5000, rs_score=50),
        ]
        out = _format_flip_table(items, top=10)
        self.assertIn("ROI", out)
        self.assertIn("47.0", out)   # 47/100 = 47.0%
        self.assertIn("19.6", out)   # 19600/100000 = 19.6%

    def test_config_members_only_honored(self):
        import tempfile
        from pathlib import Path
        sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        import rshelper.profile as pmod
        import rshelper.config as cmod
        tmp = tempfile.TemporaryDirectory()
        pmod.CONFIG_DIR = Path(tmp.name) / "config"
        pmod.CACHE_DIR = Path(tmp.name) / "cache"
        prof_dir = pmod.CONFIG_DIR / "profiles" / "main"
        prof_dir.mkdir(parents=True)
        (prof_dir / "config.toml").write_text("[flip]\nmembers_only = true\n")
        cfg = cmod.load_config("main")
        self.assertTrue(cfg.flip.members_only)

    def test_config_min_volume_default_ten(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        import rshelper.profile as pmod
        import rshelper.config as cmod
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pmod, "CONFIG_DIR", Path(tmp) / "config"), \
                 mock.patch.object(pmod, "CACHE_DIR", Path(tmp) / "cache"):
                prof_dir = pmod.CONFIG_DIR / "profiles" / "main"
                prof_dir.mkdir(parents=True)
                (prof_dir / "config.toml").write_text("[flip]\ndirection = \"arbitrage\"\n")
                cfg = cmod.load_config("main")
        self.assertEqual(cfg.flip.min_volume, 10)
        self.assertEqual(cfg.margin.min_volume, 10)

    def test_trade_paper_uses_live_prices(self):
        from pathlib import Path
        from unittest import mock
        from argparse import Namespace
        import tempfile
        sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        import rshelper.api as amod
        import rshelper.journal as jmod
        import rshelper.cli as cmod
        original_path = jmod.TRADES_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            try:
                with mock.patch.object(amod, "fetch_mapping", return_value=[
                        {"id": 1, "name": "Nature rune", "limit": 13000}]):
                    with mock.patch.object(amod, "fetch_latest", return_value={
                            "1": {"high": 150, "low": 140,
                                  "highTime": int(time.time()) - 60,
                                  "lowTime": int(time.time()) - 60}}):
                        cmod._trade_paper(Namespace(
                            item="nature rune", qty=100, capital=0, note="",
                            profile=None, flip_direction="arbitrage"))
                trades = jmod.list_trades()
            finally:
                jmod.TRADES_PATH = original_path
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual(t.name, "Nature rune")
        self.assertEqual(t.qty, 100)
        self.assertEqual(t.buy_price, 150)
        self.assertEqual(t.sell_price, 140)
        self.assertEqual(t.note, "paper")

    def test_trade_paper_sizes_from_capital(self):
        from pathlib import Path
        from unittest import mock
        from argparse import Namespace
        import tempfile
        sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        import rshelper.api as amod
        import rshelper.journal as jmod
        import rshelper.cli as cmod
        original_path = jmod.TRADES_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            try:
                with mock.patch.object(amod, "fetch_mapping", return_value=[
                        {"id": 1, "name": "Nature rune", "limit": 13000}]):
                    with mock.patch.object(amod, "fetch_latest", return_value={
                            "1": {"high": 150, "low": 140,
                                  "highTime": int(time.time()) - 60,
                                  "lowTime": int(time.time()) - 60}}):
                        cmod._trade_paper(Namespace(
                            item="nature rune", qty=0, capital=3000, note="",
                            profile=None, flip_direction="arbitrage"))
                trades = jmod.list_trades()
            finally:
                jmod.TRADES_PATH = original_path
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].qty, 20)  # 3000 // 150, capped by limit

    def test_trade_paper_traditional_direction(self):
        from pathlib import Path
        from unittest import mock
        from argparse import Namespace
        import tempfile
        sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        import rshelper.api as amod
        import rshelper.journal as jmod
        import rshelper.cli as cmod
        original_path = jmod.TRADES_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            try:
                with mock.patch.object(amod, "fetch_mapping", return_value=[
                        {"id": 1, "name": "Nature rune", "limit": 13000}]):
                    with mock.patch.object(amod, "fetch_latest", return_value={
                            "1": {"high": 150, "low": 140,
                                  "highTime": int(time.time()) - 60,
                                  "lowTime": int(time.time()) - 60}}):
                        cmod._trade_paper(Namespace(
                            item="nature rune", qty=10, capital=0, note="",
                            profile=None, flip_direction="traditional"))
                t = jmod.list_trades()[0]
            finally:
                jmod.TRADES_PATH = original_path
        self.assertEqual(t.buy_price, 140)  # bid
        self.assertEqual(t.sell_price, 150)  # offer

    def test_trade_paper_insufficient_capital(self):
        from pathlib import Path
        from unittest import mock
        from argparse import Namespace
        import tempfile
        sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        import rshelper.api as amod
        import rshelper.journal as jmod
        import rshelper.cli as cmod
        original_path = jmod.TRADES_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            try:
                with mock.patch.object(amod, "fetch_mapping", return_value=[
                        {"id": 1, "name": "Nature rune", "limit": 13000}]):
                    with mock.patch.object(amod, "fetch_latest", return_value={
                            "1": {"high": 150, "low": 140,
                                  "highTime": int(time.time()) - 60,
                                  "lowTime": int(time.time()) - 60}}):
                        with self.assertRaises(SystemExit):
                            cmod._trade_paper(Namespace(
                                item="nature rune", qty=0, capital=100,
                                note="", profile=None,
                                flip_direction="arbitrage"))
                self.assertEqual(jmod.list_trades(), [])
            finally:
                jmod.TRADES_PATH = original_path

    def test_trade_open_close_positions(self):
        from pathlib import Path
        from unittest import mock
        from argparse import Namespace
        import tempfile
        sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        import rshelper.api as amod
        import rshelper.journal as jmod
        import rshelper.positions as pmod
        import rshelper.cli as cmod
        original_path = jmod.TRADES_PATH
        original_pos = pmod.POSITIONS_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            pmod.POSITIONS_PATH = Path(tmp) / "positions.json"
            try:
                with mock.patch.object(amod, "fetch_mapping", return_value=[
                        {"id": 561, "name": "Nature rune", "limit": 13000}]):
                    with mock.patch.object(amod, "fetch_latest", return_value={
                            "561": {"high": 150, "low": 140,
                                    "highTime": int(time.time()) - 60,
                                    "lowTime": int(time.time()) - 60}}):
                        cmod._trade_open(Namespace(
                            item="nature rune", qty=10, capital=0, note="",
                            profile=None, flip_direction="arbitrage"))
                        self.assertEqual(len(pmod.list_positions()), 1)
                        cmod._trade_close(Namespace(
                            item="nature rune", qty=0, profile=None))
                trades = jmod.list_trades()
                positions_after = pmod.list_positions()
            finally:
                jmod.TRADES_PATH = original_path
                pmod.POSITIONS_PATH = original_pos
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].qty, 10)
        self.assertEqual(trades[0].buy_price, 150)  # arbitrage: buy at high
        self.assertEqual(trades[0].sell_price, 140)
        self.assertEqual(trades[0].note, "paper")
        self.assertEqual(positions_after, [])

    def test_trade_positions_json_round_trip(self):
        from pathlib import Path
        from unittest import mock
        from argparse import Namespace
        import tempfile
        sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        import rshelper.api as amod
        import rshelper.positions as pmod
        import rshelper.cli as cmod
        original_pos = pmod.POSITIONS_PATH
        with tempfile.TemporaryDirectory() as tmp:
            pmod.POSITIONS_PATH = Path(tmp) / "positions.json"
            try:
                pmod.open_position(561, "Nature rune", 5, 100,
                                   direction="arbitrage")
                with mock.patch.object(amod, "fetch_latest", return_value={
                        "561": {"high": 150, "low": 140,
                                "highTime": int(time.time()) - 60,
                                "lowTime": int(time.time()) - 60}}):
                    rows = cmod._trade_positions(Namespace(profile=None, json=True))
            finally:
                pmod.POSITIONS_PATH = original_pos
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qty"], 5)
        self.assertEqual(rows[0]["current"], 140)
        # (140-100)*5 - ge_tax(140)=2 per item
        self.assertEqual(rows[0]["unrealized"], 190)

    def test_auto_trade_status(self):
        r = run("auto-trade", "--status")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Trader:", r.stdout)
        # Status must be truthful: running (local or synced) or explicitly not.
        self.assertTrue("running" in r.stdout or "not running" in r.stdout)

    def test_trade_pnl_by_item_json(self):
        r = run("trade", "pnl", "--by-item", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)  # real ledger; may be []
        self.assertIsInstance(data, list)

    def test_process_scan_json(self):
        """process-scan --json outputs a JSON list (stdout = data only)."""
        import sys as _sys
        from unittest import mock
        import tempfile
        from pathlib import Path
        _sys.path.insert(0, os.path.join(_TEST_DIR, "..", "src"))
        import rshelper.api as amod
        import rshelper.cli as cmod
        from argparse import Namespace
        import contextlib
        import io
        # Isolate the cache so the mock fetch is actually used (a warm cache
        # would short-circuit the mocks with real data).
        import rshelper.api as _api_mod
        orig_cache_path = _api_mod._cache_path
        tmpdir_ref = {}
        with tempfile.TemporaryDirectory() as tmp:
            def _fake_cache_path(name, profile=None):
                return Path(tmp) / (name + ".json")
            _api_mod._cache_path = _fake_cache_path
            try:
                now = int(time.time())
                mapping = [
                    {"id": 2353, "name": "Steel bar", "limit": 10000},
                    {"id": 440, "name": "Iron ore", "limit": 10000},
                    {"id": 453, "name": "Coal", "limit": 10000},
                ]
                latest = {
                    "2353": {"high": 400, "low": 576, "highTime": now - 60, "lowTime": now - 60},
                    "440": {"high": 100, "low": 90, "highTime": now - 60, "lowTime": now - 60},
                    "453": {"high": 130, "low": 120, "highTime": now - 60, "lowTime": now - 60},
                }
                vol = {
                    "2353": {"avgHighPrice": 400, "avgLowPrice": 576,
                             "highPriceVolume": 5000, "lowPriceVolume": 5000},
                    "440": {"avgHighPrice": 100, "avgLowPrice": 90,
                            "highPriceVolume": 5000, "lowPriceVolume": 5000},
                    "453": {"avgHighPrice": 130, "avgLowPrice": 120,
                            "highPriceVolume": 5000, "lowPriceVolume": 5000},
                }
                with mock.patch.object(cmod, "fetch_mapping", return_value=mapping), \
                     mock.patch.object(cmod, "fetch_latest", return_value=latest), \
                     mock.patch.object(cmod, "fetch_5m", return_value=vol), \
                     contextlib.redirect_stdout(io.StringIO()) as out:
                    cmod.process_scan(Namespace(profile=None, members_only=False,
                                                min_volume=0, min_profit=0,
                                                capital=0, top=10, name="",
                                                json=True, csv=False, html=False,
                                                save_snapshot=False))
            finally:
                _api_mod._cache_path = orig_cache_path
        data = json.loads(out.getvalue())
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertEqual(data[0]["name"], "Steel bar")
        self.assertIn("gp_per_hour", data[0])
        self.assertIn("input_cost", data[0])

    def test_watch_check_json_stdout_pure(self):
        """watch check --json must emit ONLY JSON on stdout (no human lines)."""
        import rshelper.api as amod
        import rshelper.watchlist as wl
        from pathlib import Path
        from argparse import Namespace
        from unittest import mock
        import rshelper.cli as cmod
        original_path = wl.WATCHLIST_PATH
        with tempfile.TemporaryDirectory() as tmp:
            wl.WATCHLIST_PATH = Path(tmp) / "watchlist.json"
            try:
                wl.add(561, "Nature rune", alert_margin_above=50)
                now = int(time.time())
                with mock.patch.object(amod, "fetch_latest", return_value={
                        "561": {"high": 100, "low": 200,
                                "highTime": now - 60, "lowTime": now - 60}}), \
                     contextlib.redirect_stdout(io.StringIO()) as out, \
                     contextlib.redirect_stderr(io.StringIO()) as err:
                    with self.assertRaises(SystemExit) as ctx:
                        cmod.watch_check(Namespace(profile=None,
                                                   flip_direction="arbitrage",
                                                   ge_slots=2, verbose=False,
                                                   json=True))
                self.assertEqual(ctx.exception.code, 1)
                data = json.loads(out.getvalue())
                self.assertIsInstance(data, list)
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["name"], "Nature rune")
                self.assertIn("Fetching latest prices", err.getvalue())
            finally:
                wl.WATCHLIST_PATH = original_path

    def test_watch_check_json_empty(self):
        """Empty watchlist + --json emits a JSON object, not prose."""
        import contextlib
        import io
        import rshelper.watchlist as wl
        from pathlib import Path
        from argparse import Namespace
        import rshelper.cli as cmod
        original_path = wl.WATCHLIST_PATH
        with tempfile.TemporaryDirectory() as tmp:
            wl.WATCHLIST_PATH = Path(tmp) / "watchlist.json"
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    cmod.watch_check(Namespace(profile=None,
                                               flip_direction="arbitrage",
                                               ge_slots=2, verbose=False,
                                               json=True))
                data = json.loads(out.getvalue())
                self.assertEqual(data, {"alerts": [], "count": 0})
            finally:
                wl.WATCHLIST_PATH = original_path

    def test_signals_human_mode_does_not_crash_on_flip(self):
        """`signals` human path must not NameError when a FLIP signal exists."""
        from unittest import mock
        import rshelper.signals as sigmod
        from rshelper.signals import Signal
        from rshelper.models import Item
        from argparse import Namespace
        import rshelper.cli as cmod
        fake = [Signal(type="FLIP", item_id=561, name="Nature rune",
                       severity="HIGH", current_price=100, deviation=7.5,
                       message="Nature rune: 7.5% spread")]
        # Patch the bootstrap + signal detection so no network is touched.
        items = [Item(id=561, name="Nature rune", members=False, buy_limit=10000,
                      alch_value=0, buy_price=100, sell_price=92, volume=600,
                      profit=7, rs_score=80)]
        cmod._fetch_bootstrap = lambda p=None: (
            [{"id": 561, "name": "Nature rune"}],
            {"561": {"high": 100, "low": 92, "highTime": 1, "lowTime": 1}},
            {"561": {"avgHighPrice": 100, "avgLowPrice": 92,
                     "highPriceVolume": 600, "lowPriceVolume": 600}},
            items)
        with mock.patch.object(sigmod, "detect_signals", return_value=fake):
            cmod.signals_cmd(Namespace(profile=None, monitor=0,
                                       flip_direction="arbitrage",
                                       members_only=False, cooldown=15,
                                       json=False))

    def test_signals_monitor_ignores_json_documented(self):
        """signals --monitor prints [signal] lines; --json is not honored there."""
        import contextlib
        import io
        from unittest import mock
        from argparse import Namespace
        import rshelper.signals as sigmod
        from rshelper.signals import Signal
        from rshelper.models import Item
        import rshelper.cli as cmod
        fake = [Signal(type="DUMP", item_id=561, name="Nature rune",
                       severity="MEDIUM", current_price=100, deviation=-12.0,
                       message="Nature rune: -12.0% vs 5m avg")]
        items = [Item(id=561, name="Nature rune", members=False, buy_limit=10000,
                      alch_value=0, buy_price=100, sell_price=92, volume=600)]
        cmod._fetch_bootstrap = lambda p=None: (
            [{"id": 561, "name": "Nature rune"}],
            {"561": {"high": 100, "low": 92, "highTime": 1, "lowTime": 1}},
            {"561": {"avgHighPrice": 100, "avgLowPrice": 92,
                     "highPriceVolume": 600, "lowPriceVolume": 600}},
            items)
        with mock.patch.object(sigmod, "detect_signals", return_value=fake), \
             mock.patch("time.sleep", side_effect=KeyboardInterrupt):
            # signals_cmd catches KeyboardInterrupt and returns cleanly.
            cmod.signals_cmd(Namespace(profile=None, monitor=1,
                                       flip_direction="arbitrage",
                                       members_only=False, cooldown=15,
                                       json=True))

    def test_trade_close_refuses_auto_lots(self):
        """`trade close` must refuse lots the auto-trader owns."""
        from pathlib import Path
        from unittest import mock
        from argparse import Namespace
        import tempfile
        import rshelper.api as amod
        import rshelper.positions as pmod
        import rshelper.cli as cmod
        original_pos = pmod.POSITIONS_PATH
        with tempfile.TemporaryDirectory() as tmp:
            pmod.POSITIONS_PATH = Path(tmp) / "positions.json"
            try:
                pmod.open_position(561, "Nature rune", 5, 100,
                                   direction="arbitrage", note="auto")
                with mock.patch.object(amod, "fetch_mapping", return_value=[
                        {"id": 561, "name": "Nature rune", "limit": 13000}]):
                    with mock.patch.object(amod, "fetch_latest", return_value={
                            "561": {"high": 150, "low": 140,
                                    "highTime": int(time.time()) - 60,
                                    "lowTime": int(time.time()) - 60}}):
                        with self.assertRaises(SystemExit):
                            cmod._trade_close(Namespace(
                                item="nature rune", qty=0, profile=None))
                self.assertEqual(len(pmod.list_positions()), 1)  # untouched
            finally:
                pmod.POSITIONS_PATH = original_pos

    def test_item_info_json_timeseries_single_doc(self):
        """item-info --json --timeseries must emit ONE JSON document on stdout."""
        from pathlib import Path
        from unittest import mock
        from argparse import Namespace
        import rshelper.api as amod
        import rshelper.cli as cmod
        now = int(time.time())
        ts_data = [
            {"timestamp": now - (60 * (10 - i)), "avgHighPrice": 100 + i,
             "avgLowPrice": 90 + i, "highPriceVolume": 100, "lowPriceVolume": 100}
            for i in range(10)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            orig_cache = amod._cache_path
            amod._cache_path = lambda name, profile=None: Path(tmp) / (name + ".json")
            try:
                with mock.patch.object(amod, "fetch_mapping", return_value=[
                        {"id": 1397, "name": "Air battlestaff", "members": True,
                         "limit": 18000, "highalch": 9300}]):
                    with mock.patch.object(amod, "fetch_latest", return_value={
                            "1397": {"high": 8780, "low": 8750,
                                     "highTime": now - 60, "lowTime": now - 60}}):
                        with mock.patch.object(amod, "fetch_timeseries",
                                               return_value=ts_data):
                            import contextlib, io
                            with contextlib.redirect_stdout(io.StringIO()) as out:
                                cmod.item_info(Namespace(
                                    item="air battlestaff", profile=None,
                                    json=True, timeseries=True, predict=False,
                                    tax_curve=False, wiki=False, wiki_open=False))
                            data = json.loads(out.getvalue())  # must parse as ONE doc
                            self.assertIn("timeseries_analysis", data)
                            self.assertIn("confidence", data["timeseries_analysis"])
            finally:
                amod._cache_path = orig_cache

    def test_profile_switch_missing_raises(self):
        """profile switch to a nonexistent profile must exit 1."""
        import rshelper.profile as pmod
        from pathlib import Path
        orig = pmod.CONFIG_DIR
        with tempfile.TemporaryDirectory() as tmp:
            pmod.CONFIG_DIR = Path(tmp) / "config"
            try:
                import subprocess as sp
                r = sp.run([sys.executable, "-m", "rshelper", "profile", "switch", "bogus"],
                           capture_output=True, text=True,
                           cwd=os.path.join(_TEST_DIR, ".."),
                           env={**os.environ, "PYTHONPATH": "src"})
                self.assertEqual(r.returncode, 1)
                self.assertIn("does not exist", r.stderr)
            finally:
                pmod.CONFIG_DIR = orig


    def test_signals_scan_full_universe(self):
        """`signals` must pass the FULL item list to detect_signals (flip_ids
        restrict FLIP only), mirroring the monitor/dashboard."""
        from unittest import mock
        from argparse import Namespace
        from rshelper.models import Item
        import rshelper.signals as sigmod
        import rshelper.cli as cmod
        items = [Item(id=1, name="A", members=False, buy_limit=100, alch_value=0,
                      buy_price=100, sell_price=90, volume=500),
                 Item(id=2, name="B", members=False, buy_limit=100, alch_value=0,
                      buy_price=100, sell_price=95, volume=500)]
        cmod._fetch_bootstrap = lambda p=None: (
            [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
            {"1": {"high": 100, "low": 90, "highTime": 1, "lowTime": 1},
             "2": {"high": 100, "low": 95, "highTime": 1, "lowTime": 1}},
            {"1": {"avgHighPrice": 100, "avgLowPrice": 90,
                   "highPriceVolume": 500, "lowPriceVolume": 500},
             "2": {"avgHighPrice": 100, "avgLowPrice": 95,
                   "highPriceVolume": 500, "lowPriceVolume": 500}},
            items)
        captured = {}
        def fake_detect(items_arg, vol, cooldown_sec=0, flip_ids=None, profile=None):
            captured["items"] = items_arg
            captured["flip_ids"] = flip_ids
            captured["profile"] = profile
            return []
        with mock.patch.object(sigmod, "detect_signals", side_effect=fake_detect):
            cmod.signals_cmd(Namespace(profile=None, monitor=0,
                                       flip_direction="arbitrage",
                                       members_only=False, cooldown=15,
                                       json=False))
        self.assertEqual(len(captured["items"]), 2)  # full universe, not flips
        self.assertEqual(captured["profile"], None)


if __name__ == "__main__":
    unittest.main()
