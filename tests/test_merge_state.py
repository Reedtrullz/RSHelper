"""Tests for the deploy state-merge script."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deploy"))

import merge_state


def test_list_union_repo_wins_volume_only_kept():
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        vol = Path(tmp) / "vol"
        stage.mkdir()
        vol.mkdir()
        (vol / "trades.json").write_text(json.dumps({"trades": [
            {"id": 1, "site": True}, {"id": 2, "site": True}]}))
        (stage / "trades.json").write_text(json.dumps({"trades": [
            {"id": 2, "site": False}, {"id": 3, "site": False}]}))
        merge_state.merge_dir(str(stage), str(vol), None)
        merged = json.loads((vol / "trades.json").read_text())["trades"]
        by_id = {r["id"]: r for r in merged}
        assert set(by_id) == {1, 2, 3}
        assert by_id[1]["site"] is True   # volume-only row kept
        assert by_id[2]["site"] is False  # repo wins on id ties
        assert by_id[3]["site"] is False
    print("  PASSED test_list_union_repo_wins_volume_only_kept")


def test_watchlist_union_and_plain_file_wins():
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        vol = Path(tmp) / "vol"
        stage.mkdir()
        vol.mkdir()
        (vol / "watchlist.json").write_text(json.dumps({"items": {"1": {"a": 1}}}))
        (stage / "watchlist.json").write_text(json.dumps({"items": {"2": {"b": 2}}}))
        (vol / "trader_state.json").write_text(json.dumps({"running": True}))
        (stage / "trader_state.json").write_text(json.dumps({"running": False}))
        merge_state.merge_dir(str(stage), str(vol), None)
        wl = json.loads((vol / "watchlist.json").read_text())["items"]
        assert set(wl) == {"1", "2"}
        st = json.loads((vol / "trader_state.json").read_text())
        assert st["running"] is False  # plain files: stage wins
    print("  PASSED test_watchlist_union_and_plain_file_wins")


def test_snapshot_subdir_recursion():
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        vol = Path(tmp) / "vol"
        (stage / "snapshots").mkdir(parents=True)
        (vol / "snapshots").mkdir(parents=True)
        (stage / "snapshots" / "flip-2026-08-01.json").write_text("{}")
        (vol / "snapshots" / "kept.json").write_text("{}")
        merge_state.merge_dir(str(stage), str(vol), None)
        assert (vol / "snapshots" / "flip-2026-08-01.json").exists()
        assert (vol / "snapshots" / "kept.json").exists()
    print("  PASSED test_snapshot_subdir_recursion")


def test_positions_pruned_not_unioned():
    """Closed positions must be pruned from the volume, not unioned back in.

    The trader is the sole writer of open positions, so a volume row for a
    position the trader already closed is a stale ghost. The staged (repo)
    file is the source of truth and replaces the volume wholesale.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        vol = Path(tmp) / "vol"
        stage.mkdir()
        vol.mkdir()
        # Volume has 2 stale open positions (already closed by the trader).
        (vol / "positions.json").write_text(json.dumps({"positions": [
            {"id": 19, "item_id": 9244, "name": "Dragonstone bolts (e)",
             "qty": 531, "buy_price": 373},
            {"id": 20, "item_id": 12934, "name": "Zulrah's scales",
             "qty": 1592, "buy_price": 153},
        ]}))
        # Staged repo file is empty — the trader closed everything.
        (stage / "positions.json").write_text(json.dumps({"positions": []}))
        merge_state.merge_dir(str(stage), str(vol), None)
        merged = json.loads((vol / "positions.json").read_text())["positions"]
        assert merged == [], f"closed positions must be pruned, got {merged}"
    print("  PASSED test_positions_pruned_not_unioned")


def test_positions_stage_wins_on_conflict():
    """A live position present in both copies: staged (trader) row wins."""
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        vol = Path(tmp) / "vol"
        stage.mkdir()
        vol.mkdir()
        (vol / "positions.json").write_text(json.dumps({"positions": [
            {"id": 5, "item_id": 8780, "name": "Teak plank", "qty": 279,
             "buy_price": 724, "site_mutated": True},
        ]}))
        (stage / "positions.json").write_text(json.dumps({"positions": [
            {"id": 5, "item_id": 8780, "name": "Teak plank", "qty": 250,
             "buy_price": 724},
        ]}))
        merge_state.merge_dir(str(stage), str(vol), None)
        merged = json.loads((vol / "positions.json").read_text())["positions"]
        assert len(merged) == 1
        assert merged[0]["qty"] == 250  # trader's row replaces the site's
        assert "site_mutated" not in merged[0]
    print("  PASSED test_positions_stage_wins_on_conflict")


def test_main_requires_args():
    assert merge_state.main([]) == 2
    assert merge_state.main(["missing-dir", "/tmp"]) == 2
    print("  PASSED test_main_requires_args")


if __name__ == "__main__":
    test_list_union_repo_wins_volume_only_kept()
    test_watchlist_union_and_plain_file_wins()
    test_snapshot_subdir_recursion()
    test_positions_pruned_not_unioned()
    test_positions_stage_wins_on_conflict()
    test_main_requires_args()
    print("\nAll merge_state tests passed.")
