"""Tests for the replay harness (scripts/replay.py)."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import replay

def test_runtime_config_and_injected_decisions():
    from dataclasses import asdict
    from unittest import mock
    from rshelper import trader
    from rshelper.config import TraderConfig
    from rshelper.positions import Position
    cfg=TraderConfig(stop_mark_blend=0.5,reentry_minutes=45)
    assert asdict(replay.ReplayConfig.from_trader_config(cfg))==asdict(cfg)
    now=1700000000
    lot=Position(1,1,'Synthetic',10,100,'traditional',replay._candle_iso(now-1800))
    quote={'1':{'high':105,'low':100,'highTime':now,'lowTime':now}}
    with mock.patch.object(trader.time,'time',side_effect=AssertionError('wall clock used')):
        assert trader.exit_reason(lot,quote,cfg,now=now,avg_low=100)=='take_profit'
    from rshelper.models import Item
    candidate=Item(1,'Synthetic',False,10000,0,100,96,10000)
    volume={'1':{'avgLowPrice':100,'lowPriceVolume':5000,'highPriceVolume':5000}}
    quote={'1':{'high':100,'low':96,'highTime':now,'lowTime':now}}
    with mock.patch.dict(trader._RECENT_EXITS,{1:(now,'stop_loss')},clear=True):
        assert trader.select_candidates([candidate],quote,volume,cfg,now=now,recent_exits={})==[candidate]
        assert trader.select_candidates([candidate],quote,volume,cfg,now=now,recent_exits={1:(now,'stop_loss')})==[]


def _ts_item(item_id: int, n: int = 30, hi: int = 104, lo: int = 100,
             base_ts: int = 1_699_999_800) -> list[dict]:
    """A synthetic candle series: a dip (low drops ~5%) then recovery, so
    the dip+spread filters see a mean-reverting opportunity. The dip keeps
    the spread within [4%, 5%] so it passes max_entry_spread_pct."""
    out = []
    for i in range(n):
        # First 10 candles at normal price; candles 10-14 dip 5% (the low
        # falls below the trailing average); then recover.
        if 10 <= i < 15:
            c_lo = int(lo * 0.95)   # e.g. 100 -> 95
            c_hi = int(hi * 0.955)  # keep spread ~4.2% (99/95)
        else:
            c_lo, c_hi = lo, hi
        out.append({
            "timestamp": base_ts + i * 300,
            "avgHighPrice": c_hi,
            "avgLowPrice": c_lo,
            "highPriceVolume": 5000,
            "lowPriceVolume": 5000,
        })
    return out


def _run(data,cfg):
    from dataclasses import replace
    return replay.simulate(data,replace(cfg,capital=10000),
        metadata={str(iid):{'name':'Synthetic','members':False,'limit':10000} for iid in data},slot_limit=8)


def test_aligned_runtime_replay_budgets_fills_and_collections():
    from dataclasses import asdict
    from rshelper.config import TraderConfig
    from unittest import mock
    from rshelper import profile,state_identity,trader,paper_book,cli,journal
    cfg=replay.ReplayConfig(capital=10000,dip_depth_pct=3.0)
    data={1:_ts_item(1,n=35),2:_ts_item(2,n=35)}
    metadata={str(iid):{'name':'Synthetic '+str(iid),'members':False,'limit':60} for iid in data}
    observations=list(replay.candle_observations(data,metadata))
    simulated=replay.simulate(data,cfg,metadata=metadata,slot_limit=8,observations=observations)
    expected={row['at']:row for row in simulated['trace'] if row['kind']=='budget'}
    with tempfile.TemporaryDirectory() as folder,mock.patch.object(profile,'CONFIG_DIR',Path(folder)), \
            mock.patch.dict(trader._RECENT_EXITS,{},clear=True):
        selected='aligned';root=profile.resolve_config_path('',selected);root.mkdir(parents=True)
        origin='11111111-1111-4111-8111-111111111111';identity='22222222-2222-4222-8222-222222222222'
        for filename,value in {'identity-manifest.json':state_identity.new_manifest(origin),
                'identity-activation.json':{'schema_version':1,'mode':'identified','origin_uuid':origin,
                    'profile_uuid':identity,'financial_authority':True,'replication_origins':[origin]}}.items():
            (root/filename).write_text(replay.json.dumps(value))
        paper_book.initialize_budget(selected,bankroll=cfg.capital,slot_limit=8,
            operation_id='33333333-3333-4333-8333-333333333333',now=observations[0]['now']-14400)
        collected=[]
        for snapshot in observations:
            with mock.patch.object(trader.time,'time',return_value=snapshot['now']), \
                    mock.patch.object(cli,'_fetch_bootstrap',return_value=(metadata,snapshot['latest'],snapshot['5m'],snapshot['items'])):
                actual=trader._run_paper_cycle(TraderConfig(**asdict(cfg)),selected)
            expected_budget={key:value for key,value in expected[snapshot['now']].items() if key not in ('kind','at')}
            assert actual['budget']==expected_budget,(snapshot['now'],actual['budget'],expected_budget)
            collected.extend(actual['closed'])
        economic=lambda rows:[{key:row[key] for key in ('item_id','qty','profit','reason')} for row in rows]
        assert economic(collected)==economic(simulated['trade_list'])
        assert simulated['trades']>0 and len(journal.list_trades(profile=selected))==simulated['trades']
        book=paper_book.budget_snapshot(selected,now=observations[-1]['now'])
        actual_fills=[{key:fill[key] for key in ('side','qty','price','tax_paid')} for record in book['offers'].values() for fill in record['fills']]
        modeled=[{key:row[key] for key in ('side','qty','price','tax_paid')} for row in simulated['trace'] if row['kind']=='fill']
        assert sorted(actual_fills,key=replay.json.dumps)==sorted(modeled,key=replay.json.dumps)


def test_replay_never_uses_owner_files_or_wall_clock():
    from unittest import mock
    data={1:_ts_item(1,n=35)}
    cfg=replay.ReplayConfig(capital=10000)
    with mock.patch.object(Path,'read_text',side_effect=AssertionError('profile read')), \
            mock.patch.object(Path,'read_bytes',side_effect=AssertionError('profile read')), \
            mock.patch.object(Path,'write_text',side_effect=AssertionError('profile write')), \
            mock.patch.object(Path,'write_bytes',side_effect=AssertionError('profile write')), \
            mock.patch.object(Path,'open',side_effect=AssertionError('profile open')), \
            mock.patch.object(replay.trader.time,'time',side_effect=AssertionError('wall clock')):
        result=_run(data,cfg)
    assert result['trades']>0
    assert replay.simulate(data,cfg)['trades']==0
    assert 'account slot capacity unknown' in replay.simulate(data,cfg)['budget']['unknown']


def test_stable_ties_and_explicit_legacy_config():
    from dataclasses import asdict
    from rshelper.config import TraderConfig
    from rshelper.models import Item
    cfg=replay.ReplayConfig()
    assert asdict(cfg)==asdict(TraderConfig())
    old=replay.ReplayConfig.historical_baseline()
    assert (old.dip_depth_pct,old.stop_loss_pct,old.stop_grace_minutes)==(2.0,-1.5,10)
    now=1700000100
    items=[Item(iid,'Synthetic',False,10000,0,100,96,10000) for iid in (2,1)]
    quote={str(item.id):{'high':100,'low':96,'highTime':now,'lowTime':now} for item in items}
    volume={str(item.id):{'avgLowPrice':100,'lowPriceVolume':5000,'highPriceVolume':5000} for item in items}
    assert [item.id for item in replay.trader.select_candidates(items,quote,volume,cfg,now=now,recent_exits={})]==[1,2]


def test_shared_stop_blend_grace_and_thin_print_prices():
    from dataclasses import replace
    from rshelper.positions import Position
    from rshelper.market_data import MarketDataResult,market_payload
    now=1700000100
    cfg=replay.ReplayConfig(stop_mark_blend=0.5)
    lot=Position(1,1,'Synthetic',10,100,'traditional',replay._candle_iso(now-1800))
    quote={'1':{'high':101,'low':99,'highTime':now,'lowTime':now}}
    assert replay.trader.exit_reason(lot,quote,cfg,now=now,avg_low=105)=='stop_loss'
    assert replay.trader.exit_reason(lot,quote,replace(cfg,stop_mark_blend=0.0),now=now,avg_low=105) is None
    young=replace(lot,opened_at=replay._candle_iso(now-600))
    assert replay.trader.exit_reason(young,quote,cfg,now=now,avg_low=105) is None
    quote['1']['low']=80
    thin={'1':{'avgLowPrice':100,'lowPriceVolume':1,'highPriceVolume':10000}}
    volume=market_payload(MarketDataResult(thin,'wiki','historical-model',now,now,now,False,'executed-trades',{'wiki':1}))
    assert replay.trader.paper_sale_price(lot,quote['1'],volume,cfg,'stop_loss')==100
    volume['1']['lowPriceVolume']=5000
    assert replay.trader.paper_sale_price(lot,quote['1'],volume,cfg,'stop_loss')==77
    item=replay.Item(1,'Synthetic',False,10000,0,100,96,10000)
    entry_quote={'1':{'high':100,'low':96,'highTime':now,'lowTime':now}}
    volume['1']['lowPriceVolume']=1
    assert replay.trader.select_candidates([item],entry_quote,volume,cfg,now=now,recent_exits={})==[]


def test_replay_cli_and_sweep_require_explicit_inputs_and_emit_strict_json():
    import contextlib,io,sweep
    from unittest import mock
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);data=root/'candles.json';mapping=root/'mapping.json';config=root/'config.toml'
        data.write_text(replay.json.dumps({'1':_ts_item(1,n=35)}))
        mapping.write_text(replay.json.dumps({'1':{'name':'Synthetic','members':False,'limit':10000}}))
        config.write_text('[trader]\ncapital=10000\n')
        out=io.StringIO();errors=io.StringIO()
        args=['--data',str(data),'--mapping',str(mapping),'--config','runtime-defaults','--config-file',str(config),'--slots','8','--json']
        with mock.patch.object(sys,'argv',['replay',*args]),contextlib.redirect_stdout(out),contextlib.redirect_stderr(errors):
            assert replay.main()==0
        result=replay.json.loads(out.getvalue());assert result['trades']>0 and not errors.getvalue()
        out=io.StringIO();errors=io.StringIO()
        with mock.patch.object(sys,'argv',['sweep',*args,'--top','1']),contextlib.redirect_stdout(out),contextlib.redirect_stderr(errors):
            assert sweep.main()==0
        ranked=replay.json.loads(out.getvalue());assert len(ranked)==1 and isinstance(ranked[0]['cfg'],dict)
        with mock.patch.object(sys,'argv',['replay']),contextlib.redirect_stderr(io.StringIO()):
            try:replay.main()
            except SystemExit as exc:assert exc.code==2
            else:raise AssertionError('implicit replay inputs accepted')


def test_corrupt_input_and_sweep_failure_are_clear():
    import contextlib,io,sweep
    from unittest import mock
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);data=root/'data.json';mapping=root/'mapping.json'
        data.write_text(replay.json.dumps({' 1':_ts_item(1)}))
        try:replay.load_data(data)
        except ValueError:pass
        else:raise AssertionError('noncanonical item ID accepted')
        data.write_text('{"1":[],"1":[]}')
        try:replay.load_data(data)
        except ValueError:pass
        else:raise AssertionError('duplicate item ID accepted')
        mapping.write_text(replay.json.dumps({'1':{'name':'Synthetic','members':False,'limit':10000}}))
        rows=_ts_item(1);rows[1]['timestamp']+=60
        data.write_text(replay.json.dumps({'1':rows}))
        out=io.StringIO();err=io.StringIO()
        with mock.patch.object(sys,'argv',['sweep','--data',str(data),'--mapping',str(mapping),
                '--config','runtime-defaults','--slots','8','--json']),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            assert sweep.main()==1
        assert not out.getvalue() and 'five-minute' in err.getvalue()


def test_cancel_stages_and_unknown_free_membership_remain_safe():
    from rshelper.ge_offers import new_paper_offer,cancel_paper_buy
    from rshelper.budget import require_capacity
    order=new_paper_offer(1,10,100,'traditional',1700000100)
    assert cancel_paper_buy(order,1700000400)['stage']=='canceled'
    assert order['stage']=='buying'
    order['bought_qty']=2
    canceled=cancel_paper_buy(order,1700000400)
    assert (canceled['stage'],canceled['bought_qty'],canceled['canceled_buy_qty'])==('bought',2,8)
    budget={'slot_limit':3,'available_slots':3,'unknown':[],'available_cash':1000,
            'purchase_windows':{'1':{'available_qty':10}}}
    for members in (None,True):
        try:require_capacity(budget,item_id=1,qty=1,buy_price=100,members=members)
        except ValueError:pass
        else:raise AssertionError('unknown/member item admitted to free account')


def test_replay_baseline_generates_trades():
    """A dip+spread item should generate profitable trades under the
    validated defaults."""
    data = {1: _ts_item(1, n=60, hi=104, lo=100)}  # 4% spread, 4% dip vs 1h avg
    cfg = replay.ReplayConfig(dip_depth_pct=3.0, stop_loss_pct=-2.0,
                              stop_grace_minutes=20, min_spread_pct=4.0)
    r = _run(data, cfg)
    assert r["trades"] > 0, f"expected trades, got {r}"
    assert r["roi_pct"] > 0
    assert r["win_rate"] == 100.0
    print("  PASSED test_replay_baseline_generates_trades")


def test_replay_no_trades_without_dip():
    """An item that never dips below the entry filter produces no trades."""
    data = {1: _ts_item(1, n=30, hi=100, lo=99)}  # 1% spread < 4% filter
    cfg = replay.ReplayConfig(min_spread_pct=4.0)
    r = _run(data, cfg)
    assert r.get("trades", 0) == 0
    print("  PASSED test_replay_no_trades_without_dip")


def test_replay_grace_blocks_early_stop():
    """A short crash inside the grace period survives until recovery."""
    candles = []
    base = 1_699_999_800
    for i in range(40):
        if 10 <= i < 14:
            c_lo, c_hi = 96, 100
        elif 14 <= i < 16:
            c_lo, c_hi = 88, 91  # crash mid-dip, within the grace window
        else:
            c_lo, c_hi = 100, 104
        candles.append({"timestamp": base + i * 300, "avgHighPrice": c_hi,
                        "avgLowPrice": c_lo, "highPriceVolume": 100000,
                        "lowPriceVolume": 100000})
    data = {1: candles}
    cfg = replay.ReplayConfig(dip_depth_pct=3.0, stop_loss_pct=-2.0,
                              stop_grace_minutes=20, min_spread_pct=4.0,
                              min_volume=100)
    r = _run(data, cfg)
    reasons = [t["reason"] for t in r.get("trade_list", [])]
    assert "stop_loss" not in reasons, \
        f"grace must block the early stop, got {reasons}"
    assert any(t["profit"] > 0 for t in r.get("trade_list", [])), r
    print("  PASSED test_replay_grace_blocks_early_stop")


def test_replay_staged_sale_collects():
    """A timed sale collects only after the supported sell stage fills."""
    candles = []
    base = 1_699_999_800
    for i in range(30):
        if 10 <= i < 15:
            c_lo, c_hi = 96, 100
        else:
            c_lo, c_hi = 100, 104
        candles.append({"timestamp": base + i * 300, "avgHighPrice": c_hi,
                        "avgLowPrice": c_lo, "highPriceVolume": 100000,
                        "lowPriceVolume": 100000})
    data = {1: candles}
    cfg = replay.ReplayConfig(dip_depth_pct=3.0, stop_loss_pct=-2.0,
                              stop_grace_minutes=20, min_spread_pct=4.0,take_profit_pct=10.0)
    r = _run(data, cfg)
    reasons = [t["reason"] for t in r.get("trade_list", [])]
    assert "spread_collapse" in reasons, f"expected timed staged sale, got {reasons}"
    stages=[row['kind'] for row in r['trace']]
    assert stages.index('queued')<stages.index('bought')<stages.index('sale')<stages.index('collected')
    assert all(trade['tax_paid']==replay.ge_tax(trade['sell'])*trade['qty'] for trade in r['trade_list'])
    print("  PASSED test_replay_staged_sale_collects")


if __name__ == "__main__":
    test_runtime_config_and_injected_decisions()
    test_replay_baseline_generates_trades()
    test_replay_no_trades_without_dip()
    test_replay_grace_blocks_early_stop()
    test_replay_staged_sale_collects()
    print("\nAll replay tests passed.")
