"""Tests for multi-account profiles."""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.profile import (
    get_active_profile, set_active_profile, create_profile, delete_profile,
    list_profiles, validate_profile_name, resolve_config_path, resolve_cache_path,
    ACTIVE_PROFILE_PATH, CONFIG_DIR
)

def _clean():
    """Remove test artifacts."""
    set_active_profile("default")
    from rshelper.profile import CACHE_DIR
    for d in [CONFIG_DIR, CACHE_DIR]:
        p = d / "profiles"
        if p.exists():
            import shutil
            shutil.rmtree(p, ignore_errors=True)
    # Clean leftover data from earlier tests
    for fp in [CONFIG_DIR / "trades.json", CONFIG_DIR / "watchlist.json"]:
        if fp.exists():
            fp.unlink()

def test_default_profile_no_file():
    _clean()
    if ACTIVE_PROFILE_PATH.exists():
        ACTIVE_PROFILE_PATH.unlink()
    assert get_active_profile() == "default"
    print("  PASSED test_default_profile_no_file")

def test_profile_switch_readback():
    _clean()
    set_active_profile("alt")
    assert get_active_profile() == "alt"
    set_active_profile("default")
    assert get_active_profile() == "default"
    print("  PASSED test_profile_switch_readback")

def test_create_profile_creates_dirs():
    _clean()
    create_profile("testprof")
    config_p = CONFIG_DIR / "profiles" / "testprof"
    assert config_p.exists()
    print("  PASSED test_create_profile_creates_dirs")

def test_delete_profile_removes_dirs():
    _clean()
    create_profile("todelete")
    config_p = CONFIG_DIR / "profiles" / "todelete"
    assert config_p.exists()
    assert delete_profile("todelete", force=True)
    assert not config_p.exists()
    print("  PASSED test_delete_profile_removes_dirs")

def test_profile_watchlist_isolation():
    _clean()
    from rshelper import watchlist
    watchlist.add(1, "DefaultItem", profile="default")
    ids_default = watchlist.get_watched_ids(profile="default")
    assert 1 in ids_default
    ids_alt = watchlist.get_watched_ids(profile="alt")
    assert 1 not in ids_alt
    watchlist.remove(1, profile="default")
    print("  PASSED test_profile_watchlist_isolation")

def test_profile_cache_isolation():
    _clean()
    default_path = resolve_cache_path("test.json", "default")
    alt_path = resolve_cache_path("test.json", "alt")
    assert default_path != alt_path
    assert "profiles/alt" in str(alt_path)
    print("  PASSED test_profile_cache_isolation")

def test_profile_trade_isolation():
    _clean()
    from rshelper.journal import log_trade, list_trades, delete_trade
    t = log_trade(1, "TestItem", 1, 100, 200, profile="default")
    assert len(list_trades(profile="default")) == 1
    assert len(list_trades(profile="alt")) == 0
    delete_trade(t.id, profile="default")
    print("  PASSED test_profile_trade_isolation")

def test_profile_cli_create_switch():
    import subprocess
    _clean()
    r = subprocess.run([sys.executable, "-m", "rshelper", "profile", "create", "testcli"],
                       capture_output=True, text=True,
                       cwd=os.path.join(os.path.dirname(__file__), ".."),
                       env={**os.environ, "PYTHONPATH": "src"})
    assert r.returncode == 0
    r = subprocess.run([sys.executable, "-m", "rshelper", "profile", "switch", "testcli"],
                       capture_output=True, text=True,
                       cwd=os.path.join(os.path.dirname(__file__), ".."),
                       env={**os.environ, "PYTHONPATH": "src"})
    assert r.returncode == 0
    set_active_profile("default")
    delete_profile("testcli", force=True)
    print("  PASSED test_profile_cli_create_switch")

def test_global_profile_flag():
    """--profile flag is accepted by CLI."""
    import subprocess
    r = subprocess.run([sys.executable, "-m", "rshelper", "--profile", "default", "flip-scan", "--top", "1"],
                       capture_output=True, text=True,
                       cwd=os.path.join(os.path.dirname(__file__), ".."),
                       env={**os.environ, "PYTHONPATH": "src"})
    assert r.returncode == 0
    print("  PASSED test_global_profile_flag")

def test_default_profile_backward_compat():
    """Legacy paths still work without --profile."""
    _clean()
    assert get_active_profile() == "default"
    default_path = resolve_config_path("watchlist.json", "default")
    assert "profiles/default" not in str(default_path)
    print("  PASSED test_default_profile_backward_compat")

if __name__ == "__main__":
    test_default_profile_no_file()
    test_profile_switch_readback()
    test_create_profile_creates_dirs()
    test_delete_profile_removes_dirs()
    test_profile_watchlist_isolation()
    test_profile_cache_isolation()
    test_profile_trade_isolation()
    test_profile_cli_create_switch()
    test_global_profile_flag()
    test_default_profile_backward_compat()
    print("\nAll profile tests passed.")
