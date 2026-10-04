"""Profile names and filenames cannot escape their selected roots."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import profile


class TestProfileSecurity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / 'config'
        self.cache = self.root / 'cache'
        for key, value in [('CONFIG_DIR', self.config), ('CACHE_DIR', self.cache),
                           ('ACTIVE_PROFILE_PATH', self.config / 'active_profile')]:
            patch = mock.patch.object(profile, key, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_profile_paths_stay_rooted(self):
        for name in ('../victim', '/tmp/victim', 'a/b', 'a\\b', 'alt\n', '', True):
            for resolver in (profile.resolve_config_path, profile.resolve_cache_path):
                with self.subTest(name=name, resolver=resolver.__name__), self.assertRaises(ValueError):
                    resolver('trades.json', name)
        for filename in ('../victim', '/tmp/victim', 'folder/../../victim'):
            with self.assertRaises(ValueError):
                profile.resolve_config_path(filename, 'default')

    def test_delete_invalid_name_preserves_sibling(self):
        victim = self.config / 'victim'
        victim.mkdir(parents=True)
        (victim / 'important').write_text('preserve')
        (self.config / 'profiles').mkdir()
        self.assertFalse(profile.delete_profile('../victim', force=True))
        self.assertEqual((victim / 'important').read_text(), 'preserve')

    def test_symlink_escape_never_resolves_or_deletes(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'important').write_text('preserve')
        parent = self.config / 'profiles'
        parent.mkdir(parents=True)
        (parent / 'alt').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            profile.resolve_config_path('important', 'alt')
        self.assertFalse(profile.delete_profile('alt', force=True))
        self.assertTrue((outside / 'important').exists())

    def test_invalid_active_marker_is_preserved_and_reported(self):
        self.config.mkdir()
        profile.ACTIVE_PROFILE_PATH.write_text('../victim')
        with self.assertRaises(ValueError):
            profile.get_active_profile()
        self.assertEqual(profile.ACTIVE_PROFILE_PATH.read_text(), '../victim')

    def test_unreadable_marker_does_not_choose_default(self):
        self.config.mkdir()
        profile.ACTIVE_PROFILE_PATH.write_text('alt')
        with mock.patch.object(Path, 'read_text', side_effect=PermissionError('fixture')):
            with self.assertRaises(ValueError):
                profile.get_active_profile()

    def test_profile_selection_consistent(self):
        profile.set_active_profile('alt')
        self.assertEqual(profile.resolve_profile(None), 'alt')
        self.assertEqual(profile.resolve_config_path('trades.json').resolve(), (self.config / 'profiles/alt/trades.json').resolve())
        self.assertEqual(profile.resolve_cache_path('latest.json').resolve(), (self.cache / 'profiles/alt/latest.json').resolve())
        self.assertEqual(profile.resolve_config_path('trades.json', 'default').resolve(), (self.config / 'trades.json').resolve())

    def test_active_switch_does_not_move_daemon(self):
        from rshelper import monitor
        profile.set_active_profile('default')
        calls = []
        def poll(no_notify, selected):
            calls.append(selected)
            if len(calls) == 1:
                profile.set_active_profile('alt')
            else:
                raise KeyboardInterrupt
        with mock.patch.object(monitor, '_monitor_dir', return_value=self.config), \
                mock.patch.object(monitor, '_pid_path', return_value=self.config / 'monitor.pid'), \
                mock.patch.object(monitor, '_state_path', return_value=self.config / 'monitor_state.json'), \
                mock.patch.object(monitor, '_poll_cycle', side_effect=poll):
            monitor.run_monitor(interval_sec=1, no_notify=True)
        self.assertEqual(calls, ['default', 'default'])
        self.assertEqual(profile.get_active_profile(), 'alt')

    def test_cli_resolves_profile_before_defaults(self):
        from rshelper import cli
        from rshelper.config import Config
        selected = []
        def load(name):
            selected.append(name)
            return Config()
        with mock.patch.object(cli, 'load_config', side_effect=load), \
                mock.patch.object(cli, 'config_path'), \
                mock.patch.object(sys, 'argv', ['rshelper', 'config', 'path', '--profile', 'alt']):
            cli.main()
        self.assertEqual(selected, ['alt'])

    def test_resolved_path_does_not_follow_retargeted_alias(self):
        original = self.config / 'profiles/original'
        original.mkdir(parents=True)
        alias = original.parent / 'alt'
        alias.symlink_to(original, target_is_directory=True)
        target = profile.resolve_config_path('trades.json', 'alt')
        alias.unlink()
        outside = self.root / 'outside'
        outside.mkdir()
        alias.symlink_to(outside, target_is_directory=True)
        self.assertEqual(target, (original / 'trades.json').resolve())

    def test_delete_inside_root_alias_preserves_original(self):
        original = self.config / 'profiles/original'
        original.mkdir(parents=True)
        (original / 'important').write_text('preserve')
        (original.parent / 'alt').symlink_to(original, target_is_directory=True)
        self.assertFalse(profile.delete_profile('alt', force=True))
        self.assertTrue((original / 'important').exists())

    def test_daemon_paths_use_shared_selected_root(self):
        from rshelper import monitor, trader
        self.assertEqual(monitor._pid_path('alt'), profile.resolve_config_path('monitor.pid', 'alt'))
        self.assertEqual(monitor._state_path('alt'), profile.resolve_config_path('monitor_state.json', 'alt'))
        self.assertEqual(trader._pid_path('alt'), profile.resolve_config_path('trader.pid', 'alt'))
        self.assertEqual(trader._state_path('alt'), profile.resolve_config_path('trader_state.json', 'alt'))


if __name__ == '__main__':
    unittest.main()
