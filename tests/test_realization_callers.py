"""Caller routing, batch preflight and retry pinning for recoverable closes."""
import contextlib
import copy
import json
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rshelper import journal, positions, realization, state_identity
from rshelper.persistence import canonical_uuid

ORIGIN = "11111111-1111-4111-8111-111111111111"
OP = "22222222-2222-4222-8222-222222222222"
OP2 = "33333333-3333-4333-8333-333333333333"
LOT_OP = "44444444-4444-4444-8444-444444444444"

FIXTURE_ROWS = [
    {"id": 1, "item_id": 561, "name": "Nature rune", "qty": 10, "buy_price": 100,
     "direction": "traditional", "opened_at": "2026-01-01T00:00:00Z"},
    {"id": 2, "item_id": 561, "name": "Nature rune", "qty": 7, "buy_price": 130,
     "direction": "arbitrage", "opened_at": "2026-01-01T00:01:00Z"},
]


def _trade_uuid(operation_id):
    return str(__import__("uuid").uuid5(__import__("uuid").UUID(ORIGIN), operation_id))


class BatchEngineTest(unittest.TestCase):
    @contextlib.contextmanager
    def routed(self, activate=False):
        api = realization
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows, manifest = state_identity.migrate_rows(
                copy.deepcopy(FIXTURE_ROWS), "positions", state_identity.new_manifest(ORIGIN))
            (root / "positions.json").write_text(json.dumps({"positions": rows}))
            (root / "trades.json").write_text('{"trades":[]}')
            (root / "identity-manifest.json").write_text(json.dumps(manifest))
            if activate:
                (root / "identity-activation.json").write_text(json.dumps(
                    {"schema_version": 1, "origin_uuid": ORIGIN,
                     "mode": "identified", "financial_authority": True}))
            with contextlib.ExitStack() as stack:
                for patch in (
                        mock.patch.object(positions, "POSITIONS_PATH", root / "positions.json"),
                        mock.patch.object(journal, "TRADES_PATH", root / "trades.json"),
                        mock.patch.object(api, "_intent_path", return_value=root / "realizations.json"),
                        mock.patch.object(api, "_manifest_path", return_value=root / "identity-manifest.json")):
                    stack.enter_context(patch)
                yield root, rows

    def test_retry_after_response_loss_uses_pinned_quote(self):
        api = realization
        with self.routed() as (root, rows):
            receipt = api.close_and_realize("default", rows[0]["lot_uid"], 4, 120, OP, "manual")
            self.assertFalse(receipt["replayed"])
            raw = json.loads((root / "trades.json").read_text())["trades"]
            self.assertEqual(len(raw), 1)
            original_uuid = raw[0]["record_uuid"]
            self.assertEqual((raw[0]["qty"], raw[0]["buy_price"], raw[0]["sell_price"]), (4, 100, 120))
            with self.assertRaisesRegex(ValueError, "different economics"):
                api.close_and_realize("default", rows[0]["lot_uid"], 4, 150, OP, "manual")
            replay = api.close_and_realize("default", rows[0]["lot_uid"], 4, 120, OP, "manual")
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["trade_uuids"], [original_uuid])
            trades = journal.list_trades()
            self.assertEqual(len(trades), 1)
            remaining = [p for p in json.loads((root / "positions.json").read_text())["positions"]
                         if p["record_uuid"] == rows[0]["record_uuid"]]
            self.assertEqual(remaining[0]["qty"], 6)

    def test_prepare_batch_persists_children_before_any_apply(self):
        api = realization
        with self.routed(activate=True) as (root, rows):
            plan = api.prepare_close_batch("default", 561, 12, OP, {
                "traditional": 120, "arbitrage": 140})
            self.assertEqual(len(plan["operations"]), 2)
            self.assertEqual(sum(entry["qty"] for entry in plan["operations"]), 12)
            for entry in plan["operations"]:
                canonical_uuid(entry["operation_id"])
            pinned = json.loads((root / "realizations.json").read_text())
            self.assertEqual(len(pinned["operations"]), 2)
            for entry in pinned["operations"].values():
                self.assertFalse(entry["done"])
            self.assertEqual(len(journal.list_trades()), 0)
            receipt = api.realize_close_batch("default", OP)
            self.assertEqual(len(receipt["receipts"]), 2)
            trades = journal.list_trades()
            self.assertEqual({trade.buy_price for trade in trades}, {100, 130})
            all_rows = json.loads((root / "positions.json").read_text())["positions"]
            quantities = {p["record_uuid"]: p["qty"] for p in all_rows if not p.get("tombstone")}
            self.assertNotIn(rows[0]["record_uuid"], quantities)
            self.assertEqual(quantities[rows[1]["record_uuid"]], 5)

    def test_manual_batch_insufficient_qty_writes_nothing(self):
        api = realization
        with self.routed(activate=True) as (root, rows):
            before = ((root / "positions.json").read_bytes(), (root / "trades.json").read_bytes())
            with self.assertRaises(ValueError):
                api.prepare_close_batch("default", 561, 25, OP, {
                    "traditional": 120, "arbitrage": 140})
            self.assertEqual(((root / "positions.json").read_bytes(), (root / "trades.json").read_bytes()), before)
            self.assertFalse((root / "realizations.json").exists())

    def test_batch_replay_uses_pinned_quote_after_restart(self):
        api = realization
        with self.routed(activate=True) as (root, rows):
            api.prepare_close_batch("default", 561, 10, OP, {
                "traditional": 120})
            with self.assertRaisesRegex(ValueError, "different economics"):
                api.prepare_close_batch("default", 561, 10, OP, {
                    "traditional": 150})
            api.recover_pending("default")
            receipt = api.realize_close_batch("default", OP)
            self.assertTrue(all(row["replayed"] or row.get("applied") for row in receipt["receipts"])
                            or len(receipt["receipts"]) == 1)
            trades = journal.list_trades()
            self.assertEqual([(trade.qty, trade.sell_price) for trade in trades], [(10, 120)])

    def test_auto_exit_closes_selected_uuid_not_fifo(self):
        api = realization
        with self.routed(activate=True) as (root, rows):
            plan = api.prepare_close_batch("default", 561, 3, OP, {
                "arbitrage": 140}, lot_uids=[rows[1]["lot_uid"]])
            api.realize_close_batch("default", OP)
            trades = journal.list_trades()
            raw = json.loads((root / "trades.json").read_text())["trades"]
            self.assertEqual([trade.buy_price for trade in trades], [130])
            self.assertEqual(raw[0]["closed_lot_uid"], plan["operations"][0]["lot_uid"])

    def test_mixed_direction_batch_restart_preserves_cost_basis(self):
        api = realization
        with self.routed(activate=True) as (root, rows):
            api.prepare_close_batch("default", 561, 12, OP, {
                "traditional": 120, "arbitrage": 140})
            def crash(step):
                if step == "journal":
                    raise RuntimeError("injected crash")
            with mock.patch.object(api, "_checkpoint", side_effect=crash):
                with self.assertRaisesRegex(RuntimeError, "injected crash"):
                    api.realize_close_batch("default", OP)
            api.recover_pending("default")
            api.realize_close_batch("default", OP)
            trades = journal.list_trades()
            self.assertEqual(sorted((trade.buy_price, trade.sell_price) for trade in trades),
                             [(100, 120), (130, 140)])
            self.assertEqual(len(trades), 2)
            all_rows = json.loads((root / "positions.json").read_text())["positions"]
            quantities = {p["record_uuid"]: p["qty"] for p in all_rows if not p.get("tombstone")}
            self.assertNotIn(rows[0]["record_uuid"], quantities)
            self.assertEqual(quantities[rows[1]["record_uuid"]], 5)

    def test_concurrent_manual_auto_close_conserves_units(self):
        api = realization
        with self.routed(activate=True) as (root, rows):
            errors = []

            def manual():
                try:
                    plan = api.prepare_close_batch("default", 561, 4, OP, {
                        "traditional": 120}, lot_uids=[rows[0]["lot_uid"]])
                    api.realize_close_batch("default", OP)
                except Exception as exc:
                    errors.append(exc)

            def automated():
                try:
                    plan = api.prepare_close_batch("default", 561, 3, OP2, {
                        "arbitrage": 140}, lot_uids=[rows[1]["lot_uid"]])
                    api.realize_close_batch("default", OP2)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=manual), threading.Thread(target=automated)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertEqual(errors, [])
            trades = journal.list_trades()
            self.assertEqual(sum(trade.qty for trade in trades), 7)
            active = [p for p in json.loads((root / "positions.json").read_text())["positions"]
                      if not p.get("tombstone")]
            self.assertEqual(sum(p["qty"] for p in active), 10)

    def test_prepare_requires_activation_and_canonical_operation(self):
        api = realization
        with self.routed() as (root, rows):
            with self.assertRaisesRegex(ValueError, "identified profile"):
                api.prepare_close_batch("default", 561, 1, OP, {
                    "traditional": 120})
        with self.routed(activate=True) as (root, rows):
            with self.assertRaises(ValueError):
                api.prepare_close_batch("default", 561, 1, "not-a-uuid", {
                    "traditional": 120})


class CallerRoutingTest(unittest.TestCase):
    @contextlib.contextmanager
    def routed(self):
        api = realization
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows, manifest = state_identity.migrate_rows(
                copy.deepcopy(FIXTURE_ROWS), "positions", state_identity.new_manifest(ORIGIN))
            (root / "positions.json").write_text(json.dumps({"positions": rows}))
            (root / "trades.json").write_text('{"trades":[]}')
            (root / "identity-manifest.json").write_text(json.dumps(manifest))
            (root / "identity-activation.json").write_text(json.dumps(
                {"schema_version": 1, "origin_uuid": ORIGIN,
                 "mode": "identified", "financial_authority": True}))
            with contextlib.ExitStack() as stack:
                for patch in (
                        mock.patch.object(positions, "POSITIONS_PATH", root / "positions.json"),
                        mock.patch.object(journal, "TRADES_PATH", root / "trades.json"),
                        mock.patch.object(api, "_intent_path", return_value=root / "realizations.json"),
                        mock.patch.object(api, "_manifest_path", return_value=root / "identity-manifest.json")):
                    stack.enter_context(patch)
                yield root, rows

    def test_cli_close_routes_selected_lot_through_realization(self):
        from rshelper import cli as cmod
        from argparse import Namespace
        with self.routed() as (root, rows):
            with mock.patch.object(cmod, "_resolve_item",
                                   return_value={"id": 561, "name": "Nature rune"}),                     mock.patch.object(cmod, "_resolve_paper_prices",
                                      side_effect=lambda entry, profile, direction: (
                                          150, 140, {"source": "wiki", "delivery": "network",
                                                     "stale": False, "fetched_at": None,
                                                     "last_success_at": None,
                                                     "last_attempt_at": None})):
                cmod._trade_close(Namespace(item="nature rune", qty=0, profile=None,
                                            operation_id=None))
            trades = journal.list_trades()
            raw = json.loads((root / "trades.json").read_text())["trades"]
            self.assertEqual(len(trades), 2)
            parent_op = str(uuid.uuid5(uuid.UUID(ORIGIN), "trade:close:561"))
            by_lot = {row["closed_lot_uid"]: row for row in raw}
            self.assertEqual(set(by_lot), {rows[0]["lot_uid"], rows[1]["lot_uid"]})
            for row in raw:
                child_op = str(uuid.uuid5(uuid.UUID(parent_op),
                                          "close:" + row["closed_lot_uid"]))
                self.assertEqual(row["operation_id"], child_op)
                self.assertEqual(row["record_uuid"],
                                 str(uuid.uuid5(uuid.UUID(ORIGIN), child_op)))
                self.assertEqual(row["strategy"], "manual")
            self.assertEqual(sum(row["qty"] for row in raw), 17)
            active = [p for p in json.loads((root / "positions.json").read_text())["positions"]
                      if not p.get("tombstone")]
            self.assertEqual(active, [])

    def test_cli_operation_id_pins_children(self):
        from rshelper import cli as cmod
        from argparse import Namespace
        with self.routed() as (root, rows):
            with mock.patch.object(cmod, "_resolve_item",
                                   return_value={"id": 561, "name": "Nature rune"}),                  mock.patch.object(cmod, "_resolve_paper_prices",
                                   side_effect=lambda entry, profile, direction: (150, 140, {"source": "wiki", "delivery": "network", "stale": False, "fetched_at": None, "last_success_at": None, "last_attempt_at": None})):
                cmod._trade_close(Namespace(item="nature rune", qty=0, profile=None, operation_id=LOT_OP))
            raw = json.loads((root / "trades.json").read_text())["trades"]
            self.assertEqual(raw[0]["operation_id"], str(__import__("uuid").uuid5(
                __import__("uuid").UUID(LOT_OP), "close:" + rows[0]["lot_uid"])))

    def test_cli_rejects_malformed_operation_before_writes(self):
        from rshelper import cli as cmod
        from argparse import Namespace
        with self.routed() as (root, rows):
            with mock.patch.object(cmod, "_resolve_item",
                                   return_value={"id": 561, "name": "Nature rune"}):
                with self.assertRaises(SystemExit):
                    cmod._trade_close(Namespace(item="nature rune", qty=0, profile=None, operation_id="bogus"))
            self.assertEqual(journal.list_trades(), [])
            self.assertFalse((root / "realizations.json").exists())

    def test_ge_collect_routes_exact_lot_and_replays(self):
        from rshelper import ge_offers
        latest = {"561": {"high": 150, "low": 140, "highTime": 0, "lowTime": 0}}
        now = __import__("time").time()
        latest["561"]["highTime"] = int(now) - 30
        latest["561"]["lowTime"] = int(now) - 30
        with self.routed() as (root, rows):
            frozen = str(__import__("uuid").uuid4())
            with mock.patch.object(ge_offers, "close_market_price", return_value=140),                     mock.patch.object(__import__("rshelper.realization", fromlist=["new_operation_id"]),
                                      "new_operation_id", side_effect=[frozen]):
                result = ge_offers.collect_offer(rows[0]["id"], latest=latest)
            self.assertTrue(result["ok"])
            trades = journal.list_trades()
            raw = json.loads((root / "trades.json").read_text())["trades"]
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0].strategy, "ge_collect")
            self.assertEqual(raw[0]["closed_lot_uid"], rows[0]["lot_uid"])
            again = ge_offers.collect_offer(rows[0]["id"], latest=latest, operation_id=frozen)
            self.assertTrue(again["ok"])
            self.assertEqual(len(journal.list_trades()), 1)

    def test_trader_exit_routes_through_identified_writer(self):
        from rshelper import trader as tmod
        from rshelper.config import TraderConfig
        cfg = TraderConfig(capital=1_000_000, trade_capital_frac=0.40, max_positions=3,
                           min_volume=800, min_price=25, max_spread_ratio=5.0,
                           dip_depth_pct=2.5, max_dip_pct=10.0, min_spread_pct=3.5,
                           max_entry_spread_pct=5.75, reentry_minutes=30,
                           stop_reentry_minutes=90, take_profit_pct=3.0,
                           stop_loss_pct=-2.0, stop_grace_minutes=0,
                           max_hold_minutes=180, spread_collapse_exit_minutes=60,
                           interval_sec=120, stop_slippage=0.97, stop_mark_blend=0.0)
        with self.routed() as (root, rows):
            auto_row = dict(rows[0])
            auto_row["note"] = "auto"
            store = json.loads((root / "positions.json").read_text())
            store["positions"] = [auto_row]
            (root / "positions.json").write_text(json.dumps(store))
            now = int(__import__("time").time())
            latest = {"561": {"high": 100, "low": 80, "highTime": now - 30, "lowTime": now - 30}}
            vol_5m = {"561": {"avgLowPrice": 100, "lowPriceVolume": 5, "highPriceVolume": 5000}}
            from rshelper.market_data import MarketDataResult, market_payload
            wiki_vol = market_payload(MarketDataResult(vol_5m, "wiki", "network", 100, 100, 100,
                                                       False, "executed-trades", {"wiki": 1}))
            import rshelper.cli as cmod
            with mock.patch.object(cmod, "_fetch_bootstrap",
                                   return_value=({}, latest, wiki_vol, [])):
                result = tmod.run_cycle(cfg, profile=None)
            self.assertEqual(len(result["closed"]), 1)
            trades = journal.list_trades()
            raw = json.loads((root / "trades.json").read_text())["trades"]
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0].strategy, "auto")
            self.assertEqual(raw[0]["closed_lot_uid"], rows[0]["lot_uid"])
            parent_op = str(uuid.uuid5(uuid.UUID(ORIGIN), "trade:auto:" + rows[0]["lot_uid"]))
            child_op = str(uuid.uuid5(uuid.UUID(parent_op), "close:" + rows[0]["lot_uid"]))
            self.assertEqual(raw[0]["operation_id"], child_op)
            self.assertEqual(raw[0]["record_uuid"], str(uuid.uuid5(uuid.UUID(ORIGIN), child_op)))
            store_rows = json.loads((root / "positions.json").read_text())["positions"]
            active = [p for p in store_rows if not p.get("tombstone")]
            self.assertEqual(active, [])
            closed_rows = [p for p in store_rows if p.get("tombstone")]
            self.assertEqual(len(closed_rows), 1)
            self.assertEqual(closed_rows[0]["record_uuid"], rows[0]["record_uuid"])




class DashboardCloseRoutingTest(unittest.TestCase):
    """The dashboard manual close routes identified lots through pinned batches."""

    def _latest(self, high=120, low=90):
        now = int(__import__("time").time())
        return {"561": {"high": high, "low": low,
                        "highTime": now - 30, "lowTime": now - 30}}

    def test_dashboard_close_routes_through_identified_batch(self):
        from rshelper.dashboard import server as dash
        from rshelper.market import ge_tax
        with BatchEngineTest.routed(self, activate=True) as (root, rows):
            result = dash.identified_position_close(
                "default", rows[0]["id"], None, self._latest())
            self.assertTrue(result["ok"])
            parent_op = str(uuid.uuid5(uuid.UUID(ORIGIN),
                                       "dash:close:" + str(rows[0]["id"])))
            child_op = str(uuid.uuid5(uuid.UUID(parent_op),
                                      "close:" + rows[0]["lot_uid"]))
            expected_uuid = str(uuid.uuid5(uuid.UUID(ORIGIN), child_op))
            self.assertEqual(result["operation_id"], parent_op)
            self.assertEqual(result["trade_uuids"], [expected_uuid])
            self.assertEqual(result["qty"], 10)
            self.assertEqual(result["sell_price"], 120)
            self.assertEqual(result["profit"], (120 - 100) * 10 - ge_tax(120) * 10)
            self.assertFalse(result["closed_at_entry"])
            raw = json.loads((root / "trades.json").read_text())["trades"]
            self.assertEqual(len(raw), 1)
            self.assertEqual(raw[0]["operation_id"], child_op)
            self.assertEqual(raw[0]["record_uuid"], expected_uuid)
            self.assertEqual(raw[0]["closed_lot_uid"], rows[0]["lot_uid"])
            self.assertEqual(raw[0]["strategy"], "manual")
            self.assertEqual(raw[0]["exit_reason"], "manual")
            self.assertEqual(raw[0]["qty"], 10)
            self.assertEqual(raw[0]["buy_price"], 100)
            self.assertEqual(raw[0]["sell_price"], 120)
            self.assertEqual(raw[0]["tax_paid"], ge_tax(120) * 10)
            store_rows = json.loads((root / "positions.json").read_text())["positions"]
            active = [p for p in store_rows if not p.get("tombstone")]
            self.assertEqual([p["record_uuid"] for p in active],
                             [rows[1]["record_uuid"]])
            # A retry after a lost response replays the pinned economics even
            # when the live quote has moved and the position is consumed.
            replay = dash.identified_position_close(
                "default", rows[0]["id"], None,
                self._latest(high=200, low=10),
                operation_id=result["operation_id"])
            self.assertEqual(replay["operation_id"], result["operation_id"])
            self.assertEqual(replay["trade_uuids"], [expected_uuid])
            self.assertEqual(replay["qty"], 10)
            self.assertEqual(replay["sell_price"], 120)
            self.assertEqual(len(journal.list_trades()), 1)

    def test_dashboard_close_malformed_operation_id_is_refused(self):
        from rshelper.dashboard import server as dash
        with BatchEngineTest.routed(self, activate=True) as (root, rows):
            with self.assertRaisesRegex(ValueError, "canonical UUID"):
                dash.identified_position_close(
                    "default", rows[0]["id"], None, self._latest(),
                    operation_id="not-a-uuid")
            self.assertEqual(json.loads((root / "trades.json").read_text())["trades"], [])
            self.assertFalse((root / "realizations.json").exists())

    def test_dashboard_close_unpinned_operation_id_pins_fresh_request(self):
        from rshelper.dashboard import server as dash
        with BatchEngineTest.routed(self, activate=True) as (root, rows):
            # A browser retry whose first request never arrived has a UUID the
            # server has never seen: it must pin a fresh close under that id
            # instead of failing with unknown batch.
            result = dash.identified_position_close(
                "default", rows[0]["id"], None, self._latest(),
                operation_id=OP2)
            self.assertTrue(result["ok"])
            self.assertEqual(result["operation_id"], OP2)
            child_op = str(uuid.uuid5(uuid.UUID(OP2),
                                      "close:" + rows[0]["lot_uid"]))
            raw = json.loads((root / "trades.json").read_text())["trades"]
            self.assertEqual(len(raw), 1)
            self.assertEqual(raw[0]["operation_id"], child_op)
            replay = dash.identified_position_close(
                "default", rows[0]["id"], None, self._latest(high=1, low=1),
                operation_id=OP2)
            self.assertEqual(replay["trade_uuids"], result["trade_uuids"])
            self.assertEqual(len(journal.list_trades()), 1)

    def test_dashboard_close_legacy_profile_keeps_fifo_path(self):
        from rshelper.dashboard import server as dash
        with BatchEngineTest.routed(self) as (root, rows):
            before = ((root / "positions.json").read_bytes(),
                      (root / "trades.json").read_bytes())
            result = dash.identified_position_close(
                "default", rows[0]["id"], None, self._latest())
            self.assertIsNone(result)
            self.assertEqual(((root / "positions.json").read_bytes(),
                              (root / "trades.json").read_bytes()), before)
            self.assertFalse((root / "realizations.json").exists())


if __name__ == "__main__":
    unittest.main()
