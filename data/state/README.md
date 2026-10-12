# RSHelper synthetic public demo

These two JSON files contain invented examples approved on 12 October 2026.
They contain no live trading records and cannot seed an operational profile.

- `trades.json`: item_id, qty, buy_price, sell_price, tax_paid, profit.
- `positions.json`: item_id, qty, buy_price, direction.

The [approved policy](../../docs/execution/public-demo-policy.json) selects only
the synthetic-demo profile and these fields. The application serializer produced
the exact reviewed preview. Names, notes, account labels, timestamps, watches,
alerts, operational state and identity/receipt proof stay outside this dataset.

Real state remains private: the Mac is financial authority and the VPS is a
replica reached through authenticated SSH packets and exact applied receipts.
The legacy State Sync workflow is retired. Identified profiles reject raw Git
publication and skip public seed files. Recover a new deployment from an
inspected private app backup, never from these examples.

Existing public Git history is retained. Replacing this working-tree dataset
does not remove previously published versions. See the
[coordinated state runbook](../../docs/execution/coordinated-state-runbook.md).
