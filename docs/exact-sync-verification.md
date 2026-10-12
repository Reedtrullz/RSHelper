# Unchanged private-state verification

An unchanged packet can have an exact replica receipt while the receiver's last successful sync timestamp ages. The private client now verifies that exact accepted cursor through authenticated SSH instead of sending the full packet again. The receiver accepts only the captured profile UUID, source origin UUID, revision and hash, and checks both requested and applied cursor equality under the profile lock. A mismatch changes no freshness or financial file.

`state verify` records a successful `no_op` interaction only after that equality check. It retains the original replication receipt and packet cursor. `readiness` already accepts successful applied/no-op interactions, so freshness still expires when verification stops. This is observed authenticated verification, not a new financial revision or an invented state update.

The host receiver bounds verification JSON to 4,096 bytes and rejects duplicate/extra fields, noncanonical identities, Boolean revisions and malformed hashes before invoking the pinned image. Existing SSH identity safeguards, finite command deadlines, output bounds and production lease apply. The client validates the returned exact receipt before removing its pending packet. A lost verification response retains the same packet and its next attempt verifies the same cursor.

Scoped Sonnet review `20261012T133928Z-a08ca3c9` completed once with no retry/fallback (46.306 seconds, 5,212 input / 2,318 output tokens), covering six selected diffs. Every claim was checked locally:

- UUID/re/json imports are already present in the receiver, and actual helper invocation is tested.
- Successful `no_op` status describes the verification interaction; it does not rewrite the stored financial replication receipt. Byte-preservation fixtures prove this distinction.
- The existing readiness writer is intentionally imported at invocation; actual CLI verification exercises that import and its profile-lock behavior.
- The receiver validates the raw origin as a canonical UUID before action dispatch. Alternate spellings are rejected consistently.
- Lost-response coverage now explicitly proves no prior pending packet, retention of the same manifest/hash after the failure, and successful retry without another apply.
- `args.hash` is an argument attribute and does not shadow the built-in function.
- Tests verify an existing applied receipt and compare the returned receipt exactly. Native review added a failing test for mismatched requested/applied acknowledgement fields, followed by the additional equality guard.

This follow-up addresses reopened #33. Source/replica readiness and exact receipt readback after GitHub deployment remain required acceptance evidence.
