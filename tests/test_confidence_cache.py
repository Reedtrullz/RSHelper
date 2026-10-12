from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper import api
from rshelper.config import Config
from rshelper.dashboard import server
from rshelper.models import Item
from rshelper.market_data import MarketDataResult,market_payload

def history():
    return MarketDataResult([{'timestamp':1700000100+i*300,'avgHighPrice':100,
                'avgLowPrice':120,'highPriceVolume':100,'lowPriceVolume':100} for i in range(8)],
                'wiki','network',100,100,100,False,'executed-trades',{'wiki':8})

class HistoryCoalescingTest(unittest.TestCase):
    def test_profiles_and_timesteps_do_not_share_acquisitions(self):
        barrier = threading.Barrier(3)
        def fetch(*args,**kwargs):
            barrier.wait(3)
            return history()
        with mock.patch.object(api,'_fetch_result',side_effect=fetch) as acquisition,ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(api.fetch_timeseries_result,561,step,profile)
                       for step,profile in [('5m','default'),('5m','other'),('1h','default')]]
            self.assertTrue(all(f.result(4) is not None for f in futures))
        self.assertEqual(acquisition.call_count,3)
        self.assertEqual(api._HISTORY_INFLIGHT,{})

    def test_capacity_rejection_and_failure_release_admission(self):
        entered,release = threading.Event(),threading.Event()
        def fetch(*args,**kwargs):
            entered.set()
            if not release.wait(3):raise AssertionError('fixture not released')
            raise ValueError('fixture failed')
        with mock.patch.object(api,'MAX_HISTORY_INFLIGHT',1), \
                mock.patch.object(api,'_fetch_result',side_effect=fetch) as acquisition,ThreadPoolExecutor(max_workers=2) as pool:
            owner = pool.submit(api.fetch_timeseries_result,1,'5m','default')
            try:
                self.assertTrue(entered.wait(3))
                self.assertIsNone(api.fetch_timeseries_result(2,'5m','default'))
                self.assertEqual(acquisition.call_count,1)
                with api._HISTORY_LOCK:
                    done = next(iter(api._HISTORY_INFLIGHT.values()))['done']
                original_wait = done.wait
                joined = threading.Event()
                def wait(timeout=None):
                    joined.set()
                    return original_wait(timeout)
                with mock.patch.object(done,'wait',side_effect=wait):
                    follower = pool.submit(api.fetch_timeseries_result,1,'5m','default')
                    self.assertTrue(joined.wait(3))
            finally:
                release.set()
            with self.assertRaisesRegex(ValueError,'fixture failed'):owner.result(3)
            with self.assertRaisesRegex(RuntimeError,'shared history acquisition failed') as error:
                follower.result(3)
            self.assertIsInstance(error.exception.__cause__,ValueError)
        self.assertEqual(api._HISTORY_INFLIGHT,{})
        self.assertFalse(hasattr(api._ACQUISITION,'end'))
        with mock.patch.object(api,'_fetch_result',return_value=history()):
            self.assertIsNotNone(api.fetch_timeseries_result(2,'5m','default'))

    def test_expired_network_completion_cannot_publish_cache(self):
        clock = [100.0]
        def fetch(*args,**kwargs):
            clock[0] = 102.0
            return {'data':history().data}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(api,'_cache_path',side_effect=lambda name,profile:Path(folder)/(name+'.json')), \
                mock.patch.object(api,'_cache_result',return_value=None), \
                mock.patch.object(api,'_get',side_effect=fetch), \
                mock.patch.object(api,'_save_cache_result') as save, \
                mock.patch.object(api,'ACQUISITION_TIMEOUT',1), \
                mock.patch.object(api.time,'monotonic',side_effect=lambda:clock[0]):
            self.assertIsNone(api.fetch_timeseries_result(561,'5m','default'))
            save.assert_not_called()
        self.assertEqual(api._HISTORY_INFLIGHT,{})

    def test_overlapping_history_requests_dispatch_once_and_own_their_results(self):
        entered,release = threading.Event(),threading.Event()
        waits = threading.Condition()
        followers = [0]
        shared_done = [None]
        original_wait = threading.Event.wait
        def tracked_wait(event,timeout=None):
            if event is shared_done[0]:
                with waits:
                    followers[0] += 1
                    waits.notify_all()
            return original_wait(event,timeout)
        def fetch(*args,**kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError('fixture acquisition not released')
            return history()
        with mock.patch.object(api,'_fetch_result',side_effect=fetch) as acquisition, \
                mock.patch.object(threading.Event,'wait',tracked_wait),ThreadPoolExecutor(max_workers=8) as pool:
            owner = pool.submit(api.fetch_timeseries_result,561,'5m','default')
            self.assertTrue(original_wait(entered,3))
            with api._HISTORY_LOCK:
                shared_done[0] = next(iter(api._HISTORY_INFLIGHT.values()))['done']
            joined = [pool.submit(api.fetch_timeseries_result,561,'5m','default') for _ in range(7)]
            with waits:
                self.assertTrue(waits.wait_for(lambda:followers[0]>=7,3))
            release.set()
            values = [future.result(3) for future in [owner,*joined]]
        self.assertEqual(acquisition.call_count,1)
        values[0].data[0]['avgLowPrice'] = 1
        self.assertTrue(all(value.data[0]['avgLowPrice']==120 for value in values[1:]))

    def test_duplicate_batch_ids_collapse_and_acquisition_is_capped(self):
        with mock.patch.object(api,'fetch_timeseries_result',return_value=history()) as fetch:
            values = api.fetch_timeseries_batch_results([1,1,*range(2,40)],workers=2,profile='default')
        self.assertEqual(fetch.call_count,30)
        self.assertEqual(list(sorted(values)),list(range(1,31)))

class QuoteConfidenceTest(unittest.TestCase):
    def exercise(self,scenario):
        now = [1700002500.0]
        callbacks = {}
        cfg = Config()
        callbacks['config'] = cfg
        rows = market_payload(history(),sequence=True)
        first = Item(1,'Synthetic',False,100,0,100,120,volume=100)
        second = Item(1,'Synthetic',False,100,0,100,50,volume=100)
        class HttpServer:
            def __init__(self,*args): pass
            def serve_forever(self): scenario(callbacks,now,rows)
            def server_close(self): pass
        def handler(*args,**kwargs):
            callbacks['scan_items'] = args[1]
            callbacks.update(kwargs)
            return object
        with ExitStack() as stack:
            for target,name,value in ((server,'load_config',lambda *args:cfg),
                    (server,'_fetch_bootstrap',mock.Mock(side_effect=[([{'id':1}],{}, {},[first]),([{'id':1}],{}, {},[second])])),
                    (server,'ThreadingHTTPServer',HttpServer),(server,'make_handler',handler),
                    (server,'detect_signals',lambda *args,**kwargs:[]),(server.time,'time',lambda:now[0])):
                stack.enter_context(mock.patch.object(target,name,value))
            stack.enter_context(mock.patch('rshelper.tuning.record_if_changed'))
            stack.enter_context(mock.patch('rshelper.journal.list_trades',return_value=[]))
            stack.enter_context(mock.patch.object(server.watchlist,'load',return_value={'items':{}}))
            stack.enter_context(mock.patch.object(server.alerts,'push_alert'))
            stack.enter_context(mock.patch.object(server.alerts,'unread_count',return_value=0))
            server.run(port=0,owner_token='a'*64)

    def test_current_quote_revision_recomputes_profitability(self):
        def scenario(callbacks,now,rows):
            with mock.patch.object(api,'fetch_timeseries_batch_results',return_value={1:rows}):
                first = callbacks['confidence_fn']([1])['1']
                now[0] += 121.0
                callbacks['scan_items']()
                second = callbacks['confidence_fn']([1])['1']
            self.assertEqual(first['candle_coverage']['samples'],8)
            self.assertEqual(second['candle_coverage']['samples'],8)
            self.assertLess(second['profitability_score'],first['profitability_score'])
            self.assertGreater(second['market_revision'],first['market_revision'])
        self.exercise(scenario)

    def test_effective_config_invalidates_scores_and_unavailable_history_is_explicit(self):
        def scenario(callbacks,now,rows):
            with mock.patch.object(api,'fetch_timeseries_batch_results',return_value={}) as fetch:
                first = callbacks['confidence_fn']([1])
                self.assertFalse(first['1']['available'])
                self.assertIn('Wiki',first['1']['reason'])
                self.assertEqual(callbacks['confidence_fn']([1]),first)
                self.assertEqual(fetch.call_count,1)
                callbacks['config'].flip.min_volume += 1
                self.assertEqual(callbacks['confidence_fn']([1]),first)
                self.assertEqual(fetch.call_count,2)
        self.exercise(scenario)

    def test_late_old_completion_cannot_fill_a_new_market_generation(self):
        entered,release = threading.Event(),threading.Event()
        def scenario(callbacks,now,rows):
            calls = [0]
            def fetch(*args,**kwargs):
                calls[0] += 1
                if calls[0]==1:
                    entered.set()
                    if not release.wait(3):raise AssertionError('old fixture not released')
                return {1:rows}
            with mock.patch.object(api,'fetch_timeseries_batch_results',side_effect=fetch),ThreadPoolExecutor(max_workers=1) as pool:
                old = pool.submit(callbacks['confidence_fn'],[1])
                self.assertTrue(entered.wait(3))
                now[0] += 121.0
                callbacks['scan_items']()
                current = callbacks['confidence_fn']([1])
                release.set()
                self.assertEqual(old.result(3),{})
                self.assertEqual(callbacks['confidence_fn']([1]),current)
        self.exercise(scenario)

if __name__ == '__main__':
    unittest.main()
