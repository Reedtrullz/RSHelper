"""E2E CLI tests: subprocess invocations of rshelper commands."""

import json
import os
import subprocess
import sys
import time
import unittest


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


if __name__ == "__main__":
    unittest.main()
