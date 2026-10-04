"""Contracts for the isolated, stdlib-only test runner."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestRunner(unittest.TestCase):
    def invoke(self, source):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "test_fixture.py"
            target.write_text(source)
            return subprocess.run(
                [sys.executable, str(ROOT / "scripts/run-tests.py"),
                 "--offline", "--json", "--tests-dir", folder],
                capture_output=True, text=True, timeout=20)

    def test_runner_fails_on_unexecuted_file(self):
        result = self.invoke("VALUE = 1\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no tests", json.loads(result.stdout)["files"][0]["error"])

    def test_actual_counts_include_functions_and_unittest(self):
        result = self.invoke("import unittest\ndef test_function(): assert True\n"
                             "class Tests(unittest.TestCase):\n"
                             " def test_method(self): self.assertTrue(True)\n"
                             " @unittest.skip('fixture')\n"
                             " def test_skip(self): pass\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["tests"], report["skipped"]), (3, 1))

    def test_offline_suite_no_external_side_effects(self):
        result = self.invoke("import socket\ndef test_network():\n"
                             " try: socket.create_connection(('example.com', 80))\n"
                             " except Exception: pass\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("network", json.loads(result.stdout)["files"][0]["error"])

    def test_home_is_disposable(self):
        result = self.invoke("import os\nfrom pathlib import Path\n"
                             "def test_home():\n"
                             " assert str(Path.home()) != os.environ['RSHELPER_REAL_HOME']\n"
                             " (Path.home() / 'written-by-test').write_text('fixture')\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_external_process_is_rejected(self):
        result = self.invoke("import subprocess\ndef test_process():\n"
                             " try: subprocess.run(['osascript', '-e', 'ignored'])\n"
                             " except Exception: pass\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("external process", json.loads(result.stdout)["files"][0]["error"])

    def test_positional_environment_keeps_guard(self):
        result = self.invoke("import os, subprocess, sys\ndef test_child():\n"
                             " env = {'HOME': os.environ['HOME']}\n"
                             " p = subprocess.Popen([sys.executable, '-c', "
                             "\"import socket; socket.getaddrinfo('example.com', 80)\"],"
                             "0, None, None, None, None, None, True, False, None, env)\n"
                             " p.wait()\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("network", json.loads(result.stdout)["files"][0]["error"])

    def test_report_identifies_unexecuted_files(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "test_a.py").write_text("def test_fail(): assert False\n")
            Path(folder, "test_b.py").write_text("def test_pass(): assert True\n")
            result = subprocess.run([sys.executable, str(ROOT / "scripts/run-tests.py"),
                                     "--offline", "--json", "--tests-dir", folder],
                                    capture_output=True, text=True, timeout=20)
        report = json.loads(result.stdout)
        self.assertFalse(report["complete"])
        self.assertEqual(report["not_run"], ["test_b.py"])


if __name__ == "__main__":
    unittest.main()
