"""E2E CLI tests: subprocess invocations of rshelper commands."""

import json
import os
import subprocess
import sys
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

    def test_margin_check_help(self):
        r = run("margin-check", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--ge-slots", r.stdout)


if __name__ == "__main__":
    unittest.main()
