"""Machine-readable output remains valid during fetch failures and retries."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import rshelper.api as api


class TestOutputContract(unittest.TestCase):
    def test_flip_formats_use_directional_capital_and_server_economics(self):
        import csv
        import rshelper.cli as cli
        from rshelper.models import Item
        for direction, high, low in (('arbitrage', 100, 110), ('traditional', 110, 100)):
            item = Item(1, 'Synthetic', False, 100, 0, high, low, 20)
            for output in ('--json', '--csv', '--html', None):
                with self.subTest(direction=direction, output=output):
                    out, err = io.StringIO(), io.StringIO()
                    argv = ['rshelper', 'flip-scan', '--flip-direction', direction,
                            '--capital', '1000', '--no-members-only']
                    if output: argv.append(output)
                    with mock.patch.object(cli, '_fetch_bootstrap', return_value=([], {}, {}, [item])), \
                            mock.patch.object(sys, 'argv', argv), \
                            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        cli.main()
                    if output == '--json':
                        row = json.loads(out.getvalue())[0]
                        self.assertEqual(row['roi'], 8.0)
                        self.assertEqual(row['capital_per_unit'], 100)
                        self.assertEqual(row['explanation']['tax'], 2)
                        self.assertEqual(row['explanation']['net_profit'], 8)
                    elif output == '--csv':
                        row = next(csv.DictReader(io.StringIO(out.getvalue())))
                        self.assertEqual(float(row['roi']), 8.0)
                        self.assertEqual(int(row['capital_per_unit']), 100)
                    else:
                        self.assertIn('8.0', out.getvalue())
                        self.assertIn('10', out.getvalue())

    def test_retry_json_has_one_value(self):
        failures = [urllib.error.HTTPError('https://fixture.invalid', code, 'fixture', {}, None)
                    for code in (429, 503)]
        failures += [urllib.error.URLError('timeout'), json.JSONDecodeError('fixture', '', 0)]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                response = mock.MagicMock()
                response.__enter__.return_value.read1.side_effect = [b'{"data": {"2": {"high": 200}}}', b'']
                out, err = io.StringIO(), io.StringIO()
                with mock.patch.object(api.urllib.request, "urlopen", side_effect=[failure, response]), \
                        mock.patch.object(api.time, "sleep"), \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    data = api._fetch_url('https://fixture.invalid')
                    print(json.dumps(data))
                self.assertEqual(json.loads(out.getvalue()), {"data": {"2": {"high": 200}}})
                self.assertIn('Retrying', err.getvalue())

    def test_exhausted_fetch_has_empty_stdout(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(api.urllib.request, "urlopen", side_effect=urllib.error.URLError('timeout')), \
                mock.patch.object(api.time, "sleep"), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertIsNone(api._fetch_url('https://fixture.invalid', retries=1))
        self.assertEqual(out.getvalue(), '')
        self.assertIn('Warning', err.getvalue())

    def test_sweep_json_contract(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        spec = importlib.util.spec_from_file_location('sweep_contract', ROOT / "scripts/sweep.py")
        sweep = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sweep)
        out, err = io.StringIO(), io.StringIO()
        fixture = {"trades": 1, "roi_pct": 1, "win_rate": 100, "profit_factor": 1, "max_drawdown": 0}
        with tempfile.TemporaryDirectory() as folder:
            mapping=Path(folder)/'mapping.json'
            mapping.write_text(json.dumps({'2':{'name':'Synthetic','members':False,'limit':10000}}))
            with mock.patch.object(sweep, 'load_data', return_value={2: []}), \
                    mock.patch.object(sweep, 'simulate', side_effect=lambda *a,**k:dict(fixture)), \
                    mock.patch.object(sys, 'argv', ['sweep.py','--data',str(Path(folder)/'data.json'),
                        '--mapping',str(mapping),'--config','runtime-defaults','--slots','8','--json','--top','1']), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(sweep.main(), 0)
        self.assertEqual(len(json.loads(out.getvalue())), 1)

    def test_exhausted_fallback_stdout_empty(self):
        out, err = io.StringIO(), io.StringIO()
        failure = lambda *args: api._fetch_url('https://fixture.invalid', retries=0)
        with mock.patch.object(api, '_load_cache', return_value=None), \
                mock.patch.object(api, '_load_stale_cache', return_value=None), \
                mock.patch.object(api, '_get', side_effect=failure), \
                mock.patch.object(api, '_get_ge_tracker', side_effect=failure), \
                mock.patch.object(api.urllib.request, 'urlopen', side_effect=urllib.error.URLError('timeout')), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertIsNone(api.fetch_latest())
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(err.getvalue().count('Warning'), 2)

    def test_quiet_failed_fetch(self):
        import rshelper.cli as cli
        out, err = io.StringIO(), io.StringIO()
        def fail_fetch(args):
            api._fetch_url('https://fixture.invalid', retries=0)
            raise SystemExit(1)
        with mock.patch.object(cli, 'item_info', side_effect=fail_fetch), \
                mock.patch.object(api.urllib.request, 'urlopen', side_effect=urllib.error.URLError('timeout')), \
                mock.patch.object(sys, 'argv', ['rshelper', '--quiet', 'item-info', '2', '--json']), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            previous = sys.stderr
            try:
                with self.assertRaises(SystemExit):
                    cli.main()
                self.assertIs(sys.stderr, previous)
            finally:
                if sys.stderr is not previous:
                    sys.stderr.close()
                    sys.stderr = previous
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(err.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
