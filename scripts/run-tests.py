"""Run every test file in a disposable home; no third-party test runner."""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts/test-support"


def execute_file(path):
    spec = importlib.util.spec_from_file_location("isolated_tests", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    for name, function in vars(module).items():
        if name.startswith("test_") and callable(function) and not isinstance(function, type):
            suite.addTest(unittest.FunctionTestCase(function))
    if not suite.countTestCases():
        raise ValueError("no tests executed in discovered file")
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    return {"tests": result.testsRun, "skipped": len(result.skipped),
            "failures": len(result.failures), "errors": len(result.errors)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--provider-check", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--tests-dir", type=Path, default=ROOT / "tests")
    parser.add_argument("--file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.file:
        report = {"tests": 0, "skipped": 0, "failures": 0, "errors": 0}
        try:
            report.update(execute_file(args.file))
        except BaseException as exc:
            report.update(error=f"{type(exc).__name__}: {exc}", errors=1)
        args.result.write_text(json.dumps(report))
        return int(bool(report.get("error") or report["failures"] or report["errors"]))
    files = sorted(args.tests_dir.glob("test_*.py"))
    if args.provider_check:
        files = [path for path in files if path.name == "test_integration.py"]
    report = {"mode": "offline" if args.offline else "provider-check", "files": [],
              "tests": 0, "skipped": 0, "failures": 0, "errors": 0}
    scratch_root = Path(os.environ.get("RSHELPER_TEST_SCRATCH", ROOT / ".execution"))
    scratch_root.mkdir(parents=True, exist_ok=True)
    for path in files:
        with tempfile.TemporaryDirectory(prefix="suite-", dir=scratch_root) as folder:
            home = Path(folder) / "home"
            home.mkdir()
            result_path = Path(folder) / "result.json"
            violation = Path(folder) / "violations.log"
            env = {**os.environ, "HOME": str(home), "TMPDIR": folder,
                   "XDG_CONFIG_HOME": str(home / ".config"),
                   "XDG_CACHE_HOME": str(home / ".cache"),
                   "RSHELPER_REAL_HOME": os.environ.get("RSHELPER_REAL_HOME", str(Path.home())),
                   "RSHELPER_TEST_GUARD": str(GUARD),
                   "RSHELPER_TEST_VIOLATIONS": str(violation),
                   "RSHELPER_TEST_SCRATCH": folder,
                   "RSHELPER_OFFLINE": "1" if args.offline else "0",
                   "RSHELPER_PROVIDER_CHECK": "1" if args.provider_check else "0",
                   "PYTHONPATH": os.pathsep.join([str(GUARD), str(ROOT / "src")]),
                   "PYTHONDONTWRITEBYTECODE": "1"}
            command = [sys.executable, __file__, "--offline" if args.offline else "--provider-check",
                       "--file", str(path.resolve()), "--result", str(result_path)]
            try:
                completed = subprocess.run(command, env=env, cwd=ROOT,
                                           capture_output=True, text=True, timeout=120)
                entry = json.loads(result_path.read_text()) if result_path.exists() else {
                    "tests": 0, "skipped": 0, "failures": 0, "errors": 1,
                    "error": "test subprocess produced no report"}
                if completed.returncode and not entry.get("errors") and not entry.get("failures"):
                    entry.update(errors=1, error=f"subprocess exited {completed.returncode}")
                if violation.exists():
                    entry.update(errors=entry["errors"] + 1, error=violation.read_text().strip())
                if completed.returncode or entry.get("error"):
                    print(completed.stdout + completed.stderr, file=sys.stderr)
            except subprocess.TimeoutExpired:
                entry = {"tests": 0, "skipped": 0, "failures": 0,
                         "errors": 1, "error": "test file exceeded 120 second deadline"}
            entry["file"] = path.name
            report["files"].append(entry)
            for key in ("tests", "skipped", "failures", "errors"):
                report[key] += entry[key]
            if entry["failures"] or entry["errors"]:
                break
    if not files:
        report.update(errors=1, error="no test files discovered")
    report["discovered_files"] = len(files)
    report["not_run"] = [path.name for path in files[len(report["files"]):]]
    report["complete"] = bool(files) and not report["not_run"]
    print(json.dumps(report, indent=2) if args.json else
          f'{report["tests"]} tests, {report["skipped"]} skipped, '
          f'{report["failures"]} failures, {report["errors"]} errors ({len(report["files"])} files)')
    return int(bool(report["failures"] or report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
