"""Multi-account profile management."""
import os
import re
import shutil
import json
import tempfile
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "rshelper"
CACHE_DIR = Path.home() / ".cache" / "rshelper"
ACTIVE_PROFILE_PATH = CONFIG_DIR / "active_profile"

PROFILE_NAME_RE = re.compile(r'^[a-zA-Z0-9_-]{1,32}$')


def _read_active_profile() -> str:
    """Read active profile name. Returns 'default' if missing."""
    try:
        if ACTIVE_PROFILE_PATH.exists():
            name = ACTIVE_PROFILE_PATH.read_text().strip()
            if name:
                return name
    except OSError:
        pass
    return "default"


def get_active_profile() -> str:
    return _read_active_profile()


def set_active_profile(name: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(ACTIVE_PROFILE_PATH, name)


def atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically with a unique temp file (safe under concurrency)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data, indent: int | None = None) -> None:
    """Write JSON atomically with a unique temp file (safe under concurrency)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def resolve_config_path(subpath: str, profile: str | None = None) -> Path:
    if profile is None:
        profile = _read_active_profile()
    if profile == "default":
        return CONFIG_DIR / subpath
    return CONFIG_DIR / "profiles" / profile / subpath


def resolve_cache_path(subpath: str, profile: str | None = None) -> Path:
    if profile is None:
        profile = _read_active_profile()
    if profile == "default":
        return CACHE_DIR / subpath
    return CACHE_DIR / "profiles" / profile / subpath


def validate_profile_name(name: str) -> bool:
    return bool(PROFILE_NAME_RE.match(name))


def create_profile(name: str) -> bool:
    """Create profile directories. Returns False if name invalid or already exists."""
    if not validate_profile_name(name):
        return False
    config_profile = CONFIG_DIR / "profiles" / name
    cache_profile = CACHE_DIR / "profiles" / name
    if config_profile.exists() or cache_profile.exists():
        return False
    config_profile.mkdir(parents=True, exist_ok=True)
    cache_profile.mkdir(parents=True, exist_ok=True)
    return True


def delete_profile(name: str, force: bool = False) -> bool:
    """Delete profile directories. Returns False if not found."""
    if name == "default":
        return False  # can't delete default
    config_profile = CONFIG_DIR / "profiles" / name
    cache_profile = CACHE_DIR / "profiles" / name
    found = config_profile.exists() or cache_profile.exists()
    if not found:
        return False
    if not force:
        has_data = False
        for p in [config_profile, cache_profile]:
            if p.exists():
                for _ in p.rglob("*"):
                    has_data = True
                    break
        if has_data:
            return False
    shutil.rmtree(config_profile, ignore_errors=True)
    shutil.rmtree(cache_profile, ignore_errors=True)
    if _read_active_profile() == name:
        set_active_profile("default")
    return True


def list_profiles() -> list[str]:
    """List all profile names. Always includes 'default'."""
    profiles = ["default"]
    config_profiles = CONFIG_DIR / "profiles"
    if config_profiles.exists():
        for p in config_profiles.iterdir():
            if p.is_dir() and validate_profile_name(p.name):
                profiles.append(p.name)
    return sorted(set(profiles))
