# Coordinated state cutover remaining after PRs 68–70

The identity readers/legacy writer guard, recoverable exact-lot realization and pure identity merge prerequisites are released separately. No live identity writer, manifest, intent or tombstone has been activated. Issues 8, 10 and 11 remain open.

## Source-grounded remaining write/staging inventory

| Path | Current boundary | Required coordinated change/proof |
| --- | --- | --- |
| `src/rshelper/positions.py` | Legacy opens/FIFO closes; identified rows refuse old writers | Explicit identified opens; exact UUID close selection; retained full-close tombstone; filter tombstones in all readers |
| `src/rshelper/journal.py` | Legacy logs/removal; identified writer guard | Native creation lineage; mutable revision/deletion tombstones; retain immutable financial evidence for operation recovery |
| `src/rshelper/alerts.py` | Legacy append/read/prune; identified writer guard | Read revisions, deletion/pruning tombstones; offline-peer horizon before any purge |
| `src/rshelper/watchlist.py` | Dictionary keyed by item ID; physical remove; replacement drops extension identity | Explicit watch lineage/creation generation, revisioned threshold edits, retained deletes and re-add semantics; guard old writers before activation |
| `src/rshelper/state_identity.py` | Pure explicit legacy mapping; own-origin mapping attestation | Durable profile manifest publication; attestation of newly created operation records without reassigning UUIDs |
| `src/rshelper/realization.py` | Inactive intent/receipt core; exact pinned row IDs/timestamps; full close currently removes row | Coordinate canonical timestamps/display aliases and tombstones; audit deleted journal financial evidence; startup recovery before writers |
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
