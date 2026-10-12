# Observed offers

The owner dashboard has a separate Observed offers view for manual game receipts.
Plan the original order, record placement, cumulative partial fills and actual GP,
cancel any unfilled remainder, then record collection. Buy receipts record GP spent;
sell receipts record gross GP and actual fees. UTC time and an evidence description
are mandatory. A correction names the latest receipt and appends another receipt
in the same phase. The original item, side, quantity and limit price cannot change.

Paper estimates never become observed receipts. Observed cash flow is not profit.
Complete game cash, inventory, purchase windows and cost matching remain unknown.
Reservations and slots are reported separately from the paper budget; users must
not sum both lanes as one game account. Canceled offers keep a slot until collection.

CLI commands are `observed list`, `observed history OFFER_UUID`, and
`observed record OFFER_UUID --input event.json --expected-revision N --operation-id UUID`.
All accept `--json`. A repeated identical operation is acknowledged once; changing
its payload or using a stale revision is refused. The dashboard retains the same
operation identifier when retrying an unchanged draft.

CSV headers are `offer_uuid,operation_id,expected_revision` followed by the sorted
event fields from `observed_offers.CSV_FIELDS`. Receipts must declare `source=csv`.
Use `observed preview-csv --input file.csv --json` first. It reports unknown mapped
items and the first conflicting row without applying any rows. Then use
`observed apply-csv --input file.csv --expected-import-hash HASH --backup NEW.zip`.
The exact preview hash and a new validated private backup are required before the
atomic append. Imports are limited to 200 rows and 64 KiB; histories to 10,000 receipts.

The Mac remains the only financial writer. Private replication and full private
backups include the immutable ledger; VPS writes and public export are refused.
A missing acknowledged ledger, conflicting authority or history rewind fails closed.
Host-supplied deployment checks require ledger support in running, candidate and
rollback images. An older image can be used before any observed receipts exist;
afterward a rollback requires an image that understands and validates this ledger.
Deleting ledger data to make an older image pass is not a recovery procedure.

## Review and validation

Scoped Sonnet review `20261012T172713Z-67d5bb27` covered all 20 selected files
in one call, with no retries or fallback. Every claim was checked locally:

- Script exit propagation is correct: production invokes `python /state-contract.py`,
  whose main guard passes the CLI result to `sys.exit`; CLI errors exit nonzero.
- A retained backup after interrupted import is the intended pre-apply recovery
  artifact. Recovery and retry preserve it and acknowledge the append exactly once.
- Zero-fill collection releases returned GP/items from an unfilled canceled offer.
  A canceled plan that was never placed consumes no slot; a placed canceled offer
  keeps its slot until collection. Both paths have regression coverage.
- Observed HTTP reads acquire no outer profile lock; existing transactions are
  reentrant. Both summary branches share the same schema, with slot capacity from
  the explicitly initialized paper account when present.
- Negative history offsets are now rejected before slicing; no result was printed
  on the original error path either.
- Pre-apply backups correctly omit a ledger that did not yet exist; separate
  post-observation backup/private-transfer tests prove inclusion afterward.
- `previous_image_id` is set before rollout; the existing rescue guard refuses a
  missing previous image before the new rollback contract task.
- Disabled selects retain their DOM value and the request reads it directly.
  UTC canonical serialization is explicit; the actual browser-generated timestamp
  mismatch was corrected before review and has a regression test.

The synthetic native-browser trial completed planned → placed → partial →
correction → canceled → collected, verified reservations/cash flow/slot release,
and kept the 320px input form within its panel. A real manual owner/game trial
has not been performed. No actual game account data was inferred or modified.
