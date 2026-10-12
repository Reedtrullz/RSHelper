# Private trade hypotheses and reviews

Reviews are private annotations attached to an existing stable lot UUID. Partial realized children retain that parent UUID and share its current annotation. Legacy journal rows without an established parent remain unknown. Exact journal note filters and the manual/auto compatibility filter remain available; queue responses disclose these filters, matching child/lot counts, reviewed counts and missing hypotheses. Returned queues contain at most 200 children (50 by default), open-lot choices at most 20, and detail histories at most 50 receipts with the full count disclosed.

The `reviews queue`, `reviews append` and `reviews history` commands and the owner Reviews screen use the same store and validation. Append requires a canonical operation UUID and the expected global review revision. An exact retry returns the existing receipt; a conflicting operation or stale revision is rejected. Corrections append a complete annotation, and removal appends a tombstone. Past receipts are retained. Financial quantities, prices, taxes, basis and realized profit are not annotation fields and cannot be modified by the writer.

`trade-reviews.json` has schema version 1 and a single financial authority. Hypothesis, planned exit and review each accept at most 8,192 UTF-8 bytes; at most 20 unique single-line tags accept 64 bytes each. Storage is limited by 100,000 receipts and the existing 64 MiB file/transaction budget, whichever is reached first. Hitting the limit refuses further publication; receipts and tombstones are not pruned automatically.

The Mac financial authority writes annotations. Authenticated replicas read the authority's private informational snapshot and reject writes. Publication, import and restore preserve existing receipt prefixes and tombstones; backups also validate the annotation authority against profile activation. Recovery uses the existing profile transaction. Older readers preserve the file during the verified image readback; use the current application for backup/export/restore. Older financial writers remain quiesced during rollback.

Private JSON/CSV profile exports include reviews by default. `profile export DESTINATION --without-reviews` excludes the root review store and review copies inside peer information, recomputes inventory hashes, and keeps the export labelled private. Such a filtered export cannot overwrite a profile that has acknowledged review history. Backup archives and private replication retain all receipts. Public/demo responses and shared URLs never include review free text; browser filters and writes use authenticated request bodies, and only a validated stable lot UUID appears in the private detail URL.

The editor keeps drafts and their original optimistic revision when queue filters refresh. It preserves the operation UUID after an ambiguous failed write and clears private state on disconnect. Notes describe the user's observations; the application does not infer adherence or predict returns.

## Review evidence

Scoped Sonnet review `20261012T131230Z-79527a78` completed one generation without retry or fallback (47.93 seconds, 6,767 input / 2,379 output tokens). It covered the complete new module and selected diffs for private transfer, replication, backup, transactions and HTTP validation. This is scoped review evidence, not a claim of whole-repository approval. Native review covers the callers, UI and tests.

- Note/strategy omission claim: callers applied the existing journal filters; the shared queue now selects through that same journal helper and reports every filter explicitly.
- Error-message spacing: corrected.
- Cross-module private validator naming: existing trust-boundary convention; the shared validator remains the single source, exercised by real HTTP malformed-body tests.
- Peer-information schema guard: confirmed gap at backup inspection; strict peer inventory validation and a failing regression now protect export and read boundaries.
- Manifest hash divergence claim: the rewritten revision uses the exact existing backup inventory hash formula; both JSON and CSV fixtures exercise import inspection.
- Missing tests in the review prompt: disclosed scope limit. Tests exercise partial children, immutable economics, retry, stale/replica denial, interrupted publication, strict fields, CLI/HTTP, tombstones and private exports.
- Mixed information record counts: both classes count durable records against the existing packet budget; no bypass was found.
- Independent `if` style: filenames are mutually exclusive, with no behavioral defect.

Native checks additionally caught replica restores discarding excluded reviews, wrong annotation authority in a backup, and queue refresh overwriting editor drafts. Each has a failing regression and a focused correction. Compatible Python 3.11 old/new/old/new image reads preserve lot identity, paper Book bytes, partial-sale profit and review-store bytes; backup/restore, transfer preview and export exclusion are exercised on owned disposable state. No owner hypotheses were fabricated.
