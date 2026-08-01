"""Tests for the history builder."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rshelper import history, profile, snapshot
from rshelper import journal as jmod
from rshelper import tuning as tmod


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._trades = jmod.TRADES_PATH
        self._snap = snapshot.SNAPSHOT_DIR
        self._cfg = profile.CONFIG_DIR
        self._active = profile.ACTIVE_PROFILE_PATH
        jmod.TRADES_PATH = self.tmp / "trades.json"
        snapshot.SNAPSHOT_DIR = self.tmp / "snapshots"
        profile.CONFIG_DIR = self.tmp
        profile.ACTIVE_PROFILE_PATH = self.tmp / "active_profile"

    def tearDown(self):
        jmod.TRADES_PATH = self._trades
        snapshot.SNAPSHOT_DIR = self._snap
        profile.CONFIG_DIR = self._cfg
        profile.ACTIVE_PROFILE_PATH = self._active

    def _write_entries(self, entries):
        path = tmod.log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"entries": entries}))

    def test_empty_history(self):
        h = history.build_history()
        self.assertEqual(h["buckets"], [])
        self.assertEqual(h["eras"], [])
        self.assertEqual(h["summary"]["trade_count"], 0)

    def test_cumulative_buckets_and_paper_filter(self):
        jmod.log_trade(1, "A", 1, 100, 200, "paper")
        jmod.log_trade(2, "B", 1, 100, 200, "")
        h = history.build_history(paper_only=True)
        self.assertEqual(h["summary"]["trade_count"], 1)
        self.assertEqual(len(h["buckets"]), 1)
        self.assertEqual(h["buckets"][0]["profit"], 96)
        self.assertEqual(h["buckets"][0]["cumulative_profit"], 96)
        h_all = history.build_history(paper_only=False)
        self.assertEqual(h_all["summary"]["trade_count"], 2)

    def test_config_assignment_and_change_flags(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        self._write_entries([
            {"ts": f"{yesterday}T10:00:00Z", "params": {"v": 1}, "note": "auto"},
            {"ts": f"{today}T10:00:00Z", "params": {"v": 2}, "note": "auto"},
        ])
        jmod.log_trade(1, "A", 1, 100, 200, "paper")
        h = history.build_history()
        self.assertEqual(h["buckets"][0]["date"], today)
        self.assertTrue(h["buckets"][0]["config_changed"])
        self.assertEqual(h["buckets"][0]["config"], {"v": 2})

    def test_snapshot_join(self):
        snapshot.save("flip", [
            {"item_id": 1, "name": "A", "profit": 100},
            {"item_id": 2, "name": "B", "profit": 300},
        ])
        h = history.build_history()
        self.assertEqual(len(h["buckets"]), 1)
        self.assertEqual(h["buckets"][0]["date"], date.today().isoformat())
        snaps = h["buckets"][0]["snapshots"]
        self.assertEqual(snaps[0]["scan_type"], "flip")
        self.assertEqual(snaps[0]["count"], 2)
        self.assertEqual(snaps[0]["avg_value"], 200)

    def test_eras_split_trades(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        self._write_entries([
            {"ts": f"{yesterday}T10:00:00Z", "params": {"v": 1}, "note": "auto"},
            {"ts": f"{today}T10:00:00Z", "params": {"v": 2}, "note": "auto"},
        ])
        jmod.log_trade(1, "A", 1, 100, 200, "paper")
        h = history.build_history()
        self.assertEqual(len(h["eras"]), 2)
        last = h["eras"][-1]
        self.assertEqual(last["config"], {"v": 2})
        self.assertGreaterEqual(last["trade_count"], 1)

    def test_final_era_includes_last_day(self):
        """Trades on the last traded day must appear in the final era."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        self._write_entries([
            {"ts": f"{yesterday}T10:00:00Z", "params": {"v": 1}, "note": "auto"},
        ])
        jmod.log_trade(1, "A", 1, 100, 200, "paper")
        h = history.build_history()
        self.assertEqual(len(h["eras"]), 1)
        self.assertEqual(h["eras"][0]["trade_count"], 1)
        self.assertGreater(h["eras"][0]["profit"], 0)

    def test_same_day_entries_do_not_overlap(self):
        """Two tuning entries on one day must not double-count trades."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        day2 = (now - timedelta(days=2)).strftime("%Y-%m-%d")
        day1 = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        today = now.strftime("%Y-%m-%d")
        self._write_entries([
            {"ts": f"{day2}T08:00:00Z", "params": {"v": 1}, "note": "auto"},
            {"ts": f"{day2}T10:00:00Z", "params": {"v": 2}, "note": "auto"},
        ])

        def _mk(iid, day):
            return {"id": iid, "item_id": iid, "name": f"I{iid}", "qty": 1,
                    "buy_price": 100, "sell_price": 200, "tax_paid": 4,
                    "profit": 96, "timestamp": f"{day}T12:00:00Z",
                    "note": "paper", "strategy": "manual", "exit_reason": "",
                    "hold_minutes": None, "quote_sell": None}

        jmod._save([_mk(1, day2), _mk(2, day1), _mk(3, today)])
        h = history.build_history()
        self.assertEqual(len(h["eras"]), 2)
        total = sum(e["trade_count"] for e in h["eras"])
        self.assertEqual(total, 3, "eras must partition trades without overlap")
        # The earlier same-day entry is degenerate: the later entry owns the
        # whole day (consistent with config_at's "last entry wins").
        self.assertEqual(h["eras"][0]["trade_count"], 0)
        self.assertEqual(h["eras"][1]["trade_count"], 3)

    def test_malformed_snapshot_skipped(self):
        """Snapshot files with non-date names must be skipped, not crash."""
        snap_dir = snapshot.SNAPSHOT_DIR
        snap_dir.mkdir(parents=True, exist_ok=True)
        (snap_dir / "garbage-name.json").write_text(
            json.dumps({"count": 1, "items": []}))
        (snap_dir / "flip-2026-07-31.json").write_text(json.dumps({
            "scan_type": "flip", "count": 2,
            "items": [{"item_id": 1, "profit": 100},
                      {"item_id": 2, "profit": 200}]}))
        h = history.build_history()
        bucket_days = {b["date"] for b in h["buckets"]}
        self.assertIn("2026-07-31", bucket_days)
        self.assertTrue(all(len(d) == 10 for d in bucket_days),
                        f"phantom days leaked into buckets: {bucket_days}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
