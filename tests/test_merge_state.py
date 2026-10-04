"""Tests for the deploy state-merge script."""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deploy"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import merge_state

def dump_fixture(data):
    """Use valid legacy state rows while keeping collision-specific fields."""
    defaults = {
        'trades': {'item_id': 2, 'name': 'fixture', 'qty': 1, 'buy_price': 100,
                   'sell_price': 110, 'tax_paid': 2, 'profit': 8,
                   'timestamp': '2026-01-01T00:00:00Z'},
        'positions': {'item_id': 2, 'name': 'fixture', 'qty': 1, 'buy_price': 100,
                      'direction': 'traditional', 'opened_at': '2026-01-01T00:00:00Z'},
        'alerts': {'ts': 1.0, 'type': 'system', 'severity': 'INFO', 'item_id': None,
                   'item_name': '', 'title': 'fixture', 'message': 'fixture', 'read': False},
    }
    for key, fields in defaults.items():
        if key in data:
            data = {**data, key: [{**fields, **row} for row in data[key]]}
    if 'items' in data:
        data = {**data, 'items': {key: {'name': 'fixture', 'added': '2026-01-01T00:00:00Z', **row}
                                for key, row in data['items'].items()}}
    return json.dumps(data)


def test_list_union_repo_wins_volume_only_kept():
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        vol = Path(tmp) / "vol"
        stage.mkdir()
        vol.mkdir()
        (vol / "trades.json").write_text(dump_fixture({"trades": [
            {"id": 1, "site": True}, {"id": 2, "site": True}]}))
        (stage / "trades.json").write_text(dump_fixture({"trades": [
            {"id": 2, "site": False}, {"id": 3, "site": False}]}))
        merge_state.merge_dir(str(stage), str(vol), None)
        merged = json.loads((vol / "trades.json").read_text())["trades"]
        by_id = {r["id"]: r for r in merged}
        # id 2 collides with DIFFERENT content (Mac and VPS each wrote #2):
        # both survive — the repo row keeps id 2, the volume row is
        # renumbered to a synthetic id (4).
        assert set(by_id) == {1, 2, 3, 4}
        assert by_id[1]["site"] is True   # volume-only row kept
        assert by_id[2]["site"] is False  # repo wins on id ties
        assert by_id[3]["site"] is False
        assert by_id[4]["site"] is True   # collided volume row preserved
        # The renumbered row carries a synthetic id beyond the max real id.
        assert 4 not in {1, 2, 3}
    print("  PASSED test_list_union_repo_wins_volume_only_kept")


def test_trades_collision_preserves_both_rows():
    """A Mac/VPS id collision must keep BOTH trades (renumber the volume row),
    not silently drop one like the old dict-union did."""
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        vol = Path(tmp) / "vol"
        stage.mkdir()
        vol.mkdir()
        (vol / "trades.json").write_text(dump_fixture({"trades": [
            {"id": 5, "source": "vps"}]}))
        (stage / "trades.json").write_text(dump_fixture({"trades": [
            {"id": 5, "source": "mac"}]}))
        merge_state.merge_dir(str(stage), str(vol), None)
        merged = json.loads((vol / "trades.json").read_text())["trades"]
        assert len(merged) == 2, f"collision must keep both, got {merged}"
        assert merged[0]["id"] == 5 and merged[0]["source"] == "mac"  # repo wins id
        assert merged[1]["id"] == 6 and merged[1]["source"] == "vps"  # renumbered
    print("  PASSED test_trades_collision_preserves_both_rows")


def test_watchlist_union_and_plain_file_wins():
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        vol = Path(tmp) / "vol"
        stage.mkdir()
        vol.mkdir()
        (vol / "watchlist.json").write_text(dump_fixture({"items": {"1": {"a": 1}}}))
        (stage / "watchlist.json").write_text(dump_fixture({"items": {"2": {"b": 2}}}))
        (vol / "trader_state.json").write_text(dump_fixture({"running": True}))
        (stage / "trader_state.json").write_text(dump_fixture({"running": False}))
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
        (vol / "positions.json").write_text(dump_fixture({"positions": [
            {"id": 19, "item_id": 9244, "name": "Dragonstone bolts (e)",
             "qty": 531, "buy_price": 373},
            {"id": 20, "item_id": 12934, "name": "Zulrah's scales",
             "qty": 1592, "buy_price": 153},
        ]}))
        # Staged repo file is empty — the trader closed everything.
        (stage / "positions.json").write_text(dump_fixture({"positions": []}))
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
        (vol / "positions.json").write_text(dump_fixture({"positions": [
            {"id": 5, "item_id": 8780, "name": "Teak plank", "qty": 279,
             "buy_price": 724, "site_mutated": True},
        ]}))
        (stage / "positions.json").write_text(dump_fixture({"positions": [
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


def test_alerts_merge_preserves_watch_triggered():
    """The alerts union must keep watch_triggered (max ts wins), not drop it."""
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        vol = Path(tmp) / "vol"
        stage.mkdir()
        vol.mkdir()
        (stage / "alerts.json").write_text(dump_fixture({
            "alerts": [{"id": 1, "ts": 100, "type": "signal"}],
            "watch_triggered": {"561": 200},
        }))
        (vol / "alerts.json").write_text(dump_fixture({
            "alerts": [{"id": 1, "ts": 100, "type": "signal"}],
            "watch_triggered": {"561": 100, "2": 50},
        }))
        merge_state.merge_dir(str(stage), str(vol), None)
        merged = json.loads((vol / "alerts.json").read_text())
        assert merged["watch_triggered"]["561"] == 200  # max ts wins
        assert merged["watch_triggered"]["2"] == 50     # volume-only kept
        assert len(merged["alerts"]) == 1
    print("  PASSED test_alerts_merge_preserves_watch_triggered")


def test_alerts_collision_preserves_both_rows():
    """An alert id collision across machines must keep BOTH alerts, not drop
    the volume-side row (the old dict-union silently lost it)."""
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        vol = Path(tmp) / "vol"
        stage.mkdir()
        vol.mkdir()
        (vol / "alerts.json").write_text(dump_fixture({
            "alerts": [{"id": 3, "source": "vps"}],
            "watch_triggered": {"561": 1},
        }))
        (stage / "alerts.json").write_text(dump_fixture({
            "alerts": [{"id": 3, "source": "mac"}],
            "watch_triggered": {"561": 2},
        }))
        merge_state.merge_dir(str(stage), str(vol), None)
        merged = json.loads((vol / "alerts.json").read_text())
        assert len(merged["alerts"]) == 2, merged
        assert merged["alerts"][0]["source"] == "mac"   # repo wins id 3
        assert merged["alerts"][0]["id"] == 3
        assert merged["alerts"][1]["source"] == "vps"   # volume renumbered
        assert merged["alerts"][1]["id"] == 4
        assert merged["watch_triggered"]["561"] == 2    # max ts wins
    print("  PASSED test_alerts_collision_preserves_both_rows")


def test_corrupt_merge_preserves_every_original():
    from rshelper.persistence import StateCorruptionError
    with tempfile.TemporaryDirectory() as tmp:
        stage, volume = Path(tmp)/'stage', Path(tmp)/'volume'
        stage.mkdir(); volume.mkdir()
        (stage/'trades.json').write_text(dump_fixture({'trades': [{'id': 1}]}))
        (stage/'watchlist.json').write_text('{broken')
        original = dump_fixture({'trades': [{'id': 2}]})
        (volume/'trades.json').write_text(original)
        (volume/'watchlist.json').write_text(dump_fixture({'items': {'4': {}}}))
        before = {path: path.read_bytes() for path in
                  (stage/'trades.json', stage/'watchlist.json', volume/'trades.json', volume/'watchlist.json')}
        try:
            merge_state.merge_dir(str(stage), str(volume), None)
        except StateCorruptionError:
            pass
        else:
            raise AssertionError('corrupt merge must fail')
        assert {path: path.read_bytes() for path in before} == before


def test_merge_accepts_legacy_zero_item_id_trade_on_both_sides():
    with tempfile.TemporaryDirectory() as tmp:
        stage, volume = Path(tmp) / 'stage', Path(tmp) / 'volume'
        stage.mkdir(); volume.mkdir()
        (stage / 'trades.json').write_text(dump_fixture({'trades': [
            {'id': 2, 'item_id': 0, 'name': 'Unknown staged item'}]}))
        (volume / 'trades.json').write_text(dump_fixture({'trades': [
            {'id': 1, 'item_id': 0, 'name': 'Unknown live item'}]}))
        merge_state.merge_dir(str(stage), str(volume), None)
        rows = json.loads((volume / 'trades.json').read_text())['trades']
        assert {row['item_id'] for row in rows} == {0}
        assert {row['name'] for row in rows} == {'Unknown staged item', 'Unknown live item'}


def test_all_merged_json_validates_before_any_destination_replacement():
    from rshelper import persistence
    from rshelper.persistence import StateCorruptionError
    with tempfile.TemporaryDirectory() as tmp:
        stage, volume = Path(tmp) / 'stage', Path(tmp) / 'volume'
        stage.mkdir(); volume.mkdir()
        (stage / '00-state.json').write_text('{"stage_extension":true}')
        original = '{"live_extension":true}'
        (volume / '00-state.json').write_text(original)
        (stage / 'trades.json').write_text(dump_fixture({'trades': [{'id': 2}]}))
        (volume / 'trades.json').write_text(dump_fixture({'trades': [{'id': 1}]}))
        # Either trade file is below this bound, but their merged union is not.
        with mock.patch.object(persistence, 'MAX_STATE_NODES', 16):
            try:
                merge_state.merge_dir(str(stage), str(volume), None)
            except StateCorruptionError:
                pass
            else:
                raise AssertionError('oversized merged output must fail preflight')
        assert (volume / '00-state.json').read_text() == original


def test_destination_corruption_is_preflighted_before_writes():
    from rshelper.persistence import StateCorruptionError
    with tempfile.TemporaryDirectory() as tmp:
        stage, volume = Path(tmp) / 'stage', Path(tmp) / 'volume'
        stage.mkdir(); volume.mkdir()
        incoming = dump_fixture({'trades': [{'id': 1}]})
        original = dump_fixture({'trades': [{'id': 2}]})
        (stage / 'trades.json').write_text(incoming)
        (stage / 'watchlist.json').write_text(dump_fixture({'items': {'3': {}}}))
        (volume / 'trades.json').write_text(original)
        (volume / 'watchlist.json').write_text('{broken')
        try:
            merge_state.merge_dir(str(stage), str(volume), None)
        except StateCorruptionError:
            pass
        else:
            raise AssertionError('corrupt existing destination must fail')
        assert (volume / 'trades.json').read_text() == original
        assert (volume / 'watchlist.json').read_text() == '{broken'


def test_merge_rejects_symlink_escape_without_writes():
    from rshelper.persistence import StateCorruptionError
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        stage, volume = root / 'stage', root / 'volume'
        outside = root / 'outside.json'
        stage.mkdir(); volume.mkdir()
        staged = dump_fixture({'trades': [{'id': 1}]})
        (stage / 'trades.json').write_text(staged)
        outside.write_text('{"trades": []}')
        (volume / 'watchlist.json').symlink_to(outside)
        before = outside.read_bytes()
        try:
            merge_state.merge_dir(str(stage), str(volume), None)
        except (ValueError, OSError, StateCorruptionError):
            pass
        else:
            raise AssertionError('escaping destination symlink must fail')
        assert outside.read_bytes() == before
        assert (volume / 'trades.json').exists() is False


def test_merge_rejects_source_symlink_escape():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        stage, volume = root / 'stage', root / 'volume'
        outside = root / 'outside.json'
        stage.mkdir(); volume.mkdir()
        outside.write_text(dump_fixture({'trades': []}))
        (stage / 'trades.json').symlink_to(outside)
        before = outside.read_bytes()
        try:
            merge_state.merge_dir(str(stage), str(volume), None)
        except (ValueError, OSError):
            pass
        else:
            raise AssertionError('escaping source symlink must fail')
        assert outside.read_bytes() == before
        assert not (volume / 'trades.json').exists()


def test_contained_destination_symlink_remains_contained_and_usable():
    with tempfile.TemporaryDirectory() as tmp:
        stage, volume = Path(tmp) / 'stage', Path(tmp) / 'volume'
        stage.mkdir(); volume.mkdir()
        (stage / 'trades.json').write_text(dump_fixture({'trades': [{'id': 2}]}))
        target = volume / 'current.json'
        target.write_text(dump_fixture({'trades': [{'id': 1}]}))
        alias = volume / 'trades.json'
        alias.symlink_to(target.name)
        merge_state.merge_dir(str(stage), str(volume), None)
        assert alias.is_symlink()
        assert {row['id'] for row in json.loads(target.read_text())['trades']} == {1, 2}


def test_merge_preserves_root_and_row_extensions():
    with tempfile.TemporaryDirectory() as tmp:
        stage, volume = Path(tmp) / 'stage', Path(tmp) / 'volume'
        stage.mkdir(); volume.mkdir()
        source = json.loads(dump_fixture({'trades': [{'id': 2, 'source_ext': {'s': 1}}]}))
        source['source_root_ext'] = {'source': True}
        destination = json.loads(dump_fixture({'trades': [{'id': 1, 'dest_ext': ['keep']}]}))
        destination['dest_root_ext'] = {'destination': True}
        (stage / 'trades.json').write_text(json.dumps(source))
        (volume / 'trades.json').write_text(json.dumps(destination))
        merge_state.merge_dir(str(stage), str(volume), None)
        result = json.loads((volume / 'trades.json').read_text())
        assert result['source_root_ext'] == {'source': True}
        assert result['dest_root_ext'] == {'destination': True}
        rows = {row['id']: row for row in result['trades']}
        assert rows[1]['dest_ext'] == ['keep']
        assert rows[2]['source_ext'] == {'s': 1}


def test_merge_requires_explicit_validation_module_for_cli():
    with tempfile.TemporaryDirectory() as tmp:
        stage, volume = Path(tmp) / 'stage', Path(tmp) / 'volume'
        stage.mkdir(); volume.mkdir()
        module = Path(merge_state.__file__).resolve().parents[1] / 'src/rshelper/persistence.py'
        assert merge_state.main([str(stage), str(volume)]) == 2
        assert merge_state.main([str(stage), str(volume), '--validation-module', str(module)]) == 0


def test_chown_applies_to_shared_lock_sidecars():
    import os
    with tempfile.TemporaryDirectory() as tmp:
        stage, volume = Path(tmp) / 'stage', Path(tmp) / 'volume'
        stage.mkdir(); volume.mkdir()
        (stage / 'trades.json').write_text(dump_fixture({'trades': []}))
        (volume / 'trades.json').write_text(dump_fixture({'trades': []}))
        ownership = f'{os.getuid()}:{os.getgid()}'
        merge_state.merge_dir(str(stage), str(volume), ownership)
        for path in (stage / 'trades.json.lock', volume / 'trades.json.lock'):
            info = path.stat()
            assert (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())


def test_validation_module_equals_syntax():
    with tempfile.TemporaryDirectory() as tmp:
        stage, volume = Path(tmp) / 'stage', Path(tmp) / 'volume'
        stage.mkdir(); volume.mkdir()
        (stage / 'trades.json').write_text(dump_fixture({'trades': []}))
        module = Path(merge_state.__file__).resolve().parents[1] / 'src/rshelper/persistence.py'
        assert merge_state.main([str(stage), str(volume), '--validation-module=' + str(module)]) == 0


if __name__ == "__main__":
    checks = [(name, test) for name, test in sorted(globals().items())
              if name.startswith('test_') and callable(test)]
    for _, test in checks:
        test()
    print(f"\nAll {len(checks)} merge_state tests passed.")
