"""Provenance must survive consumers; proxy counts cannot certify execution."""
import sys,time,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper import market_data
from rshelper.market_data import MarketDataResult
from rshelper.models import Item
from rshelper.positions import Position


def result(data,source='wiki',volume_kind='executed-trades',stale=False):
    return MarketDataResult(data,source,'stale-cache' if stale else 'network',100,200,100,stale,volume_kind,{source:len(data)})

class ConsumersTest(unittest.TestCase):
    def view(self,value):
        factory=getattr(market_data,'market_payload',None)
        self.assertTrue(callable(factory),'provenance-preserving consumer payload boundary is missing')
        return factory(value)

    def test_legacy_payload_never_infers_wiki_from_field_names(self):
        data=self.view({'2':{'avgHighPrice':110,'highPriceVolume':1000}})
        self.assertEqual(market_data.provenance(data)['source'],'unknown')
        self.assertFalse(market_data.executed_volume_supported(data))

    def test_mixed_source_item_keeps_price_and_volume_provenance(self):
        from rshelper.scanner import build_items_from_api,FlipScanner
        now=time.time()
        mapping=self.view(result([{'id':2,'name':'Fixture','limit':100,'highalch':50}],volume_kind='unknown'))
        latest=self.view(result({'2':{'high':100,'low':120,'highTime':now,'lowTime':now}},source='ge-tracker',volume_kind='standing-orders'))
        volume=self.view(result({'2':{'highPriceVolume':100,'lowPriceVolume':200}}))
        items=build_items_from_api(mapping,latest,volume)
        scanned=FlipScanner().scan(items)
        self.assertEqual(scanned[0].market_data['latest']['source'],'ge-tracker')
        self.assertEqual(scanned[0].market_data['5m']['volume_kind'],'executed-trades')

    def test_proxy_stale_and_unknown_volume_cannot_fill_offers(self):
        from rshelper import ge_offers
        p=Position(1,2,'Fixture',10,100,'traditional','2026-01-01T00:00:00Z')
        raw={'2':{'highPriceVolume':999999,'lowPriceVolume':999999}}
        with mock.patch.object(ge_offers,'list_positions',return_value=[p]):
            for value in (result(raw,'ge-tracker','standing-orders'),result(raw,stale=True),raw):
                slots=ge_offers.build_ge_slots(vol_5m=self.view(value))
                self.assertFalse(slots['slots'][0]['can_collect'])
                self.assertEqual(slots['slots'][0]['fill_pct'],0)
                self.assertIn('execution',slots['slots'][0]['fill_reason'])
            slots=ge_offers.build_ge_slots(vol_5m=self.view(result(raw)))
            self.assertTrue(slots['slots'][0]['can_collect'])

    def test_trader_proxy_volume_cannot_certify_offer_exit(self):
        from rshelper.trader import _ge_fill_pct
        p=Position(1,2,'Fixture',10,100,'traditional','2026-01-01T00:00:00Z')
        volume=self.view(result({'2':{'highPriceVolume':999999}},'ge-tracker','standing-orders'))
        self.assertEqual(_ge_fill_pct(p,volume,time.time()),0)

    def test_signal_volume_capability_is_explicit_not_shape_inferred(self):
        from rshelper import signals
        item=Item(2,'Fixture',False,100,0,100,50,volume=10000)
        raw={'2':{'avgHighPrice':100,'avgLowPrice':100,'highPriceVolume':10000}}
        with mock.patch.object(signals,'_load_cooldowns',return_value={}), \
             mock.patch.object(signals,'_load_baselines',return_value={}), \
             mock.patch.object(signals,'_save_baselines') as save, \
             mock.patch.object(signals,'_save_cooldowns'):
            found=signals.detect_signals([item],self.view(result(raw,'ge-tracker','standing-orders')))
        self.assertEqual(found,[])
        self.assertEqual(save.call_args.args[0],{})

    def test_bootstrap_acquisition_retains_attempt_success_and_stale(self):
        self.view({})  # Fail before acquisition while the boundary is missing.
        from rshelper import cli
        latest=result({'2':{'high':100,'low':120,'highTime':time.time(),'lowTime':time.time()}},stale=True)
        with mock.patch.object(cli,'fetch_mapping_result',return_value=result([{'id':2,'name':'Fixture'}],volume_kind='unknown'),create=True), \
             mock.patch.object(cli,'fetch_latest_result',return_value=latest,create=True), \
             mock.patch.object(cli,'fetch_5m_result',return_value=result({},'ge-tracker','standing-orders'),create=True), \
             mock.patch.object(cli,'cleanup_stale_cache',return_value=0):
            _,prices,vol,items=cli._fetch_bootstrap()
        meta=market_data.provenance(prices)
        self.assertEqual((meta['last_attempt_at'],meta['last_success_at'],meta['stale']),(200,100,True))
        self.assertEqual(market_data.provenance(vol)['volume_kind'],'standing-orders')
        self.assertTrue(items[0].market_data['latest']['stale'])

    def test_public_http_scan_keeps_mixed_evidence_without_private_callback(self):
        import threading,json,urllib.request
        from http.server import ThreadingHTTPServer
        from rshelper.dashboard.handlers import make_handler
        from rshelper.scanner import FlipScanner
        item=Item(2,'Fixture',False,100,0,100,120,volume=1000,
                  market_data={'latest':{'source':'wiki','delivery':'stale-cache','stale':True},
                               '5m':{'source':'ge-tracker','volume_kind':'standing-orders'}})
        private=mock.Mock(side_effect=AssertionError('public scan must not read private metadata'))
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(FlipScanner(),lambda:[item],
                                   meta_fn=private,mode='public-demo'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            response=json.load(urllib.request.urlopen('http://127.0.0.1:%d/api/scan'%server.server_port,timeout=5))
            self.assertEqual(response['market_data'],item.market_data)
            self.assertEqual(response['items'][0]['market_data'],item.market_data)
            private.assert_not_called()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

    def test_empty_wiki_volume_does_not_invent_a_slow_fill(self):
        from rshelper import ge_offers
        from rshelper.trader import _ge_fill_pct
        p=Position(1,2,'Fixture',10,100,'traditional','2026-01-01T00:00:00Z')
        volume=self.view(result({}))
        with mock.patch.object(ge_offers,'list_positions',return_value=[p]):
            self.assertFalse(ge_offers.build_ge_slots(vol_5m=volume)['slots'][0]['can_collect'])
        self.assertEqual(_ge_fill_pct(p,volume,time.time()),0)

    def test_historical_batch_retains_per_item_evidence_through_margin_analysis(self):
        from rshelper import api
        from rshelper.scanner import MarginScanner
        rows=[{'avgHighPrice':100,'avgLowPrice':120,'highPriceVolume':100,
               'lowPriceVolume':100,'timestamp':time.time()-1800+i*300} for i in range(8)]
        with mock.patch.object(api,'fetch_timeseries_result',return_value=result(rows)):
            batch=api.fetch_timeseries_batch_results([2],workers=1)
        item=Item(2,'Fixture',False,100,0,100,120,volume=100,
                  market_data={'latest':{'source':'ge-tracker'}})
        analyses=MarginScanner().scan({2:item},batch)
        self.assertEqual(analyses[0].market_data['history']['source'],'wiki')
        self.assertEqual(analyses[0].market_data['current']['latest']['source'],'ge-tracker')
        self.assertEqual(analyses[0].market_data['history']['last_success_at'],100)

    def test_item_info_json_exposes_unavailable_historical_capability(self):
        import argparse,contextlib,io,json
        from rshelper import cli
        now=time.time();stream=io.StringIO()
        with mock.patch.object(cli,'cleanup_stale_cache',return_value=0),              mock.patch.object(cli,'fetch_mapping_result',return_value=result([{'id':2,'name':'Fixture'}],volume_kind='unknown')),              mock.patch.object(cli,'fetch_latest_result',return_value=result({'2':{'high':100,'low':120,'highTime':now,'lowTime':now}})),              mock.patch.object(cli,'fetch_timeseries_result',return_value=None),              contextlib.redirect_stdout(stream),contextlib.redirect_stderr(io.StringIO()):
            cli.item_info(argparse.Namespace(item='2',profile='default',json=True,timeseries=True,predict=False))
        data=json.loads(stream.getvalue())
        self.assertFalse(data['historical']['available'])
        self.assertIn('Wiki-only',data['historical']['reason'])
        self.assertIsNone(data['historical']['market_data']['last_success_at'])
        self.assertEqual(data['market_data']['latest']['source'],'wiki')

    def test_dashboard_snapshot_preserves_volume_evidence_and_provider_times(self):
        from rshelper import signals
        from rshelper.dashboard import server
        from rshelper.config import Config
        callbacks={};case=self;seen=[]
        mapping=self.view(result([{'id':2,'name':'Fixture'}],volume_kind='unknown'))
        prices=self.view(result({'2':{'high':100,'low':120}}))
        volume=self.view(result({'2':{'avgLowPrice':120,'highPriceVolume':1000}}))
        item=Item(2,'Fixture',False,100,0,100,120,volume=1000)
        def capture(*args,**kwargs):callbacks.update(kwargs);return object
        def detect(items,counts,**kwargs):
            case.assertTrue(market_data.executed_volume_supported(counts))
            seen.append(counts)
            return []
        class FakeServer:
            def __init__(self,*args):pass
            def serve_forever(self):
                callbacks['signal_detector']()
                case.assertEqual(len(seen),1)
                closed=callbacks['close_position_fn'](1,1)
                case.assertEqual(closed['market_data']['latest']['last_success_at'],100)
                meta=callbacks['meta_fn']()
                case.assertNotIn('last_attempt_at',meta)
                case.assertEqual(meta['market_data']['latest']['last_attempt_at'],200)
                case.assertEqual(meta['market_data']['latest']['last_success_at'],100)
            def server_close(self):pass
        with mock.patch.object(server,'load_config',return_value=Config()),              mock.patch.object(server,'_fetch_bootstrap',return_value=(mapping,prices,volume,[item])),              mock.patch.object(server,'make_handler',side_effect=capture),              mock.patch.object(server,'ThreadingHTTPServer',FakeServer),              mock.patch.object(server,'detect_signals',side_effect=detect),              mock.patch('rshelper.positions.list_positions',return_value=[Position(1,2,'Fixture',1,100,'arbitrage','2026-01-01T00:00:00Z')]), mock.patch('rshelper.positions.close_positions',return_value=[{'qty':1,'name':'Fixture','buy_price':100,'profit':18}]), mock.patch('rshelper.journal.log_trade'), mock.patch('rshelper.tuning.record_if_changed'),              mock.patch('rshelper.journal.list_trades',return_value=[]),              mock.patch.object(server.watchlist,'get_watched_ids',return_value=set()),              mock.patch.object(server.alerts,'unread_count',return_value=0):
            server.run(port=0,profile='default',owner_token='a'*64)

    def test_mapping_copy_preserves_evidence(self):
        original=self.view(result({'2':{'highPriceVolume':100}}))
        copied=original.copy()
        self.assertTrue(market_data.executed_volume_supported(copied))
        copied['3']={}
        self.assertNotIn('3',original)

    def test_process_exports_include_provenance(self):
        import argparse,contextlib,io,csv
        from rshelper import cli
        from rshelper.scanner import build_items_from_api
        now=time.time()
        mapping=self.view(result([{'id':2353,'name':'Steel bar','limit':10000},
                                  {'id':440,'name':'Iron ore','limit':10000}, {'id':453,'name':'Coal','limit':10000}]))
        prices=self.view(result({str(i):{'high':h,'low':l,'highTime':now,'lowTime':now}
                      for i,h,l in [(2353,400,576),(440,100,90),(453,130,120)]},'ge-tracker','standing-orders'))
        volume=self.view(result({'2353':{'highPriceVolume':5000,'lowPriceVolume':5000}},'ge-tracker','standing-orders'))
        args=argparse.Namespace(profile=None,members_only=False,min_volume=0,min_profit=0,
                 capital=0,top=10,name='',json=False,csv=True,html=False,save_snapshot=False)
        for html in (False,True):
            stream=io.StringIO();args.html=html;args.csv=not html
            with mock.patch.object(cli,'_fetch_bootstrap',return_value=(mapping,prices,volume,build_items_from_api(mapping,prices,volume))), contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
                cli.process_scan(args)
            if html:
                self.assertIn('ge-tracker',stream.getvalue())
                self.assertIn('standing-orders',stream.getvalue())
            else:
                row=next(csv.DictReader(io.StringIO(stream.getvalue())))
                self.assertEqual(row['price_source'],'ge-tracker')
                self.assertEqual(row['volume_kind'],'standing-orders')
                self.assertEqual(row['price_last_attempt_at'],'200')
                self.assertEqual(row['price_last_success_at'],'100')

    def test_margin_csv_keeps_historical_and_current_sources(self):
        import argparse,contextlib,io,csv
        from rshelper import cli
        item=Item(2,'Fixture',False,100,0,100,120,volume=100,
                  market_data={'latest':{'source':'ge-tracker','delivery':'network','stale':False},
                               '5m':{'volume_kind':'standing-orders'}})
        rows=self.view(result([{'avgHighPrice':100,'avgLowPrice':120,'highPriceVolume':100,
               'lowPriceVolume':100,'timestamp':time.time()-1800+i*300} for i in range(8)]))
        args=argparse.Namespace(profile=None,members_only=False,min_volume=0,min_margin=0,
             ge_slots=8,check=1,workers=1,top=1,name='',flip_direction='arbitrage',csv=True,json=False,save_snapshot=False)
        stream=io.StringIO()
        with mock.patch.object(cli,'_fetch_bootstrap',return_value=([],{}, {},[item])), mock.patch.object(cli,'fetch_timeseries_batch_results',return_value={2:rows}), contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
            cli.margin_check(args)
        row=next(csv.DictReader(io.StringIO(stream.getvalue())))
        self.assertEqual(row['history_source'],'wiki')
        self.assertEqual(row['history_last_attempt_at'],'200')
        self.assertEqual(row['history_last_success_at'],'100')
        self.assertEqual(row['price_source'],'ge-tracker')
        self.assertEqual(row['volume_kind'],'standing-orders')

    def test_paper_confirmations_retain_quote_evidence(self):
        import argparse,contextlib,io
        from rshelper import api,cli
        now=time.time();entry={'id':2,'name':'Fixture','limit':100}
        args=argparse.Namespace(item='Fixture',profile=None,flip_direction='arbitrage',qty=1,capital=0,note='')
        with mock.patch.object(api,'fetch_mapping_result',return_value=result([entry])), mock.patch.object(api,'fetch_latest_result',return_value=result({'2':{'high':100,'low':120,'highTime':now,'lowTime':now}},'ge-tracker','standing-orders')):
            for callback in (cli._trade_paper,cli._trade_open,cli._trade_close):
                stream=io.StringIO()
                with contextlib.redirect_stdout(stream):callback(args)
                self.assertIn('Quote: ge-tracker / network',stream.getvalue())
                self.assertIn('last success: 100; last attempt: 200',stream.getvalue())

    def test_collect_receipt_retains_quote_evidence(self):
        from rshelper import ge_offers
        p=Position(1,2,'Fixture',1,100,'arbitrage','2026-01-01T00:00:00Z')
        now=time.time();prices=self.view(result({'2':{'high':100,'low':120,'highTime':now,'lowTime':now}}))
        with mock.patch.object(ge_offers,'list_positions',return_value=[p]), mock.patch.object(ge_offers,'close_positions',return_value=[{'name':'Fixture','qty':1,'buy_price':100,'profit':18}]), mock.patch.object(ge_offers,'log_trade'):
            receipt=ge_offers.collect_offer(1,latest=prices)
        self.assertEqual(receipt['market_data']['latest']['last_attempt_at'],200)
        self.assertEqual(receipt['market_data']['latest']['last_success_at'],100)

    def test_empty_public_scan_has_explicit_unknown_evidence(self):
        import threading,json,urllib.request
        from http.server import ThreadingHTTPServer
        from rshelper.dashboard.handlers import make_handler
        from rshelper.scanner import FlipScanner
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(FlipScanner(),lambda:[],mode='public-demo'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            data=json.load(urllib.request.urlopen('http://127.0.0.1:%d/api/scan'%server.server_port,timeout=5))
            self.assertEqual(data['market_data']['latest']['source'],'unknown')
            self.assertIsNone(data['market_data']['latest']['last_success_at'])
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

if __name__=='__main__':unittest.main()
