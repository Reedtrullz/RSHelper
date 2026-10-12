import sys
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_native_writers import DisposableHomeTest
from rshelper import tuning,bank,positions,paper_book,journal,snapshot,history
import json
from datetime import datetime,timezone,timedelta

class StrategyEquityTest(DisposableHomeTest):
    def test_native_configuration_proof_rejects_changed_valid_evidence(self):
        from rshelper import state_identity,persistence
        self.activate()
        created=positions.open_position(2,'Synthetic',2,100,operation_id=str(uuid4()))
        store=persistence.read_state(self.tmp/'config'/'positions.json','positions')
        altered=tuning.config_evidence(None,now=1791799200)
        store['positions'][0]['entry_config']=altered
        with self.assertRaisesRegex(ValueError,'immutable conflict'):
            state_identity.migrate_rows(store['positions'],'positions',
                persistence.read_state(self.tmp/'config'/'identity-manifest.json','generic'))
        self.assertEqual(positions.list_positions()[0].entry_config,created.entry_config)
        from rshelper import backup
        archive=self.tmp/'proof.zip'
        backup.export_profile(None,archive)
        _,files=backup._inspect(archive)
        self.assertEqual(json.loads(files['positions.json'])['positions'][0]['entry_config'],created.entry_config)
    def test_intraday_retention_and_unknown_equity_curve_preserve_receipts(self):
        self._swap(snapshot,'SNAPSHOT_DIR',self.tmp/'config'/'snapshots')
        receipt=self.tmp/'config'/'realizations.json'
        receipt.parent.mkdir(parents=True,exist_ok=True)
        receipt.write_text('{"owned-fixture":"immutable"}')
        instants=[datetime(2026,10,10,8,tzinfo=timezone.utc),
                  datetime(2026,10,10,9,tzinfo=timezone.utc),
                  datetime(2026,10,12,10,tzinfo=timezone.utc)]
        for index,instant in enumerate(instants):
            with mock.patch.object(snapshot,'datetime') as clock:
                clock.now.return_value=instant
                snapshot.save('equity',[],intraday=True,retention=2,
                    equity={'scope':'whole-profile','marked_equity':1000 if index==1 else None})
        files=list(snapshot.SNAPSHOT_DIR.glob('equity-*T*.json'))
        self.assertEqual(len(files),2)
        self.assertEqual(receipt.read_text(),'{"owned-fixture":"immutable"}')
        curve=history.build_history()['equity_curve']
        self.assertEqual(len(curve),2)
        self.assertEqual(curve[0]['marked_equity'],1000)
        self.assertIsNone(curve[1]['marked_equity'])
        self.assertTrue(curve[1]['gap_before'])
        self.assertTrue((snapshot.SNAPSHOT_DIR/'equity-2026-10-12.json').exists())
        with self.assertRaises(ValueError):snapshot.save('flip',[],intraday=True,retention=0)
        for intraday in (False,True):
            with self.assertRaises(ValueError):snapshot.save('../realizations',[],intraday=intraday)

    def test_history_exact_exit_context_and_unknown_entry_attribution(self):
        entries=[{'ts':'2026-10-12T08:00:00Z','params':{'v':1}},
                 {'ts':'2026-10-12T12:00:00+02:00','params':{'v':2}}]
        tuning.log_path().parent.mkdir(parents=True,exist_ok=True)
        tuning.log_path().write_text(json.dumps({'entries':list(reversed(entries))}))
        before=journal.Trade(1,2,'Synthetic',1,100,120,2,18,'2026-10-12T09:59:59Z')
        boundary=journal.Trade(2,2,'Synthetic',1,100,120,2,18,'2026-10-12T10:00:00Z')
        result=history.build_history(trades=[before,boundary])
        self.assertEqual([era['trade_count'] for era in result['eras']],[1,1])
        self.assertEqual(result['strategy_eras'][0]['attribution_basis'],'unknown-legacy-entry')
        self.assertEqual(result['strategy_eras'][0]['trade_count'],2)
        entries.append({'ts':'2026-10-12T10:00:00Z','params':{'v':3}})
        tuning.log_path().write_text(json.dumps({'entries':entries}))
        conflict=history.build_history(trades=[before,boundary])['eras'][1]
        self.assertEqual(conflict['attribution_basis'],'unknown-exit-context')
        self.assertIsNone(conflict['config_id'])
        self.assertIsNone(tuning.config_at_timestamp(boundary.timestamp,entries))

    def test_reserved_entry_and_partial_exit_keep_their_actual_configuration(self):
        from rshelper.config import TraderConfig
        from rshelper.market_data import MarketDataResult,market_payload
        self.activate()
        paper_book.initialize_budget(None,bankroll=1000,slot_limit=8,operation_id=str(uuid4()),now=19800)
        path=self.tmp/'config'/'config.toml'
        path.write_text('[trader]\ncapital=7000\n')
        reserved=paper_book.reserve_budget(None,item_id=2,name='Synthetic',qty=6,buy_price=100,
                    buy_limit=100,members=False,direction='traditional',note='auto',mode='auto',
                    expected_revision=1,operation_id=str(uuid4()),now=19800,trader_config=TraderConfig(capital=9000))
        entry=reserved['offers'][reserved['offer_id']]['entry_config']
        self.assertEqual(entry['params']['trader']['capital'],9000)
        def market(window):
            now=window+300
            def wrapped(data,kind):
                return market_payload(MarketDataResult(data,'wiki','network',now,now,now,False,kind,{'wiki':1}))
            return {'latest':wrapped({'2':{'high':120,'low':100,'highTime':now,'lowTime':now}},'unknown'),
                    '5m':wrapped({'2':{'avgHighPrice':120,'avgLowPrice':100,'highPriceVolume':1000,
                                      'lowPriceVolume':1000,'window_timestamp':window}},'executed-trades')}
        filled=paper_book.advance_offer(None,reserved['offer_id'],market(20100),expected_revision=2,
                                       operation_id=str(uuid4()),now=20400)
        self.assertEqual(positions.list_positions()[0].entry_config,entry)
        selling=paper_book.start_sale(None,reserved['offer_id'],qty=2,sell_price=120,
                    expected_revision=filled['revision'],operation_id=str(uuid4()),now=20400)
        path.write_text('[trader]\ncapital=5000\n')
        sold=paper_book.advance_offer(None,reserved['offer_id'],market(20700),expected_revision=selling['revision'],
                                    operation_id=str(uuid4()),now=21000)
        collected=paper_book.collect_offer(None,reserved['offer_id'],expected_revision=sold['revision'],
                                          operation_id=str(uuid4()),now=21000)
        trade=journal.list_trades()[0]
        self.assertEqual(trade.entry_config,entry)
        self.assertEqual(trade.exit_config['params']['trader']['capital'],7000)
        grouped=history.build_history(trades=[trade])['strategy_eras']
        self.assertEqual(grouped[0]['config_id'],entry['config_id'])
        self.assertEqual((trade.qty,trade.profit,positions.list_positions()[0].qty),(2,36,4))
        self.assertEqual(collected['budget']['available_cash'],636)
        marked=bank.build_bank_items(latest=market(20700)['latest'],now=21000)
        self.assertEqual(marked['equity']['marked_equity'],1108)
        self.assertEqual(marked['equity']['equity_return_pct'],10.8)
        unknown=bank.build_bank_items(latest={},now=21000)
        self.assertIsNone(unknown['equity']['marked_equity'])
        self.assertIsNone(unknown['equity']['equity_return_pct'])

    def test_exact_utc_config_boundaries_and_naive_unknown(self):
        entries=[{'ts':'2026-10-12T08:00:00Z','params':{'trader':{'capital':1000}}},
                 {'ts':'2026-10-12T12:00:00+02:00','params':{'trader':{'capital':2000}}}]
        self.assertIsNone(tuning.config_at_timestamp('2026-10-12T07:59:59Z',entries))
        self.assertEqual(tuning.config_at_timestamp('2026-10-12T09:59:59Z',entries),entries[0]['params'])
        self.assertEqual(tuning.config_at_timestamp('2026-10-12T10:00:00Z',entries),entries[1]['params'])
        self.assertIsNone(tuning.config_at_timestamp('2026-10-12T10:00:00',entries))
        self.assertEqual(tuning.config_at_timestamp('2026-10-12T10:00:00Z',list(reversed(entries))),entries[1]['params'])

    def test_configuration_evidence_hash_and_timestamp_are_checked(self):
        evidence=tuning.config_evidence(None,now=1791799200)
        self.assertEqual(tuning.validate_config_evidence(evidence),evidence)
        changed={**evidence,'params':{'trader':{'capital':1}}}
        with self.assertRaises(ValueError):tuning.validate_config_evidence(changed)
        with self.assertRaises(ValueError):
            tuning.validate_config_evidence({**evidence,'effective_at':'2026-10-12T10:00:00'})

    def test_missing_mark_is_unknown_and_open_loss_is_retained(self):
        positions.open_position(2,'Synthetic A',2,100,direction='traditional')
        positions.open_position(3,'Synthetic B',1,300,direction='arbitrage')
        price={'high':90,'low':80,'highTime':1000,'lowTime':1000}
        result=bank.build_bank_items(latest={'2':price},now=1000)
        self.assertIsNone(result['total_value'])
        self.assertIsNone(result['unrealized_pnl'])
        self.assertEqual(result['mark_coverage']['marked_cost_basis'],200)
        self.assertEqual(result['mark_coverage']['missing_cost_basis'],300)
        self.assertEqual(result['mark_coverage']['missing_item_ids'],[3])
        self.assertEqual(result['marked_unrealized_pnl'],-22)

if __name__=='__main__':unittest.main()
