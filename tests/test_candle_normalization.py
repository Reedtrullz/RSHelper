from dataclasses import asdict
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from rshelper import analysis, market_validation

def candles(step=300):
    return [{'timestamp':1700000000+index*step,'avgHighPrice':100,
             'avgLowPrice':120+index,'highPriceVolume':50,'lowPriceVolume':50}
            for index in range(8)]

class CandleNormalizationTest(unittest.TestCase):
    def normalize(self,rows,step='5m'):
        return market_validation.normalize_candles(rows,step)

    def test_unsorted_identical_duplicates_have_one_deterministic_analysis(self):
        rows = candles()
        mixed = [rows[4],rows[0],rows[7],rows[2],rows[1],rows[3],rows[6],rows[5],rows[4]]
        result = self.normalize(mixed)
        self.assertEqual(result['data'],rows)
        self.assertEqual(result['coverage']['duplicates'],1)
        expected = asdict(analysis.analyze_timeseries(1,rows,100,125,timestep='5m'))
        actual = asdict(analysis.analyze_timeseries(1,mixed,100,125,timestep='5m'))
        for key in ('avg_margin','confidence','margin_trend','window_hours'):
            self.assertEqual(actual[key],expected[key])

    def test_conflicting_timestamp_is_quarantined_in_both_orders(self):
        rows = candles()
        changed = {**rows[3],'avgLowPrice':999}
        left = self.normalize([*rows,changed])
        right = self.normalize([changed,*rows])
        self.assertEqual(left['data'],right['data'])
        self.assertNotIn(rows[3],left['data'])
        self.assertNotIn(changed,left['data'])
        self.assertEqual(left['coverage']['conflicts'],1)
        self.assertEqual(left['coverage']['rejected'],2)
        self.assertEqual(left['coverage']['missing_windows'],1)

    def test_malformed_rows_do_not_crash_valid_batch(self):
        rows = candles()
        bad = [None,{}, {**rows[0],'timestamp':True}, {**rows[0],'avgHighPrice':'bad'},
               {**rows[0],'lowPriceVolume':float('inf')}]
        result = self.normalize([*rows,*bad])
        self.assertEqual(result['data'],rows)
        self.assertEqual(result['coverage']['rejected'],len(bad))
        self.assertIsNotNone(analysis.analyze_timeseries(1,[*rows,*bad],100,125,timestep='5m'))

    def test_gap_is_preserved_and_disclosed_without_a_fabricated_candle(self):
        rows = candles()
        rows = rows[:3]+rows[4:]
        result = self.normalize(rows)
        self.assertEqual(result['data'],rows)
        self.assertEqual(result['coverage']['missing_windows'],1)
        self.assertEqual(result['coverage']['gap_intervals'],1)
        self.assertEqual(result['coverage']['observed_span_seconds'],2100)
        self.assertEqual(result['coverage']['coverage_ratio'],7/8)

    def test_supported_timesteps_use_their_actual_span_and_volume_units(self):
        for step,seconds in (('5m',300),('1h',3600),('6h',21600),('24h',86400)):
            with self.subTest(step=step):
                rows = candles(seconds)
                value = analysis.analyze_timeseries(1,rows,100,125,timestep=step)
                self.assertEqual(value.window_hours,7*seconds/3600)
                self.assertEqual(value.candle_coverage['timestep_seconds'],seconds)
                self.assertAlmostEqual(value.volume_score,min(1,100*300/seconds/50))

    def test_unknown_step_and_absent_times_fail_without_assuming_five_minutes(self):
        with self.assertRaises(ValueError):
            self.normalize(candles(),'bogus')
        rows = [{k:v for k,v in row.items() if k!='timestamp'} for row in candles()]
        self.assertEqual(self.normalize(rows)['data'],[])
        self.assertIsNone(analysis.analyze_timeseries(1,rows,100,125,timestep='1h'))

    def test_irregular_intervals_are_explicit_and_not_scored(self):
        result = self.normalize(candles(), '1h')
        self.assertGreater(result['coverage']['irregular_intervals'],0)
        self.assertIsNone(analysis.analyze_timeseries(1,candles(),100,125,timestep='1h'))

    def test_replay_uses_the_same_unique_valid_candles(self):
        import replay
        rows = candles()
        expected = replay.simulate({1:rows},replay.ReplayConfig())
        actual = replay.simulate({1:[*reversed(rows),rows[2],{}]},replay.ReplayConfig())
        self.assertEqual({k:v for k,v in actual.items() if k!='candle_coverage'},
                         {k:v for k,v in expected.items() if k!='candle_coverage'})
        self.assertEqual(actual['candle_coverage']['1']['rejected'],1)
        self.assertEqual(actual['candle_coverage']['1']['duplicates'],1)
        with self.assertRaises(ValueError):
            replay.simulate({1:[{}]},replay.ReplayConfig())
        with self.assertRaises(ValueError):
            replay.simulate({1:rows,2:candles(60)},replay.ReplayConfig())

    def test_api_normalizes_before_cache_and_retains_read_coverage(self):
        from rshelper import api, profile
        from rshelper.market_data import market_payload
        with tempfile.TemporaryDirectory() as temporary, patch.object(profile,'CACHE_DIR',Path(temporary)), \
                patch.object(api,'_get',return_value={'data':[*reversed(candles()),candles()[3],{}]}):
            value = api.fetch_timeseries_result(561,'5m','default')
            self.assertEqual(value.data,candles())
            payload = market_payload(value,sequence=True)
            self.assertEqual(payload.candle_coverage['duplicates'],1)
            self.assertEqual(payload.candle_coverage['rejected'],1)
            next_value = api.fetch_timeseries_result(561,'5m','default')
            self.assertEqual(next_value.delivery,'fresh-cache')
            self.assertEqual(next_value.data,candles())

if __name__ == '__main__':
    unittest.main()
