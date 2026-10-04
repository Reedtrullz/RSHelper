"""Test-process guard, inherited by Python CLI and concurrency subprocesses."""
import json
import inspect
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

if os.environ.get("RSHELPER_OFFLINE") == "1":
    approved_processes = {name: Path(os.environ.get('RSHELPER_TEST_EXECUTABLE_'+name.upper().replace('-', '_'), default)).resolve()
        for name, default in (('ps', '/bin/ps' if sys.platform == 'darwin' else '/usr/bin/ps'),
                              ('git', '/usr/bin/git'), ('ssh-keygen', '/usr/bin/ssh-keygen'))}
    def within(path, root):
        if not root:
            return False
        target, base = Path(path).resolve(), Path(root).resolve()
        return target == base or base in target.parents

    def fixture_process(executable, command, environment):
        args = list(map(str, command)) if isinstance(command, (list, tuple)) else []
        selected = shutil.which(executable, path=(environment or os.environ).get('PATH'))
        resolved = Path(selected or executable).resolve()
        shell_root = os.environ.get('RSHELPER_TEST_SHELL_ROOT')
        if executable == '/bin/bash':
            return (len(args) >= 2 and within(shell_root or '/', os.environ.get('RSHELPER_TEST_SCRATCH'))
                    and within(args[1], shell_root) and Path(args[1]).name == 'install-trader-launchd.sh')
        if Path(executable).name == 'ps':
            return (resolved == approved_processes['ps'] and len(args) == 5 and args[1:4] == ['-o', 'lstart=', '-p']
                    and args[4].isascii() and args[4].isdigit() and int(args[4]) > 0)
        root = os.environ.get('RSHELPER_TEST_GIT_ROOT')
        if not within(root or '/', os.environ.get('RSHELPER_TEST_SCRATCH')):
            return False
        if Path(executable).name == 'ssh-keygen':
            return (resolved == approved_processes['ssh-keygen'] and len(args) == 8 and args[1:7] == ['-q', '-t', 'ed25519', '-N', '', '-f']
                    and within(args[7], root))
        if Path(executable).name != 'git':
            return False
        fixture = (environment or os.environ).get('RSHELPER_TEST_FAKE_GIT')
        if resolved != approved_processes['git'] and not (
                fixture and resolved == Path(fixture).resolve() and within(fixture, root)):
            return False
        if '-C' in args:
            index = args.index('-C') + 1
            return index < len(args) and within(args[index], root)
        if '--git-dir' in args:
            index = args.index('--git-dir') + 1
            return index < len(args) and within(args[index], root)
        return len(args) > 2 and args[1] == 'init' and within(args[-1], root)

    def deny(message):
        with open(os.environ["RSHELPER_TEST_VIOLATIONS"], "a") as stream:
            stream.write(message + "\n")
        raise RuntimeError(message)

    def audit(event, args):
        if event in ("socket.connect", "socket.getaddrinfo"):
            # Real HTTP tests may use loopback; external providers need opt-in.
            address = args[1] if event == "socket.connect" else args[0]
            host = address[0] if isinstance(address, tuple) else address
            local_socket = (event == 'socket.connect' and getattr(args[0], 'family', None) == 1
                            and isinstance(address, (str, bytes)) and any(within(os.fsdecode(address), root)
                            for root in (os.environ.get('RSHELPER_TEST_SOCKET_ROOT'),
                                         os.environ.get('RSHELPER_TEST_SCRATCH'))))
            if not local_socket and host not in ("127.0.0.1", "::1", "localhost"):
                deny("unexpected external network access")
        if event == "subprocess.Popen":
            executable = str(args[0])
            if (Path(executable).resolve() != Path(sys.executable).resolve()
                    and not fixture_process(executable, args[1], args[3])):
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
        if isinstance(command, (list, tuple)) and command and Path(str(command[0])).name == 'git':
            # Local-file fixture remotes only. These override Git configuration
            # before any helper command can contact an HTTP/SSH provider.
            env.update(GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_0='protocol.allow',
                       GIT_CONFIG_VALUE_0='never', GIT_CONFIG_KEY_1='protocol.file.allow',
                       GIT_CONFIG_VALUE_1='always', GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_CONFIG_NOSYSTEM='1')
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
