import sys
import copy
import contextlib
import io
import json
import threading
import unittest
from pathlib import Path
from uuid import uuid4
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_native_writers import DisposableHomeTest
from rshelper import positions, profile, state_transaction
from rshelper import paper_book,cli
from rshelper.config import Config
from rshelper import journal, realization
from rshelper.market_data import MarketDataResult,market_payload

class PaperBookTest(DisposableHomeTest):
    def setUp(self):
        super().setUp()
        self.activate()
        self.now=20000

    def initialize(self,slots: int | None=3,bankroll=1000):
        return paper_book.initialize_budget(None,bankroll=bankroll,slot_limit=slots,
                    operation_id=str(uuid4()),now=self.now)

    def reserve(self,operation_id=None,revision=1,qty=6):
        return paper_book.reserve_budget(None,item_id=2,name='Synthetic',qty=qty,
                    buy_price=100,buy_limit=100,members=False,direction='traditional',note='manual',
                    expected_revision=revision,operation_id=operation_id or str(uuid4()),now=self.now)

    def test_atomic_reservation_exact_retry_and_conflicting_operation(self):
        self.initialize()
        operation=str(uuid4())
        first=self.reserve(operation)
        self.assertEqual(first['budget']['reserved_cash'],600)
        self.assertEqual(first['budget']['available_cash'],400)
        self.assertEqual(first['budget']['used_slots'],1)
        replay=self.reserve(operation)
        self.assertTrue(replay['retry'])
        self.assertEqual(replay['offer_id'],first['offer_id'])
        self.assertEqual(replay['revision'],2)
        self.assertEqual(positions.list_positions(),[])
        with self.assertRaisesRegex(ValueError,'operation'):
            self.reserve(operation,qty=5)
        with self.assertRaisesRegex(ValueError,'cash'):
            self.reserve(revision=2)

    def test_actual_owner_http_reserves_fills_sells_and_collects_in_separate_steps(self):
        from http.server import ThreadingHTTPServer
        from urllib import request,error
        from rshelper.dashboard.handlers import make_handler
        from rshelper.dashboard.server import paper_request
        from rshelper.ge_offers import build_ge_slots
        from rshelper.scanner import FlipScanner
        self.now=19800
        self.initialize()
        clock=[self.now]
        def refresh():
            market=self.market(clock[0]-300)
            return {'mapping':[{'id':2,'name':'Synthetic','limit':100,'members':False}],
                    'latest':market['latest'],'vol':market['5m']}
        handler=make_handler(FlipScanner(),lambda:[],owner_token='a'*64,
            paper_trade_fn=lambda body:paper_request(None,body,refresh,'traditional'),
            ge_fn=lambda:build_ge_slots(latest=refresh()['latest'],now=clock[0]))
        server=ThreadingHTTPServer(('127.0.0.1',0),handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        opener=request.build_opener(request.ProxyHandler({}))
        url='http://127.0.0.1:'+str(server.server_port)
        def get():
            return json.load(opener.open(request.Request(url+'/api/ge',headers={'Authorization':'Bearer '+'a'*64}),timeout=5))
        def post(action,**fields):
            body={'action':action,'operation_id':str(uuid4()),'expected_revision':get()['revision'],**fields}
            response=opener.open(request.Request(url+'/api/paper',data=json.dumps(body).encode(),
                headers={'Authorization':'Bearer '+'a'*64,'Content-Type':'application/json'}),timeout=5)
            return json.load(response)
        try:
            with mock.patch('time.time',side_effect=lambda:clock[0]):
                with self.assertRaises(error.HTTPError) as denied:opener.open(url+'/api/ge',timeout=5)
                self.assertEqual(denied.exception.code,401)
                queued=post('open',item='Synthetic',qty=3)
                offer_id=queued['offer_id']
                self.assertNotIn('offers',queued)
                self.assertEqual(positions.list_positions(),[])
                self.assertEqual(get()['slots'][0]['stage'],'buying')
                revision=get()['revision']
                with self.assertRaises(error.HTTPError) as invalid:post('advance',offer_id=7)
                self.assertEqual(invalid.exception.code,400)
                self.assertEqual(get()['revision'],revision)
                clock[0]=20400
                post('advance',offer_id=offer_id)
                self.assertEqual(positions.list_positions()[0].qty,3)
                post('start-sale',offer_id=offer_id,qty=3,sell_price=120)
                self.assertEqual(journal.list_trades(),[])
                clock[0]=21000
                post('advance',offer_id=offer_id)
                self.assertEqual(get()['slots'][0]['stage'],'collectable')
                post('collect',offer_id=offer_id)
                self.assertEqual(journal.list_trades()[0].profit,54)
                self.assertEqual(positions.list_positions(),[])
                self.assertEqual(get()['budget']['available_cash'],1054)
        finally:
            server.shutdown();server.server_close();thread.join(5)

    def test_concurrent_entries_cannot_both_spend_the_same_cash(self):
        self.initialize()
        barrier=threading.Barrier(2)
        results=[]
        def reserve():
            barrier.wait()
            try:results.append(self.reserve())
            except ValueError as exc:results.append(str(exc))
        threads=[threading.Thread(target=reserve) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(10);self.assertFalse(thread.is_alive())
        self.assertEqual(sum(isinstance(result,dict) for result in results),1)
        summary=paper_book.budget_snapshot(None,now=self.now)
        self.assertEqual(summary['budget']['reserved_cash'],600)

    def test_durable_intent_recovers_reservation_without_duplicate(self):
        self.initialize()
        operation=str(uuid4())
        with mock.patch.object(state_transaction,'_checkpoint',side_effect=RuntimeError('crash')):
            with self.assertRaisesRegex(RuntimeError,'crash'):self.reserve(operation)
        state_transaction.recover_profile(profile.CONFIG_DIR)
        replay=self.reserve(operation)
        self.assertTrue(replay['retry'])
        self.assertEqual(replay['budget']['reserved_cash'],600)

    def test_unknown_account_and_legacy_purchase_history_block_entries(self):
        self.initialize(slots=None)
        with self.assertRaisesRegex(ValueError,'slot'):self.reserve()
        root=profile.CONFIG_DIR
        self._swap(positions,'POSITIONS_PATH',root/'profiles'/'old'/'positions.json')
        state_transaction.activate_profile(positions.POSITIONS_PATH.parent,
                    '33333333-3333-4333-8333-333333333333',financial_authority=True)
        positions.open_position(2,'Old',1,100)
        paper_book.initialize_budget(None,bankroll=1000,slot_limit=3,
                    operation_id=str(uuid4()),now=self.now)
        with self.assertRaisesRegex(ValueError,'history'):self.reserve()

    def test_cancel_releases_only_pending_cash_and_retries_without_new_revision(self):
        self.initialize()
        first=self.reserve()
        operation=str(uuid4())
        canceled=paper_book.cancel_buy(None,first['offer_id'],expected_revision=2,
                    operation_id=operation,now=self.now)
        self.assertEqual(canceled['budget']['reserved_cash'],0)
        self.assertEqual(canceled['budget']['used_slots'],0)
        self.assertEqual(canceled['offers'][first['offer_id']]['offer']['stage'],'canceled')
        replay=paper_book.cancel_buy(None,first['offer_id'],expected_revision=2,
                    operation_id=operation,now=self.now)
        self.assertTrue(replay['retry'])
        self.assertEqual(replay['revision'],3)

    def test_replica_and_unknown_order_limits_cannot_reserve(self):
        self.initialize()
        with self.assertRaises(ValueError):
            paper_book.reserve_budget(None,item_id=2,name='Synthetic',qty=1,buy_price=100,
                buy_limit=0,direction='traditional',note='manual',expected_revision=1,
                operation_id=str(uuid4()),now=self.now)
        self.assertEqual(paper_book.budget_snapshot(None,now=self.now)['revision'],1)
        self.activate(financial_authority=False)
        with self.assertRaisesRegex(ValueError,'authority'):self.reserve()

    def market(self,window,volume=300):
        def wrapped(data,kind):
            now=window+300
            return market_payload(MarketDataResult(data,'wiki','network',now,now,now,False,kind,{'wiki':1}))
        latest=wrapped({'2':{'high':120,'low':100,'highTime':window+300,'lowTime':window+300}},'unknown')
        candles=wrapped({'2':{'avgLowPrice':100,'avgHighPrice':120,
                               'lowPriceVolume':volume,'highPriceVolume':volume,
                               'window_timestamp':window}},'executed-trades')
        return {'latest':latest,'5m':candles}

    def test_partial_fill_cancel_publishes_only_bought_qty_and_no_double_cost(self):
        self.now=19800
        self.initialize()
        first=self.reserve()
        advanced=paper_book.advance_offer(None,first['offer_id'],self.market(20100),
                    expected_revision=2,operation_id=str(uuid4()),now=20400)
        self.assertEqual(advanced['offers'][first['offer_id']]['offer']['bought_qty'],3)
        self.assertEqual(advanced['budget']['invested_cash'],300)
        self.assertEqual(advanced['budget']['reserved_cash'],300)
        self.assertEqual(positions.list_positions(),[])
        operation=str(uuid4())
        with mock.patch.object(state_transaction,'_checkpoint',side_effect=RuntimeError('crash')):
            with self.assertRaisesRegex(RuntimeError,'crash'):
                paper_book.cancel_buy(None,first['offer_id'],expected_revision=3,
                            operation_id=operation,now=20400)
        state_transaction.recover_profile(profile.CONFIG_DIR)
        result=paper_book.cancel_buy(None,first['offer_id'],expected_revision=3,
                    operation_id=operation,now=20400)
        self.assertEqual(positions.list_positions()[0].qty,3)
        self.assertEqual(result['budget']['invested_cash'],300)
        self.assertEqual(result['budget']['reserved_cash'],0)
        self.assertEqual(result['budget']['used_slots'],1)
        self.assertTrue(result['retry'])

    def test_shared_window_allocation_is_not_reused_by_another_offer(self):
        self.now=19800
        self.initialize(bankroll=5000)
        first=self.reserve(qty=10)
        second=self.reserve(revision=2,qty=10)
        first_result=paper_book.advance_offer(None,first['offer_id'],self.market(20100),
                    expected_revision=3,operation_id=str(uuid4()),now=20400)
        second_result=paper_book.advance_offer(None,second['offer_id'],self.market(20100),
                    expected_revision=4,operation_id=str(uuid4()),now=20400)
        self.assertEqual(first_result['offers'][first['offer_id']]['offer']['bought_qty'],3)
        self.assertEqual(second_result['offers'][second['offer_id']]['offer']['bought_qty'],0)
        self.assertEqual(second_result['budget']['purchase_windows']['2']['purchased_qty'],3)

    def test_sale_requires_post_sale_window_and_owns_its_limit_price(self):
        self.now=19800
        self.initialize()
        first=self.reserve(qty=3)
        bought=paper_book.advance_offer(None,first['offer_id'],self.market(20100),
                    expected_revision=2,operation_id=str(uuid4()),now=20400)
        self.assertEqual(bought['offers'][first['offer_id']]['offer']['stage'],'bought')
        self.assertEqual(positions.list_positions()[0].qty,3)
        selling=paper_book.start_sale(None,first['offer_id'],qty=3,sell_price=120,
                    expected_revision=3,operation_id=str(uuid4()),now=20400)
        self.assertEqual(selling['offers'][first['offer_id']]['offer']['stage'],'selling')
        held=paper_book.advance_offer(None,first['offer_id'],self.market(20100),
                    expected_revision=4,operation_id=str(uuid4()),now=20400)
        self.assertEqual(held['offers'][first['offer_id']]['offer']['sold_qty'],0)
        sold=paper_book.advance_offer(None,first['offer_id'],self.market(20400),
                    expected_revision=5,operation_id=str(uuid4()),now=20700)
        self.assertEqual(sold['offers'][first['offer_id']]['offer']['stage'],'collectable')
        self.assertEqual(sold['offers'][first['offer_id']]['fills'][-1]['tax_paid'],6)

    def collectable(self,sell_price=120):
        self.now=19800
        self.initialize()
        first=self.reserve(qty=3)
        offer_id=first['offer_id']
        with self.assertRaisesRegex(ValueError,'collectable'):
            paper_book.collect_offer(None,offer_id,expected_revision=2,operation_id=str(uuid4()),now=19800)
        paper_book.advance_offer(None,offer_id,self.market(20100),expected_revision=2,operation_id=str(uuid4()),now=20400)
        paper_book.start_sale(None,offer_id,qty=3,sell_price=sell_price,expected_revision=3,operation_id=str(uuid4()),now=20400)
        paper_book.advance_offer(None,offer_id,self.market(20400),expected_revision=4,operation_id=str(uuid4()),now=20700)
        return offer_id

    def test_collection_uses_pinned_fills_and_retains_cash_after_journal_hide(self):
        offer_id=self.collectable()
        operation=str(uuid4())
        result=paper_book.collect_offer(None,offer_id,expected_revision=5,operation_id=operation,now=20700)
        self.assertEqual(result['offers'][offer_id]['offer']['stage'],'collected')
        self.assertEqual(result['budget']['available_cash'],1054)
        self.assertEqual(result['budget']['used_slots'],0)
        self.assertEqual(positions.list_positions(),[])
        trade=journal.list_trades()[0]
        self.assertEqual((trade.qty,trade.sell_price,trade.tax_paid,trade.profit),(3,120,6,54))
        journal.delete_trade(trade.id)
        retry=paper_book.collect_offer(None,offer_id,expected_revision=5,operation_id=operation,now=21000)
        self.assertTrue(retry['retry'])
        self.assertEqual(retry['budget']['available_cash'],1054)
        self.assertEqual(len(journal._load()),1)

    def test_interrupted_collection_blocks_entries_and_resumes_original_operation(self):
        offer_id=self.collectable()
        operation=str(uuid4())
        with mock.patch.object(realization,'realize_close_batch',side_effect=RuntimeError('crash')):
            with self.assertRaisesRegex(RuntimeError,'crash'):
                paper_book.collect_offer(None,offer_id,expected_revision=5,operation_id=operation,now=20700)
        current=paper_book.budget_snapshot(None,now=20700)
        with self.assertRaisesRegex(ValueError,'reconciliation'):
            paper_book.reserve_budget(None,item_id=2,name='Synthetic',qty=1,buy_price=100,buy_limit=100,members=False,
                direction='traditional',note='manual',expected_revision=current['revision'],
                operation_id=str(uuid4()),now=20700)
        result=paper_book.collect_offer(None,offer_id,expected_revision=5,operation_id=operation,now=21000)
        self.assertEqual(result['budget']['available_cash'],1054)
        self.assertEqual(len(journal.list_trades()),1)

    def test_missing_acknowledged_book_cannot_reset_spent_capacity(self):
        self.initialize()
        self.reserve()
        (profile.CONFIG_DIR/'paper-offers.json').unlink()
        with self.assertRaisesRegex(ValueError,'recover'):
            self.initialize()

    def test_realized_loss_reduces_cash_instead_of_becoming_a_refund(self):
        offer_id=self.collectable(sell_price=90)
        result=paper_book.collect_offer(None,offer_id,expected_revision=5,operation_id=str(uuid4()),now=20700)
        self.assertEqual(result['budget']['realized_profit'],-33)
        self.assertEqual(result['budget']['available_cash'],967)
        self.assertEqual(journal.list_trades()[0].profit,-33)

    def test_sale_overflow_leaves_confirmed_hold_and_revision_unchanged(self):
        self.now=19800
        self.initialize()
        first=self.reserve(qty=3)
        paper_book.advance_offer(None,first['offer_id'],self.market(20100),expected_revision=2,operation_id=str(uuid4()),now=20400)
        with self.assertRaisesRegex(ValueError,'monetary bounds'):
            paper_book.start_sale(None,first['offer_id'],qty=3,sell_price=2**62,expected_revision=3,
                        operation_id=str(uuid4()),now=20400)
        self.assertEqual(paper_book.budget_snapshot(None,now=20400)['revision'],3)
        self.assertEqual(positions.list_positions()[0].qty,3)

    def test_owner_capability_update_preserves_receipts_and_visible_overflow(self):
        self.initialize(slots=None)
        before=paper_book._read(profile.CONFIG_DIR)
        operation=str(uuid4())
        changed=paper_book.set_slot_limit(None,3,expected_revision=1,operation_id=operation,now=self.now)
        self.assertEqual(changed['budget']['available_slots'],3)
        paper_book.require_book_successor(before,paper_book._read(profile.CONFIG_DIR))
        retry=paper_book.set_slot_limit(None,3,expected_revision=1,operation_id=operation,now=self.now)
        self.assertTrue(retry['retry'])
        self.reserve(revision=2)

    def test_legacy_holding_keeps_unknown_buy_evidence_and_partial_sale_remainder(self):
        lot=positions.open_position(2,'Historical',5,100,direction='traditional')
        self.now=19800
        self.initialize()
        adopted=paper_book.adopt_holding(None,lot.lot_uid,expected_revision=1,
                    operation_id=str(uuid4()),now=19800)
        offer_id=adopted['offer_id']
        self.assertEqual(adopted['offers'][offer_id]['fills'],[])
        self.assertEqual(adopted['offers'][offer_id]['purchase_basis'],'legacy-recorded-holding')
        self.assertEqual(adopted['budget']['invested_cash'],500)
        self.assertIn('purchase history incomplete',adopted['budget']['unknown'])
        paper_book.start_sale(None,offer_id,qty=5,sell_price=120,expected_revision=2,operation_id=str(uuid4()),now=19800)
        partial=paper_book.advance_offer(None,offer_id,self.market(20100,volume=200),expected_revision=3,operation_id=str(uuid4()),now=20400)
        self.assertEqual(partial['offers'][offer_id]['offer']['sold_qty'],2)
        paper_book.cancel_sale(None,offer_id,expected_revision=4,operation_id=str(uuid4()),now=20400)
        collected=paper_book.collect_offer(None,offer_id,expected_revision=5,operation_id=str(uuid4()),now=20400)
        self.assertEqual(positions.list_positions()[0].qty,3)
        self.assertEqual(collected['budget']['available_cash'],736)
        self.assertEqual(collected['budget']['used_slots'],1)
        next_offer=paper_book.adopt_holding(None,lot.lot_uid,expected_revision=7,operation_id=str(uuid4()),now=20400)['offer_id']
        paper_book.start_sale(None,next_offer,qty=3,sell_price=120,expected_revision=8,operation_id=str(uuid4()),now=20400)
        paper_book.advance_offer(None,next_offer,self.market(20400),expected_revision=9,operation_id=str(uuid4()),now=20700)
        final=paper_book.collect_offer(None,next_offer,expected_revision=10,operation_id=str(uuid4()),now=20700)
        self.assertEqual(final['budget']['available_cash'],1090)
        self.assertEqual(positions.list_positions(),[])
        self.assertEqual(sum(trade.qty for trade in journal.list_trades()),5)

    def test_retained_fill_evidence_rejects_unsupported_price_or_participation(self):
        self.now=19800
        self.initialize()
        first=self.reserve(qty=3)
        paper_book.advance_offer(None,first['offer_id'],self.market(20100),expected_revision=2,
                    operation_id=str(uuid4()),now=20400)
        original=paper_book._read(profile.CONFIG_DIR)
        for key,value in (('executed_volume',200),('observed_price',101)):
            corrupted=copy.deepcopy(original)
            corrupted['offers'][first['offer_id']]['fills'][0][key]=value
            with self.assertRaisesRegex(ValueError,'participation|executed price'):
                paper_book.validate_book(corrupted)

    def test_cli_budget_capability_and_readonly_offers_are_pure_json(self):
        from argparse import Namespace
        self.assertEqual(cli._size_qty(Namespace(qty=0,capital=0),{'limit':100},100),1)
        def invoke(arguments):
            out,err=io.StringIO(),io.StringIO()
            with mock.patch.object(sys,'argv',['rshelper',*arguments]),mock.patch.object(cli,'load_config',return_value=Config()),\
                    contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
                cli.main()
            self.assertEqual(err.getvalue(),'')
            return json.loads(out.getvalue())
        uninitialized=invoke(['trade','budget','--json'])
        self.assertFalse(uninitialized['initialized'])
        initialized=invoke(['trade','budget','--initialize','--bankroll','1000','--membership','free',
                            '--operation-id',str(uuid4()),'--json'])
        self.assertEqual(initialized['budget']['slot_limit'],3)
        updated=invoke(['trade','budget','--membership','member','--expected-revision','1',
                        '--operation-id',str(uuid4()),'--json'])
        self.assertEqual(updated['budget']['slot_limit'],8)
        offers=invoke(['trade','offers','--json'])
        self.assertEqual(offers['offers'],{})
        self.assertEqual(offers['revision'],2)

    def test_cli_open_queues_instead_of_fabricating_a_lot_and_retries_offline(self):
        self.initialize()
        operation=str(uuid4())
        arguments=['trade','open','Synthetic','3','--flip-direction','traditional','--operation-id',operation,'--json']
        def invoke():
            out=io.StringIO()
            with mock.patch.object(sys,'argv',['rshelper',*arguments]),mock.patch.object(cli,'load_config',return_value=Config()),contextlib.redirect_stdout(out):
                cli.main()
            return json.loads(out.getvalue())
        with mock.patch.object(cli,'_resolve_item',return_value={'id':2,'name':'Synthetic','limit':100,'members':False}),\
                mock.patch.object(cli,'_resolve_paper_prices',return_value=(100,120,{'source':'wiki','stale':False,'delivery':'network'})):
            first=invoke()
        self.assertEqual(first['budget']['reserved_cash'],300)
        self.assertEqual(positions.list_positions(),[])
        with mock.patch.object(cli,'_resolve_item',side_effect=AssertionError('retry fetched mapping')),\
                mock.patch.object(cli,'_resolve_paper_prices',side_effect=AssertionError('retry fetched quote')):
            retry=invoke()
        self.assertTrue(retry['retry'])
        self.assertEqual(retry['revision'],2)

    def test_fifo_sale_group_pins_each_direction_and_rejects_partial_group_errors(self):
        first=positions.open_position(2,'Historical',2,100,direction='traditional')
        second=positions.open_position(2,'Historical',2,100,direction='arbitrage')
        self.initialize()
        with self.assertRaisesRegex(ValueError,'quote'):
            paper_book.queue_sales(None,2,3,{'traditional':120},expected_revision=1,
                    operation_id=str(uuid4()),now=self.now)
        self.assertEqual(paper_book.budget_snapshot(None,now=self.now)['revision'],1)
        operation=str(uuid4())
        queued=paper_book.queue_sales(None,2,3,{'traditional':120,'arbitrage':90},expected_revision=1,
                    operation_id=operation,now=self.now)
        self.assertEqual(len(queued['offers']),2)
        by_lot={record['lots'][0]:record['offer'] for record in queued['offers'].values()}
        self.assertEqual((by_lot[first.lot_uid]['sell_price'],by_lot[first.lot_uid]['canceled_sell_qty']),(120,0))
        self.assertEqual((by_lot[second.lot_uid]['sell_price'],by_lot[second.lot_uid]['canceled_sell_qty']),(90,1))
        self.assertEqual(sum(row.qty for row in positions.list_positions()),4)
        self.assertEqual(journal.list_trades(),[])
        retry=paper_book.queue_sales(None,2,3,{'traditional':120,'arbitrage':90},expected_revision=1,
                    operation_id=operation,now=self.now)
        self.assertTrue(retry['retry'])
        self.assertEqual(retry['revision'],2)

    def test_owner_web_request_uses_stages_and_exact_offline_receipts(self):
        from rshelper.dashboard.server import paper_request
        self.now=19800
        self.initialize()
        request={'action':'open','item':'Synthetic','qty':3,'expected_revision':1,
                 'operation_id':str(uuid4())}
        def cache(window):
            market=self.market(window)
            return {'mapping':[{'id':2,'name':'Synthetic','limit':100,'members':False}],
                    'latest':market['latest'],'vol':market['5m']}
        with mock.patch('rshelper.dashboard.server.time.time',return_value=self.now):
            first=paper_request(None,request,lambda:cache(19500),'traditional')
            replay=paper_request(None,request,mock.Mock(side_effect=AssertionError('retry fetched')), 'arbitrage')
        self.assertTrue(replay['retry'])
        self.assertEqual(replay['revision'],2)
        offer_id=first['offer_id']
        def mutate(action,revision,now,**fields):
            body={'action':action,'offer_id':offer_id,'expected_revision':revision,
                  'operation_id':str(uuid4()),**fields}
            with mock.patch('rshelper.dashboard.server.time.time',return_value=now):
                return paper_request(None,body,lambda:cache(now-300),'traditional')
        with self.assertRaisesRegex(ValueError,'collectable'):
            mutate('collect',2,19800)
        mutate('advance',2,20400)
        self.assertEqual(positions.list_positions()[0].qty,3)
        mutate('start-sale',3,20400,qty=3,sell_price=120)
        self.assertEqual(journal.list_trades(),[])
        mutate('advance',4,21000)
        collected=mutate('collect',5,21000)
        self.assertTrue(collected['ok'])
        self.assertEqual(journal.list_trades()[0].profit,54)
        self.assertEqual(positions.list_positions(),[])

    def test_owner_web_rejects_bad_inputs_and_manual_takeover_of_auto_policy(self):
        from rshelper.dashboard.server import paper_request
        self.initialize()
        for change in ({'qty':True},{'expected_revision':True},{'extra':'ignored'}):
            body={'action':'open','item':'Synthetic','qty':1,'expected_revision':1,
                  'operation_id':str(uuid4()),**change}
            with mock.patch('rshelper.dashboard.server.time.time',return_value=self.now):
                with self.assertRaises(ValueError):
                    paper_request(None,body,mock.Mock(side_effect=AssertionError('invalid request fetched')),'traditional')
        automatic=paper_book.reserve_budget(None,item_id=2,name='Synthetic',qty=3,
            buy_price=100,buy_limit=100,members=False,direction='traditional',note='auto',mode='auto',
            expected_revision=1,operation_id=str(uuid4()),now=self.now)
        body={'action':'cancel-buy','offer_id':automatic['offer_id'],
              'expected_revision':2,'operation_id':str(uuid4())}
        with mock.patch('rshelper.dashboard.server.time.time',return_value=self.now):
            with self.assertRaisesRegex(ValueError,'manual'):
                paper_request(None,body,mock.Mock(side_effect=AssertionError('auto action fetched')),'traditional')
        self.assertEqual(paper_book.budget_snapshot(None,now=self.now)['budget']['reserved_cash'],300)

    def test_free_capability_rejects_member_or_unknown_items_without_reserving(self):
        self.initialize()
        for members in (None,True):
            with self.assertRaisesRegex(ValueError,'free account'):
                paper_book.reserve_budget(None,item_id=2,name='Synthetic',qty=1,buy_price=100,
                    buy_limit=100,members=members,direction='traditional',note='manual',
                    expected_revision=1,operation_id=str(uuid4()),now=self.now)
        self.assertEqual(paper_book.budget_snapshot(None,now=self.now)['revision'],1)
        self.assertEqual(self.reserve()['budget']['reserved_cash'],600)

    def test_ge_projection_pages_every_legacy_overflow_without_inventing_execution(self):
        from rshelper.ge_offers import build_ge_slots
        for item_id in range(1,56):
            positions.open_position(item_id,'Legacy '+str(item_id),1,100)
        self.initialize(bankroll=10000)
        first=build_ge_slots(now=self.now)
        second=build_ge_slots(now=self.now,offset=50)
        self.assertEqual((len(first['slots']),len(second['slots'])),(50,5))
        self.assertEqual(first['total_count'],55)
        self.assertEqual(first['budget']['slot_overflow'],52)
        self.assertEqual(first['next_offset'],50)
        self.assertIsNone(second['next_offset'])
        all_rows=first['slots']+second['slots']
        self.assertEqual(len({row['lot_uid'] for row in all_rows}),55)
        self.assertTrue(all(row['stage']=='legacy-unknown' and not row['can_collect'] and row['fill_pct']==0 for row in all_rows))
        self.assertEqual(len(positions.list_positions()),55)
        self.assertEqual(journal.list_trades(),[])

    def test_daemon_purchases_share_manual_cash_and_require_separate_sale_window(self):
        from rshelper import trader
        from rshelper.config import TraderConfig
        from rshelper.models import Item
        self.now=19800
        self.initialize()
        self.reserve()
        cfg=TraderConfig(capital=1000,trade_capital_frac=.4,max_positions=3)
        candidate=Item(id=3,name='Automatic',members=False,buy_limit=100,alch_value=0,
                       buy_price=120,sell_price=100,volume=3000)
        def cycle(now,window,candidates):
            market=self.market(window,volume=1000)
            market['latest']['3']=dict(market['latest']['2'])
            market['5m']['3']=dict(market['5m']['2'])
            with mock.patch.object(trader.time,'time',return_value=now),\
                    mock.patch.object(cli,'_fetch_bootstrap',return_value=([],market['latest'],market['5m'],[candidate])),\
                    mock.patch.object(trader,'select_candidates',return_value=candidates):
                return trader.run_cycle(cfg)
        old_exits=dict(trader._RECENT_EXITS)
        self.addCleanup(trader._RECENT_EXITS.update,old_exits)
        self.addCleanup(lambda:trader._RECENT_EXITS.clear())
        self._swap(trader,'EXITS_PATH',profile.CONFIG_DIR/'recent_exits.json')
        queued=cycle(19800,19500,[candidate])
        self.assertEqual(queued['opened'],[])
        self.assertEqual(queued['queued'][0]['qty'],4)
        self.assertEqual(queued['budget']['reserved_cash'],1000)
        self.assertEqual(positions.list_positions(),[])
        bought=cycle(20400,20100,[])
        self.assertEqual(sum(row['qty'] for row in bought['opened']),10)
        self.assertEqual(bought['closed'],[])
        self.assertEqual(journal.list_trades(),[])
        auto=next(record for record in paper_book.budget_snapshot(None,now=20400)['offers'].values() if record['mode']=='auto')
        self.assertEqual((auto['offer']['stage'],auto['sale_reason']),('selling','take_profit'))
        collected=cycle(21000,20700,[])
        self.assertEqual(collected['closed_pnl'],72)
        self.assertEqual(journal.list_trades()[0].strategy,'auto')
        self.assertEqual(journal.list_trades()[0].exit_reason,'take_profit')
        self.assertEqual(sum(row.qty for row in positions.list_positions()),6)
        self.assertEqual(collected['budget']['available_cash'],472)

    def test_daemon_refuses_missing_budget_before_acquiring_a_lease(self):
        from rshelper import trader
        from rshelper.config import TraderConfig
        with mock.patch.object(trader,'acquire_lease',side_effect=AssertionError('lease acquired')):
            with self.assertRaisesRegex(ValueError,'budget initialization'):
                trader.run_trader(TraderConfig(),once=True)

if __name__=='__main__':unittest.main()
