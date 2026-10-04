"""Single-owner daemon leases and authenticated local stop requests."""
from __future__ import annotations

import errno
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid


_MAX_OWNER_BYTES = 4096
_MAX_STATE_BYTES = 1024 * 1024
_MAX_PID_BYTES = 128
_MAX_CONTROL_BYTES = 1024
_LABEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_DOMAIN_RE = re.compile(r"^gui/[0-9]{1,10}$")


class LeaseBusy(RuntimeError):
    """Another verified or legacy daemon prevents a safe start."""


class LeaseError(RuntimeError):
    """The ownership files or local control channel cannot be trusted."""


def _kind_name(kind: str) -> str:
    if kind in ("trader", "auto-trade"):
        return "trader"
    if kind == "monitor":
        return "monitor"
    raise ValueError(f"unsupported daemon kind: {kind}")


def _pid_path(kind: str, profile: str | None) -> Path:
    name = _kind_name(kind)
    root = Path.home() / ".config" / "rshelper"
    if profile and profile != "default":
        from rshelper.profile import resolve_config_path
        return resolve_config_path(f"{name}.pid", profile)
    return root / f"{name}.pid"


def _state_path(kind: str, profile: str | None) -> Path:
    name = _kind_name(kind)
    if profile and profile != "default":
        from rshelper.profile import resolve_config_path
        return resolve_config_path(f"{name}_state.json", profile)
    return Path.home() / ".config" / "rshelper" / f"{name}_state.json"


def lease_path(pid_path: Path) -> Path:
    """Return the persistent flock inode paired with a legacy PID path."""
    path = Path(pid_path)
    return path.with_name(path.name + ".lease")


def _control_path(pid_path: Path) -> Path:
    digest = hashlib.sha256(os.fsencode(Path(pid_path).absolute())).hexdigest()[:32]
    configured_root = os.environ.get("RSHELPER_DAEMON_SOCKET_ROOT")
    directory = (Path(configured_root) if configured_root else
                 Path("/tmp") / f"rshelper-{os.geteuid()}")
    if not directory.is_absolute():
        raise LeaseError("daemon socket root must be an absolute path")
    if configured_root is None:
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(directory, flags)
    except OSError as exc:
        raise LeaseError("cannot safely open private daemon socket directory") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise LeaseError("refusing an unsafe private daemon socket directory")
    finally:
        os.close(fd)
    return directory / f"{digest}.sock"


def _read_fd(fd: int, path: Path, limit: int) -> bytes:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise LeaseError(f"refusing non-private regular file: {path}")
    if info.st_nlink != 1 or info.st_size > limit:
        raise LeaseError(f"refusing linked or oversized file: {path}")
    chunks = bytearray()
    while len(chunks) <= limit:
        part = os.read(fd, min(4096, limit + 1 - len(chunks)))
        if not part:
            break
        chunks.extend(part)
    if len(chunks) > limit:
        raise LeaseError(f"file exceeds the {limit}-byte limit: {path}")
    return bytes(chunks)


def read_private_json(path: Path, *, limit: int = _MAX_STATE_BYTES) -> dict | None:
    """Read a bounded, owner-owned regular JSON file without following links."""
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LeaseError(f"cannot safely open {path}: {exc}") from exc
    try:
        raw = _read_fd(fd, path, limit)
        if stat.S_IMODE(os.fstat(fd).st_mode) & 0o077:
            raise LeaseError(f"private JSON file has broad permissions: {path}")
    finally:
        os.close(fd)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeaseError(f"invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise LeaseError(f"expected a JSON object in {path}")
    return value


def _read_record(path: Path) -> dict | None:
    try:
        return read_private_json(path, limit=_MAX_OWNER_BYTES)
    except LeaseError:
        return None


def _read_legacy_pid(path: Path) -> tuple[bool, int | None]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return False, None
    except OSError as exc:
        raise LeaseError(f"cannot safely inspect legacy PID record {path}: {exc}") from exc
    try:
        raw = _read_fd(fd, path, _MAX_PID_BYTES)
    finally:
        os.close(fd)
    try:
        pid = int(raw.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        return True, None
    return True, pid if pid > 0 else None


def process_identity(pid: int) -> str | None:
    """Return a PID-reuse-resistant process start identity, or None if absent."""
    if pid <= 0:
        return None
    if sys.platform.startswith("linux"):
        try:
            raw = Path(f"/proc/{pid}/stat").read_text()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LeaseError(f"cannot inspect process {pid}: {exc}") from exc
        end = raw.rfind(")")
        if end < 0:
            raise LeaseError(f"invalid process identity record for {pid}")
        fields = raw[end + 2:].split()  # starts at proc stat field 3
        if len(fields) <= 19:
            raise LeaseError(f"truncated process identity record for {pid}")
        try:
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError as exc:
            raise LeaseError(f"cannot read system boot identity: {exc}") from exc
        if not boot_id:
            raise LeaseError("system boot identity is empty")
        return f"linux:{boot_id}:{fields[19]}"
    if sys.platform == "darwin":
        result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                                capture_output=True, text=True, timeout=2)
        value = result.stdout.strip()
        if not value and result.returncode:
            if not result.stderr.strip():
                return None
            raise LeaseError(f"cannot inspect process {pid}: {result.stderr.strip()[:200]}")
        return f"macos:{value}" if value else None
    raise LeaseError(f"process identity is unsupported on {sys.platform}")


def _open_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise LeaseError(f"cannot safely open daemon lease {path}: {exc}") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or info.st_size > _MAX_OWNER_BYTES):
            raise LeaseError(f"refusing unsafe daemon lease file: {path}")
        os.fchmod(fd, 0o600)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _write_record(fd: int, record: dict, path: Path) -> None:
    data = json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(data) > _MAX_OWNER_BYTES:
        raise LeaseError("daemon owner record exceeds its size limit")
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]
    os.fsync(fd)


def _held_record(pid_path: Path) -> tuple[bool, dict | None]:
    path = lease_path(pid_path)
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return False, None
    except OSError:
        return False, None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or info.st_size > _MAX_OWNER_BYTES):
            return False, None
        if stat.S_IMODE(info.st_mode) & 0o077:
            return False, None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                return False, None
            held = True
        else:
            held = False
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.lseek(fd, 0, os.SEEK_SET)
        raw = _read_fd(fd, path, _MAX_OWNER_BYTES)
        try:
            record = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            record = None
        if not isinstance(record, dict):
            record = None
        return held, record
    finally:
        os.close(fd)


def daemon_status(kind: str, profile: str | None = None, *,
                  pid_path: Path | None = None,
                  state: dict | None = None) -> dict:
    """Report lease-backed ownership, legacy uncertainty, or a state snapshot."""
    kind = _kind_name(kind)
    pid_path = Path(pid_path) if pid_path is not None else _pid_path(kind, profile)
    held, record = _held_record(pid_path)
    if held:
        try:
            owner_pid = int(record.get("pid", -1)) if record else -1
            identity_matches = bool(
                record and owner_pid > 0 and record.get("process_identity")
                and process_identity(owner_pid) == record["process_identity"])
        except (TypeError, ValueError, LeaseError):
            identity_matches = False
        if (record and record.get("version") == 1
                and record.get("kind") == kind and identity_matches):
            return {
                "running": True, "local": True, "ownership": "verified_lease",
                "pid": record["pid"], "profile": record.get("profile", profile or "default"),
                "kind": kind, "daemon_instance": record.get("daemon_instance"),
                "supervisor": record.get("supervisor_kind"),
                "service_domain": record.get("service_domain"),
                "service_label": record.get("service_label"),
                "desired_state": record.get("desired_state"),
                "ready": bool(record.get("ready", False)),
            }
        return {"running": False, "local": True,
                "ownership": "legacy_unverified", "pid": None,
                "profile": profile or "default", "kind": kind}

    legacy_present, legacy_pid = _read_legacy_pid(pid_path)
    instance_id = record.get("daemon_instance") if record else None
    if state is not None and instance_id and state.get("daemon_instance") == instance_id:
        ownership = "synced_snapshot"
    elif legacy_present:
        ownership = "legacy_unverified"
    else:
        ownership = "synced_snapshot"
    result = dict(state or {})
    result.update({"running": False, "local": False,
                   "ownership": ownership, "kind": kind})
    if ownership == "legacy_unverified":
        result["local"] = True
    result.setdefault("profile", profile or "default")
    result.setdefault("pid", legacy_pid if ownership == "legacy_unverified" else None)
    if record:
        result.update({
            "supervisor": record.get("supervisor_kind"),
            "service_domain": record.get("service_domain"),
            "service_label": record.get("service_label"),
            "desired_state": record.get("desired_state"),
            "ready": bool(record.get("ready", False)),
        })
    return result


class DaemonLease:
    """A lifetime flock plus a nonce-checked private Unix-socket control path."""

    def __init__(self, kind: str, profile: str | None, pid_path: Path, *,
                 supervisor_kind: str | None, service_domain: str | None,
                 service_label: str | None):
        self.kind = kind
        self.profile = profile or "default"
        self.pid_path = pid_path
        self.path = lease_path(pid_path)
        self.control_path = _control_path(pid_path)
        self.supervisor_kind = supervisor_kind
        self.service_domain = service_domain
        self.service_label = service_label
        self.desired_state = "enabled" if supervisor_kind else "running"
        self.stop_event = threading.Event()
        self._close_event = threading.Event()
        self._socket: socket.socket | None = None
        self._server: threading.Thread | None = None
        self._socket_inode: tuple[int, int] | None = None
        self._fd: int | None = None
        self.owner_nonce = secrets.token_hex(32)
        self.daemon_instance = uuid.uuid4().hex
        self.pid = os.getpid()
        self.identity = process_identity(self.pid)
        if not self.identity:
            raise LeaseError("could not establish this daemon's process identity")
        self._record = {
            "version": 1, "kind": kind, "profile": self.profile,
            "pid": self.pid, "process_identity": self.identity,
            "owner_nonce": self.owner_nonce,
            "daemon_instance": self.daemon_instance,
            "supervisor_kind": supervisor_kind,
            "service_domain": service_domain, "service_label": service_label,
            "desired_state": self.desired_state, "ready": False,
        }

    def __enter__(self) -> "DaemonLease":
        self._fd = _open_lock(self.path)
        try:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                    raise LeaseBusy("daemon lease is already held") from exc
                raise LeaseError(f"cannot acquire daemon lease: {exc}") from exc
            present, legacy_pid = _read_legacy_pid(self.pid_path)
            if present:
                if legacy_pid is None:
                    raise LeaseBusy("legacy PID record is unverified; controlled restart required")
                try:
                    legacy_identity = process_identity(legacy_pid)
                except LeaseError as exc:
                    raise LeaseBusy("legacy PID record is unverified; controlled restart required") from exc
                if legacy_identity is not None:
                    raise LeaseBusy("legacy daemon may still be running; controlled restart required")
            self._record["active"] = True
            _write_record(self._fd, self._record, self.path)
            self._open_control_socket()
            return self
        except BaseException:
            self._close(startup_failed=True)
            raise

    def _open_control_socket(self) -> None:
        encoded = os.fsencode(str(self.control_path))
        if len(encoded) >= 104:
            raise LeaseError("daemon control socket path exceeds the platform limit")
        try:
            info = self.control_path.lstat()
        except FileNotFoundError:
            info = None
        if info is not None:
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise LeaseError("refusing to replace an unowned daemon control path")
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(0.1)
            try:
                probe.connect(str(self.control_path))
            except OSError as exc:
                if exc.errno not in (errno.ECONNREFUSED, errno.ENOENT):
                    raise LeaseBusy("daemon control path is already in use") from exc
            else:
                raise LeaseBusy("daemon control server is already active")
            finally:
                probe.close()
            current = self.control_path.lstat()
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise LeaseError("daemon control path changed during stale-socket check")
            self.control_path.unlink()

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.control_path))
            os.chmod(self.control_path, 0o600)
            info = self.control_path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise LeaseError("daemon control socket permissions could not be verified")
            self._socket_inode = (info.st_dev, info.st_ino)
            server.listen(8)
            server.settimeout(0.2)
        except BaseException:
            server.close()
            self._unlink_control_socket()
            raise
        self._socket = server
        self._server = threading.Thread(target=self._serve_control,
                                        name=f"rshelper-{self.kind}-control", daemon=True)
        self._server.start()

    def _serve_control(self) -> None:
        assert self._socket is not None
        while not self._close_event.is_set():
            try:
                conn, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(1)
                payload = bytearray()
                try:
                    while len(payload) <= _MAX_CONTROL_BYTES:
                        part = conn.recv(min(256, _MAX_CONTROL_BYTES + 1 - len(payload)))
                        if not part or b"\n" in part:
                            payload.extend(part.split(b"\n", 1)[0])
                            break
                        payload.extend(part)
                    if len(payload) > _MAX_CONTROL_BYTES:
                        raise ValueError("request too large")
                    request = json.loads(payload)
                    if not isinstance(request, dict) or not hmac.compare_digest(
                            str(request.get("nonce", "")), self.owner_nonce):
                        response = {"ok": False, "error": "owner identity mismatch"}
                    elif request.get("action") == "probe":
                        response = {"ok": True, "daemon_instance": self.daemon_instance}
                    elif request.get("action") == "stop":
                        desired = request.get("desired_state")
                        if desired not in ("stopped", "disabled"):
                            response = {"ok": False, "error": "invalid desired state"}
                        else:
                            self.desired_state = desired
                            self._record["desired_state"] = desired
                            _write_record(self._fd, self._record, self.path)
                            self.stop_event.set()
                            response = {"ok": True, "desired_state": desired}
                    else:
                        response = {"ok": False, "error": "unsupported control action"}
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    response = {"ok": False, "error": "invalid control request"}
                try:
                    conn.sendall(json.dumps(response, separators=(",", ":")).encode() + b"\n")
                except OSError:
                    pass

    def _unlink_control_socket(self) -> None:
        if self._socket_inode is None:
            return
        try:
            info = self.control_path.lstat()
        except OSError:
            return
        if (stat.S_ISSOCK(info.st_mode) and info.st_uid == os.geteuid()
                and (info.st_dev, info.st_ino) == self._socket_inode):
            self.control_path.unlink()
        self._socket_inode = None

    def _close(self, *, startup_failed: bool = False) -> None:
        self._close_event.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._server is not None and self._server is not threading.current_thread():
            self._server.join(timeout=1)
            self._server = None
        self._unlink_control_socket()
        if self._fd is not None:
            try:
                if startup_failed:
                    current = _read_record(self.path)
                    if current and current.get("owner_nonce") == self.owner_nonce:
                        os.ftruncate(self._fd, 0)
                        os.fsync(self._fd)
                else:
                    self._record["active"] = False
                    _write_record(self._fd, self._record, self.path)
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._close()

    def mark_ready(self) -> None:
        """Publish readiness only after the caller's state and signal setup."""
        if self._fd is None or not self._record.get("active"):
            raise LeaseError("cannot publish readiness without an acquired lease")
        self._record["ready"] = True
        _write_record(self._fd, self._record, self.path)


def _supervisor_values(supervisor_kind: str | None, service_domain: str | None,
                       service_label: str | None) -> tuple[str | None, str | None, str | None]:
    supervisor_kind = supervisor_kind or os.environ.get("RSHELPER_SUPERVISOR_KIND") or None
    service_domain = service_domain or os.environ.get("RSHELPER_SERVICE_DOMAIN") or None
    service_label = service_label or os.environ.get("RSHELPER_SERVICE_LABEL") or None
    if supervisor_kind is None:
        return None, None, None
    if supervisor_kind != "launchd":
        raise LeaseError(f"unsupported supervisor kind: {supervisor_kind}")
    if not service_domain or not _DOMAIN_RE.fullmatch(service_domain):
        raise LeaseError("launchd service domain is missing or invalid")
    if not service_label or not _LABEL_RE.fullmatch(service_label):
        raise LeaseError("launchd service label is missing or invalid")
    return supervisor_kind, service_domain, service_label


def acquire_lease(kind: str, profile: str | None = None, *,
                  pid_path: Path | None = None,
                  supervisor_kind: str | None = None,
                  service_domain: str | None = None,
                  service_label: str | None = None) -> DaemonLease:
    """Build a lifetime lease for one daemon/profile pair."""
    kind = _kind_name(kind)
    supervisor_kind, service_domain, service_label = _supervisor_values(
        supervisor_kind, service_domain, service_label)
    return DaemonLease(kind, profile, Path(pid_path) if pid_path is not None
                       else _pid_path(kind, profile),
                       supervisor_kind=supervisor_kind,
                       service_domain=service_domain,
                       service_label=service_label)


class LaunchdSupervisor:
    """Narrow adapter for persistent launchd desired-state changes."""

    @staticmethod
    def _target(domain: str, label: str) -> str:
        if not _DOMAIN_RE.fullmatch(domain) or not _LABEL_RE.fullmatch(label):
            raise LeaseError("invalid launchd service identity")
        return f"{domain}/{label}"

    @staticmethod
    def _run(args: list[str]) -> None:
        if sys.platform != "darwin":
            raise LeaseError("launchd controls are only available on macOS")
        subprocess.run(args, check=True, capture_output=True, text=True, timeout=15)

    def disable(self, domain: str, label: str) -> None:
        self._run(["launchctl", "disable", self._target(domain, label)])

    def bootout(self, domain: str, label: str) -> None:
        self._run(["launchctl", "bootout", self._target(domain, label)])

    def enable(self, domain: str, label: str) -> None:
        self._run(["launchctl", "enable", self._target(domain, label)])

    def bootstrap(self, domain: str, label: str) -> None:
        target = self._target(domain, label)
        plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        self._run(["launchctl", "bootstrap", domain, str(plist)])


def wait_for_ready(kind: str, profile: str | None = None, *,
                   pid_path: Path | None = None,
                   state_path: Path | None = None,
                   expected_pid: int | None = None,
                   process=None,
                   timeout: float = 3.0,
                   poll_interval: float = 0.05) -> dict:
    """Wait for the expected child's lease, initial state, and ready receipt.

    When a Popen object is supplied, exit is detected early. The function
    never treats a PID/state snapshot alone as proof of readiness.
    """
    kind = _kind_name(kind)
    pid_path = Path(pid_path) if pid_path is not None else _pid_path(kind, profile)
    state_path = Path(state_path) if state_path is not None else _state_path(kind, profile)
    deadline = time.monotonic() + max(0.0, timeout)
    delay = max(0.005, poll_interval)
    last_status: dict = {"ready": False, "running": False,
                         "ownership": "synced_snapshot", "kind": kind}
    while True:
        if process is not None and process.poll() is not None:
            last_status.update({"ready": False, "running": False,
                                "reason": "process_exited",
                                "returncode": process.returncode})
            return last_status
        state = read_private_json(state_path)
        last_status = daemon_status(kind, profile, pid_path=pid_path, state=state)
        instance_matches = bool(
            state and state.get("daemon_instance")
            and state.get("daemon_instance") == last_status.get("daemon_instance"))
        pid_matches = expected_pid is None or last_status.get("pid") == expected_pid
        ready = (last_status.get("ownership") == "verified_lease"
                 and last_status.get("running") is True
                 and last_status.get("ready") is True
                 and state is not None and state.get("ready") is True
                 and instance_matches and pid_matches)
        if ready:
            last_status["ready"] = True
            return last_status
        last_status["ready"] = False
        if time.monotonic() >= deadline:
            last_status["reason"] = "timeout"
            return last_status
        time.sleep(min(delay, max(0.0, deadline - time.monotonic())))


def _control_request(pid_path: Path, nonce: str, action: str,
                     desired_state: str | None = None) -> dict:
    path = _control_path(pid_path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise LeaseError("verified daemon control socket is unavailable") from exc
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise LeaseError("refusing an unverified daemon control socket")
    request = {"nonce": nonce, "action": action}
    if desired_state:
        request["desired_state"] = desired_state
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(2)
        client.connect(str(path))
        client.sendall(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        payload = bytearray()
        while len(payload) <= _MAX_CONTROL_BYTES:
            part = client.recv(min(256, _MAX_CONTROL_BYTES + 1 - len(payload)))
            if not part or b"\n" in part:
                payload.extend(part.split(b"\n", 1)[0])
                break
            payload.extend(part)
        if len(payload) > _MAX_CONTROL_BYTES:
            raise LeaseError("daemon control response exceeds its limit")
        response = json.loads(payload)
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise LeaseError("daemon rejected the stop request")
        return response
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        if isinstance(exc, LeaseError):
            raise
        raise LeaseError(f"daemon stop request failed: {exc}") from exc
    finally:
        client.close()


def _stop_receipt(pid_path: Path, *, requested: bool, desired_state: str,
                  kind: str, record: dict, timeout: float) -> dict:
    deadline = time.monotonic() + max(0.0, timeout)
    held, _ = _held_record(pid_path)
    while held and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        held, _ = _held_record(pid_path)
    stopped = not held
    result = {
        "ok": requested, "requested": requested, "stopped": stopped,
        "running": held, "timed_out": requested and held,
        "ownership": "verified_lease",
        "supervisor": record.get("supervisor_kind"),
        "service_domain": record.get("service_domain"),
        "service_label": record.get("service_label"),
        "desired_state": desired_state,
    }
    if requested and held:
        result["error"] = "stop request accepted; daemon still holds its lease"
    return result


def request_stop(kind: str, profile: str | None = None, *,
                 pid_path: Path | None = None,
                 supervisor_adapter=None,
                 timeout: float = 3.0) -> dict:
    """Request an owned stop and report release separately; never signal a PID."""
    kind = _kind_name(kind)
    pid_path = Path(pid_path) if pid_path is not None else _pid_path(kind, profile)
    held, record = _held_record(pid_path)
    if not held or not record or record.get("version") != 1:
        status = daemon_status(kind, profile, pid_path=pid_path)
        return {"ok": False, "requested": False, "stopped": False,
                "running": bool(status.get("running")),
                "ownership": status.get("ownership", "synced_snapshot"),
                "error": "no verified daemon lease is held"}
    status = daemon_status(kind, profile, pid_path=pid_path)
    if status.get("ownership") != "verified_lease":
        return {"ok": False, "requested": False, "stopped": False,
                "running": True,
                "ownership": "legacy_unverified",
                "error": "daemon process identity cannot be verified"}
    nonce = record.get("owner_nonce")
    if not isinstance(nonce, str) or len(nonce) != 64:
        return {"ok": False, "requested": False, "stopped": False,
                "running": True,
                "ownership": "legacy_unverified",
                "error": "daemon owner nonce is invalid"}
    requested = False
    desired = record.get("desired_state") or "running"
    try:
        _control_request(pid_path, nonce, "probe")
        supervised = record.get("supervisor_kind") == "launchd"
        if supervised:
            domain, label = record.get("service_domain"), record.get("service_label")
            if not domain or not label:
                raise LeaseError("verified lease has no launchd service identity")
            adapter = supervisor_adapter or LaunchdSupervisor()
            adapter.disable(domain, label)
            desired = "disabled"
            _control_request(pid_path, nonce, "stop", "disabled")
            requested = True
            adapter.bootout(domain, label)
        else:
            _control_request(pid_path, nonce, "stop", "stopped")
            requested = True
            desired = "stopped"
    except Exception as exc:
        result = _stop_receipt(pid_path, requested=requested,
                               desired_state=desired, kind=kind,
                               record=record, timeout=timeout)
        result["ok"] = False
        result["error"] = str(exc)[:300]
        return result
    result = _stop_receipt(pid_path, requested=True,
                           desired_state=desired, kind=kind,
                           record=record, timeout=timeout)
    result["ok"] = True
    return result


def _persist_supervisor_desired_state(pid_path: Path, kind: str,
                                      record: dict, desired_state: str) -> bool:
    path = lease_path(pid_path)
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return False
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        current = json.loads(_read_fd(fd, path, _MAX_OWNER_BYTES))
        if (not isinstance(current, dict) or current.get("version") != 1
                or current.get("kind") != kind or current.get("active")
                or current.get("owner_nonce") != record.get("owner_nonce")
                or current.get("daemon_instance") != record.get("daemon_instance")):
            return False
        current["desired_state"] = desired_state
        _write_record(fd, current, path)
        return True
    except (LeaseError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def start_supervised_daemon(kind: str, profile: str | None = None, *,
                            pid_path: Path | None = None,
                            state_path: Path | None = None,
                            supervisor_adapter=None,
                            timeout: float = 3.0,
                            poll_interval: float = 0.05) -> dict:
    """Enable and bootstrap the persisted launchd service, then await readiness."""
    kind = _kind_name(kind)
    pid_path = Path(pid_path) if pid_path is not None else _pid_path(kind, profile)
    state_path = Path(state_path) if state_path is not None else _state_path(kind, profile)
    held, record = _held_record(pid_path)
    if held:
        status = daemon_status(kind, profile, pid_path=pid_path)
        return {**status, "ok": False, "requested": False,
                "ready": bool(status.get("ready")),
                "error": "daemon already owns the lease"}
    if (not record or record.get("version") != 1 or record.get("kind") != kind
            or record.get("supervisor_kind") != "launchd"):
        return {"ok": False, "requested": False, "running": False,
                "ready": False, "ownership": "synced_snapshot",
                "error": "no retained launchd service identity; supervised start refused"}
    domain, label = record.get("service_domain"), record.get("service_label")
    requested = False
    desired = record.get("desired_state", "disabled")
    adapter = supervisor_adapter or LaunchdSupervisor()
    try:
        LaunchdSupervisor._target(domain, label)
        adapter.enable(domain, label)
        requested = True
        desired = "enabled"
        if not _persist_supervisor_desired_state(pid_path, kind, record, "enabled"):
            raise LeaseError("could not persist launchd enabled desired state")
        adapter.bootstrap(domain, label)
        ready = wait_for_ready(
            kind, profile, pid_path=pid_path, state_path=state_path,
            timeout=timeout, poll_interval=poll_interval)
        if ready.get("ready"):
            return {**ready, "ok": True, "requested": True,
                    "desired_state": "enabled", "supervisor": "launchd"}
        error = "daemon startup did not report verified readiness"
    except Exception as exc:
        error = str(exc)[:300]
    cleanup_errors = []
    if requested:
        try:
            adapter.disable(domain, label)
            desired = "disabled"
        except Exception as exc:
            cleanup_errors.append("disable failed: " + str(exc)[:150])
        held, current = _held_record(pid_path)
        if (held and current and desired == "disabled"
                and current.get("service_domain") == domain
                and current.get("service_label") == label):
            try:
                _control_request(pid_path, current["owner_nonce"], "stop", "disabled")
            except Exception as exc:
                cleanup_errors.append("owned stop failed: " + str(exc)[:150])
        try:
            adapter.bootout(domain, label)
        except Exception as exc:
            cleanup_errors.append("bootout failed: " + str(exc)[:150])
        receipt = _stop_receipt(pid_path, requested=True, desired_state=desired,
                                kind=kind, record=record, timeout=timeout)
        held, current = _held_record(pid_path)
        if (not held and current and desired == "disabled"
                and current.get("service_domain") == domain
                and current.get("service_label") == label):
            if not _persist_supervisor_desired_state(pid_path, kind, current, "disabled"):
                cleanup_errors.append("could not persist disabled desired state")
    else:
        receipt = daemon_status(kind, profile, pid_path=pid_path)
    return {**receipt, "ok": False, "requested": requested, "ready": False,
            "desired_state": desired, "supervisor": "launchd",
            "service_domain": domain, "service_label": label,
            "cleanup_complete": bool(requested and desired == "disabled"
                                     and not receipt.get("running") and not cleanup_errors),
            "cleanup_errors": cleanup_errors, "error": error}


def install_stop_signal(lease: DaemonLease):
    """Install a temporary SIGTERM handler that wakes the lease owner loop."""
    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda _signum, _frame: lease.stop_event.set())
    return previous


def restore_stop_signal(previous) -> None:
    signal.signal(signal.SIGTERM, previous)
