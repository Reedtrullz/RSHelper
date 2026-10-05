# Realization core prerequisite for issue 8

The inactive `realization.py` module is based on the verified identity-reader PR68. No CLI, dashboard, GE collect or trader close caller imports it. No live profile manifest or identity migration is installed. Issue 8 remains open.

## Contract and evidence

`close_and_realize(profile, lot_uid, qty, sell_price, operation_id, reason, *, metadata=None)` pins an exact identified lot, economic request, bounded metadata, deterministic journal UUID and receipt under ordered persistent locks. Reusing an operation requires identical normalized arguments. Private atomic writes fsync the file, rename through a held directory descriptor, then fsync that directory. Intents and receipts are retained, capped at 10,000 operations and the shared JSON byte budget; predictable financial schema/size/UUID conflicts refuse before intent publication.

Twenty-one scoped core tests and three process tests cover exception/reload recovery; actual killed subprocesses before and after all four durable writes; two-process same-operation and competing-operation races; exact mixed-direction cost basis and quantity conservation; shared per-unit tax; original quote/strategy/hold/fill metadata; file-before-directory fsync ordering; corrupted economics/types/receipts/manifests; strict nested JSON-type comparison and refusal of malformed existing empty intent files; cleanup errors with guaranteed directory-descriptor release; prior completed proof and revision-chain auditing; restored lot quantities, duplicate tombstones and unowned journal UUID refusal; request reuse and operation/byte bounds. These are synthetic disposable-state fixtures. Killed-process evidence does not certify filesystem power-loss recovery.

`recover_pending` validates retained completed journal/position proof before applying pending work. An operation marker cannot excuse restored units: the full applied revision chain must agree with the current remaining lot or its absence. Conflicts preserve financial bytes for review. Old receipts remain replayable after later partial and full closes.

The optional metadata whitelist pins note, strategy, hold minutes, raw quote, entry spread, fill guard and market provenance with a 16 KiB limit. It does not change price/fill decisions or trading defaults. Provenance is captured evidence, not independent verification of a provider claim.

## Remaining activation work

Convert all auto/manual/dashboard/collect close callers and startup recovery; coordinate identity-aware opens, durable manifest publication, dual-host readers/writers, tombstones and issue 10B merge handling with issue 11 profile transactions; test coordinated migration, rollback and live route behavior. Current full-close removal is an inactive core behavior, not the future tombstone rollout. Old writers remain fail-closed on identified state. No receipts or tombstones may be purged until an offline-peer/retention/rollback policy is tested. Parent issue 8 cannot close on this prerequisite alone.
