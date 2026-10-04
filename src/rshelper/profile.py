"""Multi-account profile management."""
import dataclasses
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
        name = ACTIVE_PROFILE_PATH.read_text().strip()
    except FileNotFoundError:
        return "default"
    except OSError:
        raise ValueError("cannot read active profile marker; use an explicit --profile") from None
    if not validate_profile_name(name):
        raise ValueError("invalid active profile marker; use profile switch with a valid name")
    return name


def get_active_profile() -> str:
    return _read_active_profile()


def set_active_profile(name: str) -> None:
    if not validate_profile_name(name):
        raise ValueError("invalid profile name")
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


def resolve_profile(requested: str | None = None) -> str:
    name = _read_active_profile() if requested is None else requested
    if not validate_profile_name(name):
        raise ValueError("profile name must contain 1–32 letters, digits, underscores or hyphens")
    return name


def _rooted_path(root: Path, subpath: str, profile: str | None) -> Path:
    name = resolve_profile(profile)
    if not isinstance(subpath, str):
        raise ValueError("profile filename must be a relative string")
    relative = Path(subpath)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError("profile filename must stay within its selected root")
    selected = root if name == "default" else root / "profiles" / name
    target = selected / relative
    canonical_root = root.resolve()
    canonical_selected = selected.resolve()
    canonical_target = target.resolve()
    if not canonical_selected.is_relative_to(canonical_root) or not canonical_target.is_relative_to(canonical_selected):
        raise ValueError("profile path escapes its selected root through a symlink")
    return canonical_target


def resolve_config_path(subpath: str, profile: str | None = None) -> Path:
    return _rooted_path(CONFIG_DIR, subpath, profile)


def filter_fields(cls, data: dict) -> dict:
    """Keep only dataclass fields so older/newer JSON rows load tolerantly.

    Missing fields fall back to the dataclass defaults; unknown fields from a
    newer version are dropped instead of raising TypeError on construction.
    """
    known = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in data.items() if k in known}


def resolve_cache_path(subpath: str, profile: str | None = None) -> Path:
    return _rooted_path(CACHE_DIR, subpath, profile)


def validate_profile_name(name: str) -> bool:
    return isinstance(name, str) and bool(PROFILE_NAME_RE.fullmatch(name))


def create_profile(name: str) -> bool:
    """Create profile directories. Returns False if name invalid or already exists."""
    if not validate_profile_name(name):
        return False
    try:
        config_profile = resolve_config_path("", name)
        cache_profile = resolve_cache_path("", name)
    except ValueError:
        return False
    if config_profile.exists() or cache_profile.exists():
        return False
    config_profile.mkdir(parents=True, exist_ok=True)
    cache_profile.mkdir(parents=True, exist_ok=True)
    return True


def delete_profile(name: str, force: bool = False) -> bool:
    """Delete profile directories. Returns False if not found."""
    if name == "default" or not validate_profile_name(name):
        return False  # can't delete default
    if (CONFIG_DIR / "profiles" / name).is_symlink() or (CACHE_DIR / "profiles" / name).is_symlink():
        return False
    try:
        config_profile = resolve_config_path("", name)
        cache_profile = resolve_cache_path("", name)
    except ValueError:
        return False
    if config_profile.is_symlink() or cache_profile.is_symlink():
        return False
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
