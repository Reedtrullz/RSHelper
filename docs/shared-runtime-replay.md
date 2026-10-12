# Shared runtime and replay decisions

Replay now calls the runtime entry ranking, sizing, exit/grace/blend, thin-print
sale-price and reentry decisions. It uses the same conservative staged offer
progression, cancellation, sale staging, per-unit GE tax and shared budget
admission. The small extracted helpers are also used by the runtime. Production
configuration and participation policy retain their values.

`ReplayConfig.from_trader_config` copies and validates every effective trader
field. The default config matches `TraderConfig` exactly. Select the historical
2% dip/-1.5% stop/10-minute grace/25% allocation parameters explicitly; this
selection still uses current staged fills, so old immediate-fill results are
not reproduced or presented as current acceptance. Trailing/reversal knobs
without runtime counterparts were removed from the shared decision model.

```
.venv/bin/python scripts/replay.py --data candles.json --mapping mapping.json \
  --config runtime-defaults --config-file explicit-config.toml --slots 8 --json
.venv/bin/python scripts/sweep.py --data candles.json --mapping mapping.json \
  --config runtime-defaults --slots 8 --top 3 --json
```

The mapping is keyed by canonical item IDs, with public `name`, `members` and
`limit` metadata. Missing limits prevent a purchase; free accounts require known
free items. Account slots must be explicitly selected. A sweep changes only
simulated configs and never adopts a result. Both commands require explicit
data; neither defaults to owner journal, profile or temporary-file data.

Intentional tested candle/poll differences:

- Candle observations occur after completion, every300 seconds. Their quote
  proxy is that completed candle's average, not an observed latest tick.
- The volume/dip reference is the previous contiguous completed candle. This
  lag avoids using a candle's quote proxy as its own dip baseline. Its real
  window timestamp is preserved; a gap provides no invented volume or fill.
- Runtime polling may observe additional ticks and volume windows. For an
  explicitly aligned observation stream both paths consume identical inputs.
- Simulations start with empty holdings/purchase history and declared cash and
  slots. They do not infer the owner's inventory, history or buy-limit groups.
- End-of-data offers remain open. Realized turnover ROI and drawdown explicitly
  exclude uncollected offers and open marked losses; neither is total equity
  return or a forecast. Trace output is bounded with total/truncation counts.

The owned aligned runtime fixture compares every budget, actual fill quantities,
tax and collection against replay, including a competing item refused by the
conservative shared four-hour pool. Separate fixtures exercise stable ranking
ties, explicit cooldowns, grace/blend, thin prints, no wall-clock or profile I/O,
configuration selection, staged sales and strict CLI/sweep JSON. Normalization
uses an injected dataset horizon; historical exits use the supplied clock.

Held-out experiment design and independent market coverage remain #20. A green
fixture or synthetic profitable trace is not empirical strategy validation.

Scoped Sonnet review20261012T142834Z-cb5b432d completed once, without retry or
fallback:27.919 seconds,21443 input/1043 output tokens, eight selected diffs.
The replay diff contained the complete rewrite; existing large callers were
reviewed as selected diffs. Native triage checked every finding:

- Cancellation requires `buying`, then exposes a bought partial lot or cancels
  an empty order. Same-cycle evaluation of a bought lot matches the runtime;
  zero-fill cancellation never enters the bought branch. Both stages are tested.
- The sale-price helper extracts the same candle from the same volume object.
  Offer advancement copies the offer, and Book advancement freezes market data;
  neither mutates the original volume lookup. The actual aligned trace passes.
- Malformed sweep data could escape the input handler: fixed with one command
  boundary and a failing-then-passing irregular-candle fixture. No invalid run
  is skipped or ranked as successful.
- Canonical data IDs and duplicate fields now fail clearly through the existing
  bounded JSON decoder; alias/duplicate fixtures preserve all input bytes.
- Free admission already uses `members is not False`; both unknown and member
  items are refused. Existing Book and added shared-capacity tests prove this.
- Python3.11 is the documented minimum and production image runtime; `tomllib`
  is intentional. No unsupported Python3.10 fallback was added.

Native review also centralized collection profit through the same pure helper
for Book/runtime/replay; executed tax remains `market.ge_tax`. Final tests cover
this follow-up. The fresh owned live smoke acquired365 contiguous five-minute
candles each for items2/4151 from Wiki network and exercised strict CLI JSON
without creating an owner configuration. Its three modeled collections are
smoke evidence, not a held-out profitability result.
