# Coordinated state cutover remaining after PRs 68–70

The identity readers/legacy writer guard, recoverable exact-lot realization and pure identity merge prerequisites are released separately. No live identity writer, manifest, intent or tombstone has been activated. Issues 8, 10 and 11 remain open.

## Source-grounded remaining write/staging inventory

| Path | Current boundary | Required coordinated change/proof |
| --- | --- | --- |
| `src/rshelper/positions.py` | Legacy opens/FIFO closes; identified rows refuse old writers; readers filter retained tombstones | Explicit identified opens; exact UUID close caller selection |
| `src/rshelper/journal.py` | Legacy logs/removal; identified writer guard; readers/P&L filter retained tombstones | Native creation lineage; mutable revision/deletion writers; retain immutable financial evidence for operation recovery |
| `src/rshelper/alerts.py` | Legacy append/read/prune; identified writer guard; feed/count filter tombstones | Read revisions, deletion/pruning writers; offline-peer horizon before any purge |
| `src/rshelper/watchlist.py` | Legacy writers refuse identified active/deleted generations; validated dual readers | Durable native creation generation and revision/deletion writers; re-add must create a fresh generation even in the same clock tick |
| `src/rshelper/state_identity.py` | Pure explicit legacy mapping; own-origin mapping attestation | Durable profile manifest publication; attestation of newly created operation records without reassigning UUIDs |
| `src/rshelper/realization.py` | Inactive intent/receipt core retains full-close tombstones; UUID/economics proof accepts safe display aliases and canonical times, audits retained deleted trades | Startup recovery before writers; all close callers; durable manifest/native lineage; cross-origin receipt integration |
| `src/rshelper/trader.py`, `ge_offers.py`, `dashboard/server.py`, `cli.py` | Legacy close/log sequences still active | All closes route to shared UUID operation and stable retry receipt, preserving strategy/quotes/hold/fill metadata and current decisions |
| `deploy/merge_state.py` | Ordered shared locks, full preflight; per-file replacement; identified state refused | Identity-aware union plus conflict quarantine, validated revision manifest and no-op/obsolete/applied hash receipt; recoverable publication before receipt |
| `deploy/playbook.yml` and `deploy/playbook-state.yml` | Shared `state-stage` and `state-validation.py`; success-path cleanup | Run-owned private staging/helper paths; always clean only own staging; independent revision rejection and host merge lease |
| `.github/workflows/state-sync.yml` | SHA-derived `/tmp` names (same SHA reruns collide), no concurrency group; success-only cleanup | Run ID/attempt-owned staging, full deploy/state serialization, safe failure cleanup and receipt verification |
| `scripts/sync-state.sh` | Direct `cp` into tracked state without writer locks | Coherent locked capture, validated manifest, atomic destination writes and clean stdout contract |
| `scripts/sync-and-push-state.py` | Signed isolated Git refs/index; collection is not one locked financial snapshot | Coherent capture including manifests/intents/tombstones; preserve signing, pending refs and checkout WIP invariants |

## Required order and acceptance

1. Ship all read compatibility and explicit old-writer refusal, including watchlists and retained tombstones, before enabling new writes. Define which source owns each file and how conflicting concurrent revisions are reported; do not guess an origin from a path/host.
2. Implement profile-wide durable manifest/data publication and restart recovery under ordered locks, with run-owned staging and validated source revision/ancestry. Test out-of-order, same-revision retry, failed staging, actual killed subprocesses and concurrent local writer/sync against disposable volumes.
3. Connect every identified writer and close caller. Pin operational receipts to UUID/economics while allowing safe display alias normalization; deletion must not invalidate completed financial proof or recreate consumed units. Add actual caller-route and startup recovery tests, not only pure helper tests.
4. Exercise legacy import replay, independent ID collisions, mark/read/delete on both peers, re-add watch generations, partial/full lot closes and retained deletion evidence. Keep receipts/tombstones until supported offline-peer retention and rollback are tested.
5. Freeze/review/full offline and exact-index tests; live-source/JSON/caller UI checks where touched; dual-host migration rehearsal, backups and rollback; verify release identity and applied receipt. Cutover uses the app migration path and planned writer lease, preserving primary WIP and installed state until that concrete boundary is ready.

These prerequisites do not change strategy/tax/defaults, infer FIFO ownership, rewrite private publication/history, prune receipts or close parent issues. E08B publication remains a separate pending owner choice.

## Watch and financial deletion contract (implemented compatibility boundary)

An identified watch has `item_id`, `record_uuid`, `origin_uuid`, `revision` and `tombstone` in addition to legacy name/time/threshold fields. Live generations occupy the `items` dictionary keyed by item ID. Removed generations remain in `tombstones`, keyed by their UUID. The pure legacy migration explicitly binds item ID plus UTC creation instant to the supplied origin manifest; mutable names/thresholds reuse that binding. Re-adds require a new creation generation. Two distinct live generations for one item are reported as a conflict. Unknown watch root metadata must agree rather than being dropped.

A fully realized lot remains as a tombstone at the next revision, preserving its last open quantity as historical evidence. That quantity contributes zero open units; all current position readers filter the tombstone. Journal deletion similarly hides the trade from lists/P&L while retaining the exact financial record for operation proof. Alert feed/count readers hide retained deletions. Compatibility writers and the current deploy merger refuse identified state before mutation.

Realization receipts now return authoritative `trade_uuids` and the current numeric `trade_ids` aliases. The durable intent retains its original alias; safe peer alias/time normalization does not change economics or invalidate recovery. A pending journal append can allocate another numeric alias if a peer has used the original number, while retaining the same operation UUID. Deleted journal evidence must still preserve cost basis, tax, profit, lot linkage and metadata; it cannot excuse financial disagreement. No tombstone or receipt purge is enabled.
