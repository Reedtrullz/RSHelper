# Provider deadlines, private readiness and profile transfer

Authorized implementation: Issues #73, #33 and #28, followed by GitHub CI,
deployment and exact release/readiness verification. Base: 8d4bc635.

1. Bound one provider attempt/retry sequence and the Wiki/Tracker acquisition
   chain using monotonic deadlines, including shared locks, pacing and reads.
   Prove slow stream, blocked headers, retry and fallback behavior offline.
2. Add authenticated readiness with bounded source, cycle and sync summaries.
   Keep public health lightweight. Prove degraded/live separation and privacy.
3. Reuse validated private backup/restore and identity merges for JSON/CSV
   exports, read-only import previews and explicit apply with a prior backup.
   Prove round trips and refusal of malformed, duplicate or mixed identities.
4. Run the complete offline runner, browser checks, CLI smoke checks and diff
   review. Publish one focused PR, verify its exact CI head, merge and verify
   the deployed SHA and private readiness. Update the clean Mac runtime.

The owner overrode the 30 GiB storage gate on 12 October 2026. Scratch remains
bounded; private financial state, original backups and primary WIP are preserved.

## Provider budget

One provider sequence (including retries) has 30 seconds. The complete fresh-cache,
Wiki, Tracker, stale-cache acquisition chain has 60 seconds. Pacing, lock waits,
Retry-After, response reads and decoding share the monotonic remaining budget.
Neither expiration nor fallback resets the shared provider cooldown. A timed-out
response is shut down and closed by its worker; discarded workers cannot publish
cache. OS DNS/header calls cannot reliably be cancelled by urllib; callers return
at the deadline and four bounded daemon slots contain residual work. Exhausted
slots refuse new network work, allowing the normal cache fallback to proceed.

## Private readiness

`rshelper --profile NAME readiness --json` reads status without provider traffic.
Authenticated `/api/readiness` observes the dashboard's current cache without
starting a refresh. Public `/api/health` remains liveness and baked image identity.
Stale/unknown sources or source success older than 360 seconds, an authority trader success older than 600
seconds, or sync success older than 1800 seconds degrades readiness. A replica has
no local trader requirement. A failed cycle does not advance its success time.
Sync reports applied, no_op, obsolete, conflict or failed separately, with attempt
and success times and the acknowledged revision/hash. Successful sync status must
match a durable incoming receipt or the current outgoing cursor; mismatches degrade
readiness and are covered by CI. It never emits rows or raw
exception strings. These are explicit operator thresholds; status reads do not
emit repeated alerts. Existing CI receipt tests certify exact requested revisions;
the readiness tests additionally prove healthy liveness alongside degraded source
readiness, private authorization and no-op/failure separation.

## Profile transfer

`profile export DEST --format json|csv --json` creates a private 0600 export,
including its sensitivity-labelled manifest. CSV has `file,content` rows, including
the manifest; each content field preserves its complete validated JSON or TOML
file. It is a lossless profile transfer format, not a financial spreadsheet.

`profile import --input SOURCE --format json|csv|zip --expected-profile-uuid UUID
--json` validates in disposable staging and previews file changes without creating
the target or initializing its config. Add `--apply --operation-id UUID --backup
NEW_PRIVATE_ZIP` for explicit recoverable publication. Legacy imports also require
their inspected `--expected-source-revision`. Apply repeats validation under the
profile transaction and captures the pre-apply state before staging any changes.

Stable IDs already present in the target remain single records; duplicate rows in
an input are refused. Financial conflicts, undeclared origins, wrong profiles,
path traversal and rolled-back receipts are refused. Import uses coherent complete
exports and refuses a source that would discard acknowledged records or proofs.
An inactive empty target gets an empty private pre-apply backup. No remote import
endpoint or automatic publication is introduced. Keep all real exports out of Git.
