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

    def test_synthetic_git_is_scoped_and_remote_transports_are_disabled(self):
        result=self.invoke("import os, subprocess\nfrom pathlib import Path\n"
            "def test_git():\n"
            " root=Path(os.environ['TMPDIR'])/'git-fixture'\n"
            " os.environ['RSHELPER_TEST_GIT_ROOT']=os.environ['TMPDIR']\n"
            " subprocess.run(['git','init',str(root)],capture_output=True,check=True)\n"
            " denied=subprocess.run(['git','-C',str(root),'fetch','https://example.invalid/repo.git'],capture_output=True,text=True)\n"
            " assert denied.returncode and 'transport' in denied.stderr and 'not allowed' in denied.stderr\n")
        self.assertEqual(result.returncode,0,result.stderr)

    def test_git_allowance_cannot_select_the_real_checkout(self):
        result=self.invoke("import os, subprocess\n"
            "def test_git():\n"
            " os.environ['RSHELPER_TEST_GIT_ROOT']=os.environ['TMPDIR']\n"
            " try: subprocess.run(['git','-C',os.environ['RSHELPER_REAL_HOME'],'status'],capture_output=True)\n"
            " except Exception: pass\n")
        self.assertNotEqual(result.returncode,0)
        self.assertIn('external process',json.loads(result.stdout)['files'][0]['error'])

    def test_read_only_process_start_identity_is_allowed(self):
        result=self.invoke("import os, subprocess\n"
            "def test_identity():\n"
            " p=subprocess.run(['ps','-o','lstart=','-p',str(os.getpid())],capture_output=True,text=True)\n"
            " assert p.returncode==0 and p.stdout.strip()\n")
        self.assertEqual(result.returncode,0,result.stderr)

    def test_process_allowance_rejects_a_same_named_path_replacement(self):
        result=self.invoke("import os, subprocess\nfrom pathlib import Path\n"
            "def test_identity():\n"
            " root=Path(os.environ['TMPDIR'])/'fake-bin';root.mkdir()\n"
            " fake=root/'ps';fake.write_text('#!/bin/sh\\nexit 0\\n');fake.chmod(0o700)\n"
            " os.environ['PATH']=str(root)+os.pathsep+os.environ['PATH']\n"
            " try: subprocess.run(['ps','-o','lstart=','-p',str(os.getpid())],capture_output=True)\n"
            " except Exception: pass\n")
        self.assertNotEqual(result.returncode,0)
        self.assertIn('external process',json.loads(result.stdout)['files'][0]['error'])

    def test_owned_unix_socket_is_allowed_without_external_network(self):
        result=self.invoke("import os, socket\nfrom pathlib import Path\n"
            "def test_socket():\n"
            " path=Path(os.environ['RSHELPER_TEST_SOCKET_ROOT'])/'fixture.sock'\n"
            " with socket.socket(socket.AF_UNIX) as server,socket.socket(socket.AF_UNIX) as client:\n"
            "  server.bind(str(path));server.listen(1);client.connect(str(path))\n"
            "  conn,_=server.accept();conn.close()\n"
            " path.unlink()\n")
        self.assertEqual(result.returncode,0,result.stderr)

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
