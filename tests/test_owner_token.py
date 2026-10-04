"""Owner credentials stay private, stable and out of process arguments."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper.dashboard.owner_token import load_or_create_token


class TestOwnerToken(unittest.TestCase):
    def test_default_token_alias_is_not_resolved_before_validation(self):
        import rshelper.dashboard.server as server
        from rshelper import profile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            target = root / 'other.token'; target.write_text('a' * 64); target.chmod(0o600)
            (root / 'owner.token').symlink_to(target)
            with mock.patch.object(profile, 'CONFIG_DIR', root), \
                 mock.patch.object(server, '_fetch_bootstrap') as fetch, \
                 mock.patch.object(server, 'load_config') as config:
                with self.assertRaises(ValueError):
                    server.run(profile='default')
                config.assert_not_called(); fetch.assert_not_called()

    def test_server_refuses_invalid_policy_or_credential_before_fetch(self):
        import rshelper.dashboard.server as server
        with mock.patch.object(server, '_fetch_bootstrap') as fetch:
            for kwargs in ({'access_mode': 'unknown'}, {'access_mode': 'public-demo', 'control': True},
                           {'owner_token': 'short'}):
                with self.assertRaises(ValueError):
                    server.run(profile='default', **kwargs)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder).resolve() / 'owner.token'
                path.write_text('a' * 64); path.chmod(0o644)
                with self.assertRaises(ValueError):
                    server.run(profile='default', owner_token_file=str(path))
            fetch.assert_not_called()

    def test_cli_passes_explicit_mode_and_file_without_token_value(self):
        from rshelper import cli
        from rshelper.config import Config
        with mock.patch.object(sys, 'argv', ['rshelper', '--profile', 'default',
                 'dashboard', '--access-mode', 'public-demo', '--owner-token-file', '/private/owner.token']), \
             mock.patch.object(cli, 'load_config', return_value=Config()), \
             mock.patch('rshelper.dashboard.server.run') as run:
            cli.main()
        self.assertEqual(run.call_args.kwargs['access_mode'], 'public-demo')
        self.assertEqual(run.call_args.kwargs['owner_token_file'], '/private/owner.token')
        self.assertNotIn('owner_token', run.call_args.kwargs)

    def test_private_stable_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / 'private' / 'owner.token'
            token = load_or_create_token(path)
            self.assertEqual(len(token), 64)
            self.assertEqual(load_or_create_token(path), token)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_invalid_permissive_or_symlink_credentials_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / 'owner.token'
            for value, mode in ((b'short', 0o600), (b'a' * 64, 0o644), (b'x' * 5000, 0o600)):
                path.write_bytes(value); path.chmod(mode)
                with self.assertRaises(ValueError):
                    load_or_create_token(path)
                self.assertEqual(path.read_bytes(), value)
            target = Path(folder).resolve() / 'real'
            path.rename(target); path.symlink_to(target)
            with self.assertRaises(ValueError):
                load_or_create_token(path)

    def test_parent_alias_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); (root / 'real').mkdir()
            (root / 'alias').symlink_to(root / 'real')
            with self.assertRaises(ValueError):
                load_or_create_token(root / 'alias' / 'owner.token')
            self.assertFalse((root / 'real' / 'owner.token').exists())


if __name__ == '__main__':
    unittest.main()
