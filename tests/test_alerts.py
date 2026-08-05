"""Tests for the persistent alert feed (rshelper.alerts)."""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, "src")

import rshelper.alerts as amod
import rshelper.profile as pmod


class TestAlerts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path("/tmp/rshelper-test-alerts-%d" % os.getpid())
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        self._old_config = pmod.CONFIG_DIR
        pmod.CONFIG_DIR = self.tmp
        pmod.ACTIVE_PROFILE_PATH = self.tmp / "active_profile"

    def tearDown(self):
        import shutil
        pmod.CONFIG_DIR = self._old_config
        pmod.ACTIVE_PROFILE_PATH = self._old_config / "active_profile"
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_push_and_list(self):
        amod.push_alert("signal", "HIGH", 4151, "Abyssal whip",
                        "CRASH", "Abyssal whip: -25.0% vs 5m avg")
        feed = amod.list_alerts(profile="default")
        self.assertEqual(len(feed), 1)
        a = feed[0]
        self.assertEqual(a.type, "signal")
        self.assertEqual(a.item_id, 4151)
        self.assertEqual(a.item_name, "Abyssal whip")
        self.assertFalse(a.read)

    def test_newest_first(self):
        for i in range(5):
            amod.push_alert("system", "INFO", None, "", f"t{i}", f"m{i}")
        feed = amod.list_alerts(profile="default")
        self.assertEqual(len(feed), 5)
        self.assertEqual(feed[0].title, "t4")

    def test_limit(self):
        for i in range(10):
            amod.push_alert("system", "INFO", None, "", f"t{i}", "m")
        feed = amod.list_alerts(limit=3, profile="default")
        self.assertEqual(len(feed), 3)

    def test_mark_read_all(self):
        for i in range(3):
            amod.push_alert("system", "INFO", None, "", f"t{i}", "m")
        self.assertEqual(amod.unread_count(profile="default"), 3)
        changed = amod.mark_read(all=True, profile="default")
        self.assertEqual(changed, 3)
        self.assertEqual(amod.unread_count(profile="default"), 0)
        # Idempotent
        self.assertEqual(amod.mark_read(all=True, profile="default"), 0)

    def test_mark_read_ids(self):
        amod.push_alert("system", "INFO", None, "", "t0", "m")
        amod.push_alert("system", "INFO", None, "", "t1", "m")
        feed = amod.list_alerts(profile="default")
        first_id = feed[-1].id  # oldest
        changed = amod.mark_read(ids=[first_id], profile="default")
        self.assertEqual(changed, 1)
        self.assertEqual(amod.unread_count(profile="default"), 1)

    def test_prune_cap(self):
        for i in range(250):
            amod.push_alert("system", "INFO", None, "", f"t{i}", "m")
        feed = amod.list_alerts(limit=1000, profile="default")
        self.assertLessEqual(len(feed), 200)

    def test_watch_dedupe(self):
        self.assertFalse(amod.watch_triggered(4151, profile="default"))
        amod.set_watch_triggered(4151, profile="default")
        self.assertTrue(amod.watch_triggered(4151, profile="default"))

    def test_profile_isolation(self):
        amod.push_alert("system", "INFO", None, "", "default-alert", "m",
                        profile="default")
        amod.push_alert("system", "INFO", None, "", "alt-alert", "m",
                        profile="alt")
        d = amod.list_alerts(profile="default")
        a = amod.list_alerts(profile="alt")
        self.assertEqual([x.title for x in d], ["default-alert"])
        self.assertEqual([x.title for x in a], ["alt-alert"])

    def test_corrupt_file_recovers(self):
        path = amod._alerts_path("default")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        amod.push_alert("system", "INFO", None, "", "ok", "m")
        feed = amod.list_alerts(profile="default")
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0].title, "ok")

    def test_persists_across_reload(self):
        amod.push_alert("trader", "HIGH", 1, "Nature rune", "take_profit",
                        "+3,000 gp")
        # Fresh load from disk (the in-memory lock is per-process, so a
        # second module reference proves file persistence).
        import importlib
        reloaded = importlib.reload(amod)
        feed = reloaded.list_alerts(profile="default")
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0].type, "trader")

    def test_push_failure_is_silent(self):
        # Unwritable dir: push must not raise.
        self.tmp.mkdir(parents=True, exist_ok=True)
        os.chmod(self.tmp, 0o500)
        try:
            a = amod.push_alert("system", "INFO", None, "", "x", "y",
                                profile="default")
            self.assertEqual(a.title, "x")
        finally:
            os.chmod(self.tmp, 0o700)

    def test_ids_are_monotonic_across_pushes(self):
        """ids derive from max(persisted)+1 so cross-process pushes never collide."""
        amod.push_alert("system", "INFO", None, "", "a", "m")
        amod.push_alert("system", "INFO", None, "", "b", "m")
        feed = amod.list_alerts(profile="default")
        ids = sorted(a.id for a in feed)
        self.assertEqual(ids, [1, 2])
        self.assertEqual(len(set(ids)), len(ids))

    def test_update_watch_alerts_preserves_entry(self):
        from rshelper import watchlist
        watchlist.add(561, "Nature rune", alert_margin_above=100)
        amod.set_watch_triggered(561, profile="default")
        amod.update_watch_alerts(561, 250, None, profile="default")
        entry = watchlist.load()["items"]["561"]
        self.assertEqual(entry["alert_margin_above"], 250)
        self.assertEqual(entry["alert_margin_below"], None)
        self.assertEqual(entry["name"], "Nature rune")
        self.assertFalse(amod.watch_triggered(561, profile="default"),
                         "a new threshold must clear the old dedupe")

    def test_update_watch_alerts_unknown_raises(self):
        with self.assertRaises(ValueError):
            amod.update_watch_alerts(99999, 1, None, profile="default")

    def test_dashboard_boot_failure_pushes_system_alert(self):
        """A failed initial fetch must surface a system alert, not just stderr."""
        from unittest import mock
        import rshelper.dashboard.server as smod
        with mock.patch.object(smod, "_fetch_bootstrap", side_effect=SystemExit), \
             mock.patch.object(smod.ThreadingHTTPServer, "serve_forever",
                               side_effect=KeyboardInterrupt):
            smod.run(bind="127.0.0.1", port=0)
        feed = amod.list_alerts(profile="default")
        sys_types = [a for a in feed if a.type == "system"]
        self.assertGreaterEqual(len(sys_types), 1)
        self.assertIn("Data source unavailable", sys_types[0].title)

    def test_cross_process_lock_prevents_id_collision(self):
        """Two processes pushing alerts must not collide on ids (flock)."""
        import subprocess
        import os
        code = (
            "import sys; sys.path.insert(0,'src');"
            "from rshelper.alerts import push_alert;"
            "push_alert('system','INFO',None,'','p','m',profile='default')"
        )
        procs = [subprocess.Popen([sys.executable, "-c", code],
                                  cwd=os.getcwd(),
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
                 for _ in range(4)]
        for p in procs:
            p.wait(timeout=30)
        feed = amod.list_alerts(limit=100, profile="default")
        ids = [a.id for a in feed if a.title == "p"]
        self.assertEqual(len(ids), len(set(ids)), f"colliding ids: {ids}")
        # cleanup
        for a in feed:
            if a.title == "p":
                amod.mark_read(ids=[a.id], profile="default")


if __name__ == "__main__":
    unittest.main(verbosity=2)
