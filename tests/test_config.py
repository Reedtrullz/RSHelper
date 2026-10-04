"""Configuration contract regressions for #13."""
import os
import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rshelper import config as cmod
from rshelper import profile
from rshelper.models import Item
from rshelper import trader as tmod


class TestConfigContract(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._config_dir = profile.CONFIG_DIR
        self._active_profile_path = profile.ACTIVE_PROFILE_PATH
        self._exits_path = tmod.EXITS_PATH
        profile.CONFIG_DIR = self.tmp
        profile.ACTIVE_PROFILE_PATH = self.tmp / "active_profile"
        tmod.EXITS_PATH = self.tmp / "recent_exits.json"
        self.config_path = profile.resolve_config_path("config.toml")

    def tearDown(self):
        profile.CONFIG_DIR = self._config_dir
        profile.ACTIVE_PROFILE_PATH = self._active_profile_path
        tmod.EXITS_PATH = self._exits_path
        tmod._RECENT_EXITS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_config(self, text):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(text)

    def assert_config_error(self, text, section, key):
        self.write_config(text)
        original = self.config_path.read_bytes()
        try:
            cmod.load_config()
        except Exception as exc:
            error = exc
        else:
            self.fail("invalid config loaded without a diagnostic")
        self.assertEqual(type(error).__name__, "ConfigError")
        self.assertEqual(getattr(error, "section", None), section)
        self.assertEqual(getattr(error, "key", None), key)
        self.assertIn(section, str(error))
        self.assertIn(key, str(error))
        self.assertEqual(self.config_path.read_bytes(), original)

    def test_rejects_boolean_for_integer_field(self):
        self.assert_config_error("[alch]\nmin_volume = true\n", "alch", "min_volume")

    def test_rejects_nonfinite_float(self):
        self.assert_config_error("[trader]\nstop_slippage = nan\n",
                                 "trader", "stop_slippage")

    def test_invalid_config_stops_before_fetch(self):
        import contextlib
        import io
        from unittest import mock
        from rshelper import cli
        self.write_config('[trader]\nstop_slippage = nan\n')
        original = self.config_path.read_bytes()
        with mock.patch.object(sys, 'argv', ['rshelper', 'flip-scan', '--json']), \
                mock.patch.object(cli, '_fetch_bootstrap') as fetch, \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as exit:
                cli.main()
        self.assertEqual(exit.exception.code, 2)
        fetch.assert_not_called()
        self.assertEqual(out.getvalue(), '')
        self.assertIn('[trader].stop_slippage', err.getvalue())
        self.assertEqual(self.config_path.read_bytes(), original)

    def test_version_available_with_invalid_config(self):
        import contextlib
        import io
        from unittest import mock
        from rshelper import cli, __version__
        self.write_config('[trader]\nstop_slippage = nan\n')
        with mock.patch.object(sys, 'argv', ['rshelper', '--version']), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exit:
                cli.main()
        self.assertEqual(exit.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f'rshelper {__version__}')

    def test_rejects_unsafe_threshold_relationship(self):
        self.assert_config_error(
            "[trader]\nmin_spread_pct = 6.0\nmax_entry_spread_pct = 5.75\n",
            "trader", "max_entry_spread_pct")

    def test_rejects_unsafe_trader_limits(self):
        self.assert_config_error("[trader]\nmax_positions = 9\n", "trader", "max_positions")

    def test_rejects_invalid_interval_relationship(self):
        self.assert_config_error(
            "[trader]\nmax_hold_minutes = 1\nstop_grace_minutes = 0\n"
            "spread_collapse_exit_minutes = 0\ninterval_sec = 120\n",
            "trader", "interval_sec")

    def test_rejects_invalid_direction(self):
        self.assert_config_error("[flip]\ndirection = 'sideways'\n",
                                 "flip", "direction")

    def test_rejects_malformed_toml_with_config_diagnostic(self):
        self.assert_config_error("[trader\ncapital = 1000\n", "config", "toml")

    def test_rejects_non_table_section_and_unknown_keys(self):
        self.assert_config_error("alch = 4\n", "alch", "section")

    def test_rejects_unknown_key(self):
        self.assert_config_error("[trader]\ncapitol = 1000\n", "trader", "capitol")

    def test_effective_defaults_match_generated_toml_and_dataclasses(self):
        effective_config_dict = getattr(cmod, "effective_config_dict", None)
        self.assertTrue(callable(effective_config_dict), "effective_config_dict missing")
        cfg = cmod.load_config()
        effective = effective_config_dict(cfg)
        generated = tomllib.loads(cmod.DEFAULT_CONFIG_TOML)
        self.assertEqual(effective, generated)
        self.assertEqual(effective["trader"]["dip_depth_pct"], 2.5)
        self.assertEqual(cmod.TraderConfig().dip_depth_pct, 2.5)

    def test_validate_config_checks_dataclass_values(self):
        validate_config = getattr(cmod, "validate_config", None)
        self.assertTrue(callable(validate_config), "validate_config missing")
        cfg = cmod.Config()
        cfg.trader.stop_slippage = float("inf")
        with self.assertRaises(ValueError) as caught:
            validate_config(cfg)
        self.assertEqual(type(caught.exception).__name__, "ConfigError")
        self.assertEqual(caught.exception.section, "trader")
        self.assertEqual(caught.exception.key, "stop_slippage")

    def test_accepts_partial_legacy_toml_with_current_defaults(self):
        self.write_config("[trader]\ndip_depth_pct = 2.5\n")
        cfg = cmod.load_config()
        self.assertEqual(cfg.trader.dip_depth_pct, 2.5)
        self.assertEqual(cfg.trader.max_positions, 3)
        self.assertEqual(cfg.flip.direction, "arbitrage")

    def test_cooldown_outlives_pruning_horizon(self):
        import inspect
        import time

        self.assertIn("cfg", inspect.signature(tmod._persist_recent_exits).parameters)
        self.assertIn("cfg", inspect.signature(tmod._load_recent_exits).parameters)
        now = time.time()
        cfg = cmod.TraderConfig(stop_reentry_minutes=240)
        tmod._RECENT_EXITS.clear()
        tmod._RECENT_EXITS[1] = (now - 3 * 3600, "stop_loss")
        tmod._RECENT_EXITS[2] = (now - 5 * 3600, "stop_loss")
        tmod._persist_recent_exits(cfg=cfg)

        tmod._RECENT_EXITS.clear()
        tmod._load_recent_exits(cfg=cfg)
        self.assertIn(1, tmod._RECENT_EXITS)
        self.assertNotIn(2, tmod._RECENT_EXITS)

        item = Item(id=1, name="Dipped", members=False, buy_limit=10000,
                    alch_value=0, buy_price=105, sell_price=100, volume=1000,
                    profit=4, gp_per_hour=48000)
        latest = {"1": {"high": 105, "low": 100,
                        "highTime": now, "lowTime": now}}
        vol_5m = {"1": {"avgLowPrice": 105}}
        self.assertEqual(tmod.select_candidates([item], latest, vol_5m, cfg,
                                                now=now), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
