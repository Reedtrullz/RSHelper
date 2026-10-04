# Scheduled state synchronizer (#9)

The synchronizer builds a state-only commit with a temporary index, pushes its
private pending ref to `origin/main`, and records the last successful revision.
It does not move checkout HEAD, change the user's real index, copy over checkout
files, or sweep staged source changes into a state commit. The temporary index
is removed on every exit; the repository-wide lease inode is retained.

Required SSH/GPG signing is the default, enforced by `commit-tree -S`. Signing
failure returns an error before a pending commit or push exists. `--unsigned`
is an explicit operator option; it is never selected by a failure handler. A
pending unsigned revision also requires that explicit option when retried.

`--dry-run` reports selected paths and whether canonical bytes differ without
writing Git objects, refs, index, source or destination files. `--status` reports
checkout HEAD, pending and last-pushed revisions without trading record values.
A failed push retains the intended revision, and a no-change run retries it
without creating another commit. No push uses force. Source/ref divergence or a
changed HEAD stops the operation; it does not rebase or reset source WIP.
If the remote accepted a push before the local receipt could be recorded, retry
checks the fetched remote ancestry and acknowledges the same accepted revision.
A later remote release is preserved. HEAD is rechecked before each push; a
detected source change retains the pending ref for deliberate reconciliation.

Only the existing default-profile JSON allowlist and recognized snapshot names
are selected. E08's public/private classes and known trade/position fields are
consulted; new state files, snapshot classes and trade/position fields are not
published by accident. This compatibility bridge does not approve the existing
private feed as a public demo. E08-B's owner choice and authenticated private
transport cutover remain separate. Existing Git copies are retained.

Validate this code in disposable repositories first. The implementation round
does not invoke or restage the installed synchronizer. When a reviewed release
is staged by the operator, its configured repository must contain the matching
shared validation/publication modules. Keep the installed service's required
signing policy. Unlock the signer or reconcile source readiness when needed;
do not use unsigned mode as an unattended resilience fallback.

A state-only private ref can be inspected with normal Git commands. Do not reset
or update the user's checkout merely to align its HEAD with that ref; reconcile
source and state intentionally. The emitted revision is the synchronization
receipt; checkout HEAD alone no longer certifies the latest state push. Exact
remote/application receipt reconciliation is completed by #33.
