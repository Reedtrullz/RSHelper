import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))


class CatalogTest(unittest.TestCase):
    def test_scan_explanations_share_economics_and_precise_exclusions(self):
        from rshelper.models import Item
        from rshelper.scanner import FlipScanner
        item=Item(1,'Synthetic',False,100,0,100,110,20)
        scanner=FlipScanner(direction='arbitrage')
        explanation=scanner.explain(item,min_volume=10)
        result=scanner.scan([item],min_volume=10)[0]
        self.assertEqual(explanation['net_profit'],result.profit)
        self.assertEqual(explanation['gp_per_hour'],result.gp_per_hour)
        self.assertEqual(explanation['tax'],2);self.assertEqual(explanation['sell_leg_price'],110)
        self.assertEqual(explanation['exclusion_reasons'],[])
        excluded=scanner.explain(item,members_only=True,min_volume=21,min_margin=11)
        self.assertTrue(any('membership' in reason for reason in excluded['exclusion_reasons']))
        self.assertTrue(any('volume' in reason for reason in excluded['exclusion_reasons']))
        self.assertTrue(any('margin' in reason for reason in excluded['exclusion_reasons']))
        traditional=FlipScanner(direction='traditional').explain(item)
        self.assertEqual(traditional['buy_leg_price'],110);self.assertEqual(traditional['sell_leg_price'],100)
        self.assertEqual(traditional['tax'],2)
        self.assertAlmostEqual(traditional['margin_pct'],-10/110*100)
        self.assertAlmostEqual(traditional['roi_pct'],-12/110*100)
        self.assertEqual(explanation['ranking_basis'],'illustrative net profit times throughput; RS score is secondary')
        self.assertTrue(any('net profit' in reason for reason in traditional['exclusion_reasons']))

    def test_http_catalog_policy_and_bounded_queries(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from rshelper.dashboard.handlers import make_handler
        from rshelper.models import Item
        from rshelper.scanner import FlipScanner
        for mode in ('owner','public-demo'):
            calls=[]
            def catalog(query,limit):calls.append(query);return {'items':[{'id':1,'name':'Synthetic'}]}
            handler=make_handler(FlipScanner(),lambda:[Item(2,'Synthetic priced',False,100,0,100,110,20),Item(3,'Excluded',False,100,0,110,100,20)],mode=mode,owner_token='synthetic-token',
                catalog_fn=catalog,item_details_fn=lambda iid:{'id':iid,'quote':{'usable':False}})
            server=ThreadingHTTPServer(('127.0.0.1',0),handler)
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                base='http://127.0.0.1:'+str(server.server_port)
                headers={'Authorization':'Bearer synthetic-token'} if mode=='owner' else {}
                if mode=='owner':
                    with self.assertRaises(HTTPError) as denied:urlopen(base+'/api/catalog?q=x')
                    self.assertEqual(denied.exception.code,401);self.assertEqual(calls,[])
                with urlopen(Request(base+'/api/catalog?q=Synthetic&limit=50',headers=headers)) as response:
                    response=json.load(response)
                self.assertEqual(response['items'][0]['id'],1)
                with urlopen(Request(base+'/api/item?id=1',headers=headers)) as response:
                    self.assertEqual(json.load(response)['id'],1)
                count=len(calls)
                for query in ('q='+('x'*201),'q=x&q=x','limit=51','limit=0','secret=x'):
                    with self.subTest(mode=mode,query=query),self.assertRaises(HTTPError) as rejected:
                        urlopen(Request(base+'/api/catalog?'+query,headers=headers))
                    self.assertEqual(rejected.exception.code,400)
                for query in ('','id=0','id=abc','id=1&id=2','id=1&token=x'):
                    with self.subTest(mode=mode,query=query),self.assertRaises(HTTPError) as rejected:
                        urlopen(Request(base+'/api/item?'+query,headers=headers))
                    self.assertEqual(rejected.exception.code,400)
                self.assertEqual(len(calls),count)
                with urlopen(Request(base+'/api/scan',headers=headers)) as response:
                    scan=json.load(response)
                explanation=scan['items'][0]['explanation']
                self.assertEqual(scan['items'][0]['profit'],explanation['net_profit'])
                self.assertEqual(explanation['tax'],2)
                self.assertEqual(scan['exclusions']['net profit'],1)
            finally:server.shutdown();thread.join(timeout=2);server.server_close()

    def test_cli_resolvers_and_missing_quote_metadata(self):
        import argparse,io
        from contextlib import redirect_stdout,redirect_stderr
        from unittest import mock
        from rshelper import cli
        mapping=[{'id':1,'name':'Synthetic','members':False,'limit':100,'highalch':200},
                 {'id':2,'name':'Synthetic (p)','members':False}]
        args=argparse.Namespace(item='Synthetic',profile='default',json=True,timeseries=False)
        self.assertEqual(cli._resolve_item(args,mapping)['id'],1)
        self.assertEqual(cli._resolve_item(argparse.Namespace(item='(p)',json=True),mapping)['id'],2)
        with mock.patch.object(cli,'fetch_mapping_result',return_value=mapping), \
             mock.patch.object(cli,'fetch_latest_result',return_value={}), \
             redirect_stdout(io.StringIO()) as stdout,redirect_stderr(io.StringIO()):
            cli.item_info(args)
        result=json.loads(stdout.getvalue());self.assertEqual(result['id'],1)
        for key in ('buy_price','sell_price','flip_profit','flip_tax','alch_profit'):self.assertIsNone(result[key])
        self.assertEqual(result['alch_value'],200);self.assertTrue(result['price_warning'])

    def test_runtime_catalog_and_watch_callbacks_include_unpriced_mapping_item(self):
        from unittest import mock
        from rshelper.config import Config
        from rshelper.dashboard import server
        callbacks={};case=self
        def capture(*args,**kwargs):callbacks.update(kwargs);return object
        class FakeServer:
            def __init__(self,*args):pass
            def server_close(self):pass
            def serve_forever(self):
                case.assertEqual(callbacks['catalog_fn']('Synthetic',50)['items'][0]['id'],1)
                detail=callbacks['item_details_fn'](1)
                case.assertFalse(detail['quote']['usable']);case.assertFalse(detail['scan_eligible'])
                callbacks['watchlist_update_fn']('add',1)
        with mock.patch.object(server,'load_config',return_value=Config()), \
             mock.patch.object(server,'_fetch_bootstrap',return_value=([{'id':1,'name':'Synthetic'}],{},{},[])), \
             mock.patch.object(server,'make_handler',side_effect=capture), \
             mock.patch.object(server,'ThreadingHTTPServer',FakeServer), \
             mock.patch.object(server.watchlist,'load',return_value={'items':{}}), \
             mock.patch.object(server.watchlist,'add') as add, \
             mock.patch('rshelper.tuning.record_if_changed'):
            server.run(port=0,profile='default',owner_token='a'*64)
        add.assert_called_once_with(1,'Synthetic',profile='default')

    def test_runtime_history_and_watch_economics_are_explicit_and_directional(self):
        import time
        from unittest import mock
        from rshelper.config import Config
        from rshelper.dashboard import server
        from rshelper.market_data import MarketDataResult
        now=int(time.time()); stamp=now//300*300
        config=Config();config.flip.direction='traditional'
        callbacks={};case=self
        def capture(*args,**kwargs):callbacks.update(kwargs);return object
        class FakeServer:
            def __init__(self,*args):pass
            def server_close(self):pass
            def serve_forever(self):
                rows={row['id']:row for row in callbacks['watchlist_fn']()['items']}
                row=rows[1]
                case.assertEqual((row['buy'],row['sell'],row['tax'],row['net_profit']), (110,100,2,-12))
                case.assertAlmostEqual(row['margin_pct'],-10/110*100)
                for item_id,reason in ((2,'no data'),(3,'stale')):
                    case.assertFalse(rows[item_id]['usable']);case.assertEqual(rows[item_id]['reason'],reason)
                    case.assertFalse({'tax','net_profit','margin_pct'} & rows[item_id].keys())
                history=callbacks['timeseries_fn'](1)
                case.assertEqual(history['points'][0]['net_profit'],8)
                case.assertEqual(history['points'][0]['direction'],'traditional')
        candles=[{'timestamp':stamp-300,'avgHighPrice':110,'avgLowPrice':100,
                  'highPriceVolume':10,'lowPriceVolume':10}]
        result=MarketDataResult(candles,'wiki','network',now,now,now,False,'executed-trades',{'wiki':1})
        latest={'1':{'high':110,'low':100,'highTime':now,'lowTime':now},
                '2':{'high':0,'low':100,'highTime':now,'lowTime':now},
                '3':{'high':110,'low':100,'highTime':now-90000,'lowTime':now-90000}}
        with mock.patch.object(server,'load_config',return_value=config), \
             mock.patch.object(server,'_fetch_bootstrap',return_value=([{'id':1,'name':'Synthetic'}],latest,{},[])), \
             mock.patch.object(server,'make_handler',side_effect=capture), \
             mock.patch.object(server,'ThreadingHTTPServer',FakeServer), \
             mock.patch.object(server.watchlist,'load',return_value={'items':{str(key):{'name':'Synthetic '+str(key)} for key in (1,2,3)}}), \
             mock.patch('rshelper.api.fetch_timeseries_result',return_value=result), \
             mock.patch('rshelper.tuning.record_if_changed'):
            server.run(port=0,profile='default',owner_token='a'*64)

    def test_id_exact_numeric_name_ambiguity_and_bounded_stable_search(self):
        from rshelper.catalog import resolve_item,search_catalog
        mapping=[{'id':3,'name':'2'},{'id':2,'name':'Rune sword'},{'id':4,'name':'Rune sword (p)'},
                 {'id':5,'name':'Duplicate'},{'id':6,'name':'Duplicate'}]
        self.assertEqual(resolve_item('2',mapping)['id'],2)
        self.assertEqual(resolve_item('3',mapping)['name'],'2')
        self.assertEqual(resolve_item(' Rune Sword ',mapping)['id'],2)
        self.assertEqual(resolve_item('Rune sword (p)',mapping)['id'],4)
        for query in ('Rune','Duplicate','absent',''):
            with self.subTest(query=query),self.assertRaises(ValueError):resolve_item(query,mapping)
        self.assertEqual(search_catalog('rune',mapping),search_catalog('rune',list(reversed(mapping))))
        self.assertEqual(len(search_catalog('',mapping,limit=2)),2)
        with self.assertRaises(ValueError):search_catalog('x'*201,mapping)
        with self.assertRaises(ValueError):search_catalog('',mapping,limit=51)
        self.assertEqual(search_catalog('anything',[]),[])
        self.assertEqual(resolve_item('42',[{'id':99,'name':'42'}])['id'],99)

    def test_metadata_survives_missing_quote_and_economics_are_server_values(self):
        from rshelper.catalog import item_details
        from rshelper.market_data import MarketDataResult,market_payload
        now=1791810000
        mapping=[{'id':1,'name':'<Synthetic>','members':False,'limit':100,'highalch':200}]
        missing=item_details('1',mapping,{},now=now)
        self.assertEqual(missing['name'],'<Synthetic>');self.assertFalse(missing['quote']['usable'])
        self.assertIsNone(missing['quote']['buy_price']);self.assertIsNone(missing['quote']['net_profit'])
        latest=market_payload(MarketDataResult({'1':{'high':100,'low':110,'highTime':now,'lowTime':now}},
            'wiki','network',now,now,now,False,'unknown',{'wiki':1}))
        detail=item_details('1',mapping,latest,now=now)
        self.assertTrue(detail['quote']['usable']);self.assertEqual(detail['quote']['tax'],2)
        self.assertEqual(detail['quote']['net_profit'],8)
        self.assertEqual(detail['quote']['buy_price'],100);self.assertEqual(detail['quote']['sell_price'],110)
        self.assertEqual(detail['market_data']['latest']['source'],'wiki')
        stale=market_payload(MarketDataResult(dict(latest),'wiki','stale-cache',now,now,now,True,'unknown',{'wiki':1}))
        self.assertFalse(item_details('1',mapping,stale,now=now)['quote']['usable'])


if __name__=='__main__':unittest.main()
