"""Test-process guard, inherited by Python CLI and concurrency subprocesses."""
import json
import inspect
import os
from pathlib import Path
import subprocess
import sys
import time

if os.environ.get("RSHELPER_OFFLINE") == "1":
    def deny(message):
        with open(os.environ["RSHELPER_TEST_VIOLATIONS"], "a") as stream:
            stream.write(message + "\n")
        raise RuntimeError(message)

    def audit(event, args):
        if event in ("socket.connect", "socket.getaddrinfo"):
            # Real HTTP tests may use loopback; external providers need opt-in.
            address = args[1] if event == "socket.connect" else args[0]
            host = address[0] if isinstance(address, tuple) else address
            if host not in ("127.0.0.1", "::1", "localhost"):
                deny("unexpected external network access")
        if event == "subprocess.Popen":
            executable = str(args[0])
            if Path(executable).resolve() != Path(sys.executable).resolve():
                deny("unexpected external process: " + executable)
        if event == "open":
            path, mode, flags = args
            write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR))
            if write and isinstance(path, (str, bytes)):
                target = Path(os.fsdecode(path)).resolve()
                real = Path(os.environ["RSHELPER_REAL_HOME"])
                protected = [real / ".config/rshelper", real / ".cache/rshelper",
                             real / "Library/LaunchAgents"]
                if any(target == item or item in target.parents for item in protected):
                    deny("unexpected write to live user state")
        if event in ("os.remove", "os.rmdir", "os.rename", "shutil.rmtree"):
            real = Path(os.environ["RSHELPER_REAL_HOME"])
            for value in args[:2] if event == "os.rename" else args[:1]:
                if isinstance(value, (str, bytes)):
                    target = Path(os.fsdecode(value)).resolve()
                    for protected in (real / ".config/rshelper", real / ".cache/rshelper",
                                      real / "Library/LaunchAgents"):
                        if target == protected or protected in target.parents:
                            deny("unexpected removal of live user state")

    sys.addaudithook(audit)
    original_popen = subprocess.Popen
    popen_signature = inspect.signature(original_popen)

    def isolated_popen(*args, **kwargs):
        bound = popen_signature.bind(*args, **kwargs)
        provided = bound.arguments.get("env")
        env = dict(os.environ if provided is None else provided)
        for key, value in os.environ.items():
            if key.startswith("RSHELPER_") or key in ("HOME", "TMPDIR", "PYTHONDONTWRITEBYTECODE"):
                env.setdefault(key, value)
        guard = os.environ["RSHELPER_TEST_GUARD"]
        env["PYTHONPATH"] = guard + os.pathsep + env.get("PYTHONPATH", "")
        bound.arguments["env"] = env
        command = bound.arguments.get("args", [])
        if isinstance(command, (list, tuple)) and "rshelper" in command and "-m" in command:
            cache = Path(env["HOME"]) / ".cache/rshelper"
            cache.mkdir(parents=True, exist_ok=True)
            now = int(time.time())
            fixtures = {"mapping": [{"id": 561, "name": "Nature rune", "members": False,
                                      "limit": 13000, "highalch": 108},
                                     {"id": 2, "name": "Cannonball", "members": True,
                                      "limit": 11000, "highalch": 6}],
                        "latest": {"561": {"high": 150, "low": 140, "highTime": now, "lowTime": now},
                                   "2": {"high": 200, "low": 190, "highTime": now, "lowTime": now}},
                        "5m": {"561": {"highPriceVolume": 500, "lowPriceVolume": 500},
                               "2": {"highPriceVolume": 500, "lowPriceVolume": 500}}}
            for name, payload in fixtures.items():
                target = cache / (name + ".json")
                if not target.exists():
                    target.write_text(json.dumps(payload))
        return original_popen(*bound.args, **bound.kwargs)

    subprocess.Popen = isolated_popen
