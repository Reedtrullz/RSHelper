from dataclasses import replace
import argparse
import contextlib
import csv
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper.models import Item
from rshelper.recipes import Recipe,RECIPES,recipe_breakdown,process_payload
from rshelper.market import ge_tax
from rshelper.scanner import ProcessScanner
from rshelper import cli,config
from rshelper.dashboard import server

def item(iid,buy,sell,limit=10000,volume=1000):
    return Item(iid,str(iid),False,limit,0,buy,sell,volume)

class RecipeEvidenceTest(unittest.TestCase):
    def test_batch_units_tax_and_fees_share_one_breakdown(self):
        recipe = Recipe(1,{2:15},'fletching',2400,outputs_per_run=15,
                        cost_per_unit=2,rate_basis='outputs-per-hour',yield_reviewed=True,success_probability=1.0,
                        requirements={'members':True,'level':1,'unlocks':[]})
        prices = {1:item(1,110,100,limit=1),2:item(2,10,9)}
        result = recipe_breakdown(recipe,prices,{'members':True,'levels':{'fletching':1},'unlocks':[]})
        self.assertEqual(result['input_cost_per_run'],150)
        self.assertEqual(result['tax_per_output'],ge_tax(100))
        self.assertEqual(result['profit_per_output'],86)
        self.assertEqual(result['rate_runs_per_hour'],160)
        self.assertEqual(result['model_gp_per_hour'],86*2400)
        self.assertEqual(result['eligibility'],'eligible')
        self.assertIsNone(result['gp_per_hour'])
        scan = ProcessScanner(recipes={1:recipe}).scan(list(prices.values()))[0]
        self.assertEqual(scan.recipe_economics['model_gp_per_hour'],scan.gp_per_hour)
        payload = process_payload(scan)
        self.assertEqual(payload['model_gp_per_hour'],result['model_gp_per_hour'])
        self.assertEqual(payload['profit'],result['profit_per_output'])
        self.assertIsNone(payload['gp_per_hour'])
        self.assertEqual(payload['roi'],payload['roi_pct'])

    def test_members_filter_selects_member_methods_in_both_directions(self):
        recipe = Recipe(1,{2:1},'magic',100,requirements={'members':True,'level':1,'unlocks':[]})
        prices = [item(1,100,90),item(2,10,9)]
        self.assertEqual(len(ProcessScanner(recipes={1:recipe}).scan(prices,members_only=True)),1)
        self.assertEqual(len(ProcessScanner(recipes={1:recipe}).scan(prices,members_only=False)),1)

    def test_unknown_or_zero_input_limit_cannot_disappear(self):
        recipe = Recipe(1,{2:1,3:1},'smithing',100)
        for limit in (0,):
            with self.subTest(limit=limit):
                prices = {1:item(1,100,90),2:item(2,10,9),3:item(3,10,9,limit=limit)}
                result = recipe_breakdown(recipe,prices,None)
                self.assertEqual(result['model_gp_per_hour'],0)
                self.assertIn('input buy limit unknown',result['limiting_factors'])

    def test_output_buy_limit_does_not_cap_sales(self):
        recipe = Recipe(1,{2:1},'smithing',100)
        one = recipe_breakdown(recipe,{1:item(1,100,90,limit=1),2:item(2,10,9)},None)
        other = recipe_breakdown(recipe,{1:item(1,100,90,limit=10000),2:item(2,10,9)},None)
        self.assertEqual(one['model_gp_per_hour'],other['model_gp_per_hour'])
        self.assertGreater(one['model_gp_per_hour'],1000)

    def test_account_config_preserves_unknown_facts_and_validates_before_scan(self):
        recipe = Recipe(1,{2:1},'magic',100,requirements={'members':True,'level':66,'unlocks':['route']})
        prices = {1:item(1,100,90),2:item(2,10,9)}
        cfg = config.validate_config(config.Config())
        self.assertEqual(recipe_breakdown(recipe,prices,cfg.account.recipe_context())['eligibility'],'unknown')
        cfg.account.membership='member'
        cfg.account.levels={'magic':66}
        self.assertEqual(recipe_breakdown(recipe,prices,cfg.account.recipe_context())['eligibility'],'unknown')
        cfg.account.unlocks={'route':False}
        self.assertEqual(recipe_breakdown(recipe,prices,cfg.account.recipe_context())['eligibility'],'ineligible')
        cfg.account.unlocks={'route':True}
        self.assertEqual(recipe_breakdown(recipe,prices,cfg.account.recipe_context())['eligibility'],'eligible')
        for values in ({'levels':{'magic':True}},{'levels':{'magic':100}},
                       {'unlocks':{'route':1}},{'membership':'invented'}):
            bad = config.Config(account=config.AccountConfig(**values))
            with self.subTest(values=values),self.assertRaises(config.ConfigError):config.validate_config(bad)

    def test_csv_and_fractional_roi_keep_qualified_values_and_clean_stdout(self):
        recipe = Recipe(1,{2:1},'magic',100,outputs_per_run=3,yield_reviewed=True,success_probability=1.0)
        prices = [item(1,100,90),item(2,10,9)]
        scan = ProcessScanner(recipes={1:recipe}).scan(prices)[0]
        self.assertAlmostEqual(cli._process_roi(scan),scan.profit/(10/3)*100)
        unknown = replace(recipe,yield_reviewed=False)
        args = argparse.Namespace(profile=None,members_only=False,min_volume=0,min_profit=0,
                                  capital=0,skill='',top=10,name='',csv=True,json=False,html=False)
        out,err = io.StringIO(),io.StringIO()
        with mock.patch.object(cli,'_fetch_bootstrap',return_value=({}, {}, {},prices)),\
                mock.patch.object(config,'load_config',return_value=config.Config()),\
                mock.patch.object(cli,'load_config',return_value=config.Config()),\
                mock.patch('rshelper.scanner.ProcessScanner',return_value=ProcessScanner(recipes={1:unknown})),\
                contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            cli.process_scan(args)
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['profit'],'')
        self.assertEqual(rows[0]['roi'],'')
        self.assertEqual(rows[0]['gp_per_hour'],'')
        self.assertGreater(int(rows[0]['model_gp_per_hour']),0)
        self.assertIn('positive illustrative',err.getvalue())

    def test_public_process_does_not_derive_owner_account_eligibility(self):
        cfg = config.Config(account=config.AccountConfig(membership='member',levels={'smithing':99}))
        prices = [item(2353,800,700),item(440,100,90),item(453,100,90)]
        for mode,expected in (('owner','eligible'),('public-demo','unknown')):
            callbacks = {}
            class HttpServer:
                def __init__(self,*args):pass
                def serve_forever(inner):
                    result = callbacks['process_fn']()['recipes']
                    self.assertEqual(next(row for row in result if row['item_id']==2353)['eligibility'],expected)
                def server_close(self):pass
            def handler(*args,**kwargs):
                callbacks.update(kwargs)
                return object
            with contextlib.ExitStack() as stack:
                for target,name,value in ((server,'load_config',lambda *args:cfg),
                        (server,'_fetch_bootstrap',lambda *args:({}, {}, {},prices)),
                        (server,'ThreadingHTTPServer',HttpServer),(server,'make_handler',handler)):
                    stack.enter_context(mock.patch.object(target,name,value))
                stack.enter_context(mock.patch('rshelper.tuning.record_if_changed'))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
                server.run(port=0,access_mode=mode,owner_token='a'*64 if mode=='owner' else None)

    def test_iron_furnace_losses_and_account_unknown_are_explicit(self):
        result = recipe_breakdown(RECIPES[2351],{2351:item(2351,200,126),440:item(440,100,90)},None)
        self.assertEqual(result['success_probability'],.5)
        self.assertLess(result['profit_per_output'],0)
        self.assertEqual(result['eligibility'],'unknown')
        self.assertIn('level unknown',result['eligibility_reasons'])

    def test_unknown_success_and_unverified_rate_are_quarantined(self):
        self.assertIsNone(Recipe(1,{2:1},'magic',100).success_probability)
        recipe = replace(RECIPES[385],success_probability=None)
        result = recipe_breakdown(recipe,{385:item(385,200,180),383:item(383,100,90)},None)
        self.assertIsNone(result['profit_per_output'])
        self.assertIsNone(result['gp_per_hour'])
        self.assertIn('success probability unknown',result['evidence_gaps'])
        self.assertIn('rate unverified',result['evidence_gaps'])

    def test_membership_level_and_unlocks_never_assume_eligibility(self):
        recipe = Recipe(1,{2:1},'magic',100,requirements={'members':True,'level':66,'unlocks':['route']})
        prices = {1:item(1,100,90),2:item(2,10,9)}
        self.assertEqual(recipe_breakdown(recipe,prices,{})['eligibility'],'unknown')
        self.assertEqual(recipe_breakdown(recipe,prices,{'members':False})['eligibility'],'ineligible')
        self.assertEqual(recipe_breakdown(recipe,prices,{'members':True,'levels':{'magic':65}})['eligibility'],'ineligible')
        self.assertEqual(recipe_breakdown(recipe,prices,{'members':True,'levels':{'magic':66}})['eligibility'],'unknown')
        self.assertEqual(recipe_breakdown(recipe,prices,{'members':True,'levels':{'magic':66},'unlocks':['route']})['eligibility'],'eligible')
        for account in ('bad',{'members':1},{'levels':{'magic':'66'}},{'levels':{'magic':100}},
                        {'levels':{str(i):1 for i in range(101)}},{'unlocks':'route'},
                        {'unlocks':{'route':1}}):
            with self.subTest(account=account),self.assertRaises(ValueError):
                recipe_breakdown(recipe,prices,account)

    def test_capital_sell_volume_and_missing_method_membership_are_bounded(self):
        recipe = Recipe(1,{2:1},'smithing',100,success_probability=1.0)
        prices = {1:item(1,100,90,volume=1),2:item(2,10,9)}
        result = recipe_breakdown(recipe,prices,capital=100)
        self.assertEqual(result['model_runs_per_hour'],10)
        self.assertEqual(result['limiting_factors'],['capital'])
        result = recipe_breakdown(recipe,prices)
        self.assertEqual(result['model_runs_per_hour'],12)
        self.assertIn('illustrative sell volume',result['limiting_factors'])
        scanner = ProcessScanner(recipes={1:recipe})
        self.assertEqual(scanner.scan(list(prices.values()),members_only=True),[])
        prices[1].members=True
        self.assertEqual(len(scanner.scan(list(prices.values()),members_only=True)),1)

if __name__ == '__main__':
    unittest.main()
