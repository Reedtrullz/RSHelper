"""Reviewed CLI syntax matrix plus real disposable-profile output contracts."""
import argparse
import contextlib
import csv
import io
import json
from pathlib import Path
import shlex
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import cli, profile, snapshot
from rshelper.config import Config
from rshelper.market_data import MarketDataResult

CASES = {
    'scenario': '--input scenario.json --json',
    'annotations list': '--json',
    'annotations write': '--input annotation.json --expected-revision 0 --json',
    'observed list': '--slots 8 --json',
    'observed history': '11111111-1111-4111-8111-111111111111 --offset 1 --json',
    'observed record': '11111111-1111-4111-8111-111111111111 --input observed.json --expected-revision 0 --operation-id 22222222-2222-4222-8222-222222222222 --json',
    'observed preview-csv': '--input observed.csv --json',
    'observed apply-csv': '--input observed.csv --expected-import-hash 1111111111111111111111111111111111111111111111111111111111111111 --backup before.zip --json',
    'trading-mode': '--mode entries-paused --expected-revision 0 --reason Synthetic --operation-id 11111111-1111-4111-8111-111111111111 --json',
    'alch-scan': '--nature-rune-cost 1 --members-only --no-members-only --min-volume 1 --top 3 --name Synthetic --json --csv --html --save-snapshot --intraday-snapshots',
    'flip-scan': '--members-only --no-members-only --min-volume 1 --min-margin 1 --top 3 --capital 10000 --flip-direction traditional --name Synthetic --json --csv --html --save-snapshot --intraday-snapshots --ge-slots 2',
    'process-scan': '--members-only --no-members-only --skill smithing --min-volume 1 --min-profit 1 --top 3 --capital 10000 --name Synthetic --json --csv --html --save-snapshot --intraday-snapshots',
    'chain-plan': '--inventory 1761 --max-depth 2 --top 1 --json',
    'item-info': '2 --timeseries --json --tax-curve --wiki --wiki-open --predict',
    'monitor': '--interval 1 --no-notify --stop --status --json',
    'auto-trade': '--once --interval 1 --stop --status --json',
    'trade log': 'Synthetic 2 100 150 --note fixture',
    'trade paper': '2 2 --capital 10000 --flip-direction traditional --note fixture --expected-revision 1 --operation-id 11111111-1111-4111-8111-111111111111 --json',
    'trade open': '2 2 --capital 10000 --flip-direction traditional --note fixture --expected-revision 1 --operation-id 11111111-1111-4111-8111-111111111111 --json',
    'trade close': '2 1 --operation-id 11111111-1111-4111-8111-111111111111 --expected-revision 1 --json',
    'trade positions': '--json',
    'trade list': '--item Synthetic --since 2026-01-01 --top 1 --strategy manual --json --csv',
    'trade pnl': '--since 2026-01-01 --by-item --strategy manual --json',
    'trade delete': '1',
    'trade status': '--json --save-equity-snapshot',
    'trade budget': '--initialize --bankroll 1000 --membership free --expected-revision 1 --operation-id 11111111-1111-4111-8111-111111111111 --json',
    'trade offers': '--action start-sale --offer-id 11111111-1111-4111-8111-111111111111 --lot-uid 22222222-2222-4222-8222-222222222222 --qty 1 --sell-price 120 --expected-revision 1 --operation-id 33333333-3333-4333-8333-333333333333 --json',
    'signals': '--members-only --no-members-only --flip-direction traditional --cooldown 1 --json --monitor 1',
    'watch add': '2 --alert-above 1 --alert-below -1 --alert-mode crossing --alert-cooldown-sec 900 --alert-hysteresis-gp 10',
    'watch remove': '2',
    'watch list': '',
    'watch check': '--flip-direction traditional --ge-slots 2 -v --verbose --json',
    'diff': 'flip --date 2026-01-01 --json',
    'profile create': 'fixture',
    'profile switch': 'fixture',
    'profile list': '',
    'profile backup': 'private.zip --evidence --json',
    'profile export': 'private.json --format json --without-reviews --json',
    'profile import': '--input private.json --format json --expected-profile-uuid 22222222-2222-4222-8222-222222222222 --expected-source-revision fixture --apply --operation-id 11111111-1111-4111-8111-111111111111 --backup before.zip --json',
    'profile delete': 'fixture --force',
    'snapshots': 'flip',
    'config show': '',
    'config path': '',
    'reviews queue':'--tag synthetic --unreviewed --note manual --strategy manual --limit 2 --json',
    'reviews append':'11111111-1111-4111-8111-111111111111 --input review.json --expected-revision 0 --operation-id 22222222-2222-4222-8222-222222222222 --json',
    'reviews history':'11111111-1111-4111-8111-111111111111 --json',
    'config preview': '--input candidate.toml --json',
    'config apply': '--input candidate.toml --expected-revision 0:fixture --operation-id 11111111-1111-4111-8111-111111111111 --backup before.zip --json',
    'config rollback': '--restore-operation-id 22222222-2222-4222-8222-222222222222 --expected-revision 1:fixture --operation-id 11111111-1111-4111-8111-111111111111 --backup before.zip --json',
    'dashboard': '--port 5555 --bind 127.0.0.1 --access-mode owner --owner-token-file token --open --control --profile fixture',
    'history': '--all --strategy manual --json',
    'margin-check': '--members-only --no-members-only --min-volume 1 --min-margin 1 --check 2 --top 1 --capital 10000 --flip-direction traditional --name Synthetic --json --csv --ge-slots 2 --workers 1 --risk --save-snapshot --intraday-snapshots',
    'state capture': '--output packet.zip --json',
    'state apply': '--input packet.zip --json',
    'state receipt': '--origin 11111111-1111-4111-8111-111111111111 --json',
    'state verify': '--origin 11111111-1111-4111-8111-111111111111 --profile-uuid 33333333-3333-4333-8333-333333333333 --revision 1 --hash 1111111111111111111111111111111111111111111111111111111111111111 --json',
    'state check': '--json',
    'state migration-plan': '--origin 11111111-1111-4111-8111-111111111111 --profile-uuid 22222222-2222-4222-8222-222222222222 --lineage lineage.json --json',
    'state migrate': '--plan plan.json --operation-id 11111111-1111-4111-8111-111111111111 --json',
    'backup inspect': '--input private.zip --json',
    'backup restore': '--input private.zip --expected-profile-uuid 22222222-2222-4222-8222-222222222222 --operation-id 11111111-1111-4111-8111-111111111111 --expected-source-revision fixture --json',
    'readiness': '--json',
}


class CliContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in (('CONFIG_DIR', self.root / 'config'), ('CACHE_DIR', self.root / 'cache')):
            patch = mock.patch.object(profile, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(snapshot, 'CONFIG_DIR', self.root / 'config')
        patch.start()
        self.addCleanup(patch.stop)

    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, 'argv', ['rshelper', *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main()
        return out.getvalue(), err.getvalue()

    def test_every_command_and_flag_has_a_reviewed_parse_and_help_contract(self):
        parsers = []
        parse = argparse.ArgumentParser.parse_known_args
        def record(parser, *args, **kwargs):
            if parser.prog == 'rshelper':
                parsers.append(parser)
            return parse(parser, *args, **kwargs)
        with mock.patch.object(argparse.ArgumentParser, 'parse_known_args', record), \
                mock.patch.object(cli, 'load_config', return_value=Config()):
            with self.assertRaises(SystemExit) as exit:
                help_text, _ = self.invoke(['--help'])
            self.assertEqual(exit.exception.code, 0)
        parser = parsers[-1]
        leaves = {}
        def walk(node, prefix=''):
            branches = [a for a in node._actions if isinstance(a, argparse._SubParsersAction)]
            if not branches:
                leaves[prefix] = node
            for action in branches:
                for name, child in action.choices.items():
                    walk(child, (prefix + ' ' + name).strip())
        walk(parser)
        self.assertEqual(set(leaves), set(CASES), 'new commands require reviewed fixtures')
        for command, text in CASES.items():
            with self.subTest(command=command):
                args = shlex.split(text)
                flags = {flag for a in leaves[command]._actions for flag in a.option_strings}
                self.assertEqual(flags - {'-h', '--help', '--profile'}, {a for a in args if a.startswith('-') and not a.lstrip('-').isdigit()} - {'--profile'},
                                 'new flags require reviewed fixtures')
                parsed = parser.parse_args(['--profile', 'fixture', '--quiet', *command.split(), *args])
                self.assertTrue(parsed.quiet)
                self.assertEqual(parsed.profile, 'fixture')
                with self.assertRaises(SystemExit) as exit, contextlib.redirect_stdout(io.StringIO()):
                    parser.parse_args([*command.split(), '--help'])
                self.assertEqual(exit.exception.code, 0)

    def test_scans_execute_all_output_formats_with_owned_market_fixture(self):
        now = time.time()
        mapping = [{'id': 2, 'name': 'Synthetic', 'members': False, 'limit': 100, 'highalch': 300}]
        latest = {'2': {'high': 200, 'low': 190, 'highTime': now, 'lowTime': now}}
        volume = {'2': {'highPriceVolume': 100, 'lowPriceVolume': 100}}
        def result(data):
            return MarketDataResult(data, 'wiki', 'network', now, now, now, False, 'executed-trades', {'wiki': len(data)})
        with mock.patch.object(cli, 'fetch_mapping_result', return_value=result(mapping)), \
                mock.patch.object(cli, 'fetch_latest_result', return_value=result(latest)), \
                mock.patch.object(cli, 'fetch_5m_result', return_value=result(volume)):
            for command in ('alch-scan', 'flip-scan', 'process-scan'):
                common = [x for x in shlex.split(CASES[command]) if x not in ('--json', '--csv', '--html')]
                for flag in ('--json', '--csv', '--html'):
                    with self.subTest(command=command, flag=flag):
                        out, err = self.invoke(['--quiet', '--profile', 'fixture', command, *common, flag])
                        self.assertEqual(err, '')
                        if flag == '--json':
                            json.loads(out)
                        elif flag == '--csv':
                            self.assertIn('name', next(csv.reader(io.StringIO(out))))
                        else:
                            self.assertIn('<html', out.lower())
        self.assertTrue(list((profile.resolve_config_path('snapshots', 'fixture')).glob('*.json')))


if __name__ == '__main__':
    unittest.main()
