import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper.scenarios import evaluate_scenario
from rshelper.market import ge_tax

class ScenarioTest(unittest.TestCase):
    def setUp(self):
        self.holdings=[{'item_id':2,'qty':3,'buy_price':80,'direction':'traditional','high':100,'low':90,'group':'metal'},
                       {'item_id':2,'qty':2,'buy_price':75,'direction':'arbitrage','high':100,'low':90,'group':'metal'}]
        self.cash={'available':1000,'reserved':500}
        self.spec={'schema_version':1,'lane':'paper','price_leg':'direction','all_bps':0,'item_bps':{},'group_bps':{},'haircut_bps':0}

    def test_zero_shock_mixed_lots_cash_and_concentration_reconcile(self):
        result=evaluate_scenario(self.holdings,self.cash,'a'*64,self.spec)
        self.assertEqual(result['baseline_gross'],480)
        net=(100-ge_tax(100))*3+(90-ge_tax(90))*2
        self.assertEqual(result['modeled_after_tax'],net)
        self.assertEqual(result['scenario_equity'],1500+net)
        self.assertEqual(result['equity_change_pct'],0)
        self.assertEqual(result['concentration'][0]['share_pct'],100)
        self.assertEqual(result['cash'],self.cash)

    def test_item_group_shocks_haircut_and_unit_tax_floor_cap(self):
        specification={**self.spec,'all_bps':-1000,'item_bps':{'2':-500},'group_bps':{'metal':500},'haircut_bps':200}
        result=evaluate_scenario(self.holdings,self.cash,'a'*64,specification)
        self.assertEqual(result['modeled_after_tax'],(88-ge_tax(88))*3+(79-ge_tax(79))*2)
        self.holdings[0].update(high=49)
        floor=evaluate_scenario(self.holdings[:1],self.cash,'a'*64,self.spec)
        self.assertEqual(floor['modeled_after_tax'],147)
        self.holdings[0].update(high=400000000)
        cap=evaluate_scenario(self.holdings[:1],self.cash,'a'*64,self.spec)
        self.assertEqual(cap['modeled_after_tax'],(400000000-5000000)*3)

    def test_missing_leg_and_cash_never_make_unknown_total_zero(self):
        self.holdings[1]['low']=None
        result=evaluate_scenario(self.holdings,self.cash,'a'*64,self.spec)
        self.assertEqual(result['missing_item_ids'],[2])
        self.assertIsNone(result['modeled_after_tax']);self.assertIsNone(result['equity_change_pct'])
        self.assertIsNone(result['concentration'][0]['share_pct'])
        self.assertIsNone(result['concentration'][0]['baseline_gross'])
        self.assertEqual(result['concentration'][0]['known_baseline_gross'],300)
        self.holdings[1]['low']=90
        result=evaluate_scenario(self.holdings,{'available':None,'reserved':None},'a'*64,{**self.spec,'lane':'observed-manual'})
        self.assertIsNone(result['scenario_equity']);self.assertIsNone(result['equity_change_pct'])
        self.assertEqual(result['lane'],'observed-manual')

    def test_frozen_input_reproduces_and_invalid_scope_or_amount_refuses(self):
        frozen=copy.deepcopy((self.holdings,self.cash,self.spec))
        first=evaluate_scenario(self.holdings,self.cash,'a'*64,self.spec)
        self.assertEqual(first,evaluate_scenario(**first['input']))
        self.assertEqual((self.holdings,self.cash,self.spec),frozen)
        for changes in ({'all_bps':-10001},{'item_bps':{'999':10}},{'group_bps':{'unreviewed':10}},{'haircut_bps':True},{'lane':'live'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):evaluate_scenario(self.holdings,self.cash,'a'*64,{**self.spec,**changes})

    def test_cli_frozen_input_json_and_unknown_bank_marks_are_read_only(self):
        import contextlib,io,json,tempfile
        from unittest import mock
        from types import SimpleNamespace
        from rshelper import bank,cli,profile,positions
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'scenario.json'
            source.write_text(json.dumps({'holdings':self.holdings,'cash':self.cash,'market_revision':'a'*64,'specification':self.spec}))
            output=io.StringIO()
            with mock.patch.object(profile,'CONFIG_DIR',root/'state'),mock.patch.object(sys,'argv',['rshelper','--profile','default','scenario','--input',str(source),'--json']),contextlib.redirect_stdout(output):cli.main()
            self.assertEqual(json.loads(output.getvalue())['baseline_gross'],480)
            self.assertFalse((root/'state').exists())
            with mock.patch.object(bank,'list_positions',return_value=[SimpleNamespace(item_id=2,qty=2,buy_price=100,direction='traditional')]),mock.patch.object(profile,'CONFIG_DIR',root/'state'),mock.patch.object(positions,'POSITIONS_PATH',root/'state/positions.json'):
                frozen=bank.build_scenario_input(profile='default',latest={},now=1000)
            self.assertIsNone(evaluate_scenario(**frozen)['baseline_gross'])
            self.assertIsNone(frozen['cash']['available'])

    def test_private_http_calculation_has_no_profile_write_or_public_access(self):
        import http.client,json,threading
        from http.server import ThreadingHTTPServer
        from rshelper.dashboard.handlers import make_handler
        from rshelper.scanner import FlipScanner
        frozen={'holdings':self.holdings,'cash':self.cash,'market_revision':'a'*64,'specification':self.spec}
        calls=[]
        def scenario(body=None):
            calls.append(body)
            return frozen if body is None else evaluate_scenario(**body)
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(FlipScanner(),lambda:[],owner_token='a'*64,scenario_fn=scenario));server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            def request(body=None,auth=True):
                client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
                client.request('GET' if body is None else 'POST','/api/scenario',None if body is None else json.dumps(body),{'Authorization':'Bearer '+'a'*64} if auth else {})
                response=client.getresponse();raw=response.read();client.close();return response.status,raw
            self.assertEqual(request(auth=False)[0],401);self.assertFalse(calls)
            self.assertEqual(request()[0],200)
            status,raw=request(frozen);self.assertEqual(status,200);self.assertEqual(json.loads(raw)['baseline_gross'],480)
            self.assertEqual(request({**frozen,'specification':{**self.spec,'all_bps':True}})[0],400)
            self.assertEqual(request({**frozen,'extra':'private'})[0],400)
            self.assertEqual(frozen['holdings'],self.holdings)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

if __name__=='__main__':unittest.main()
