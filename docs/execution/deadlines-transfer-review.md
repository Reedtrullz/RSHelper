# Review decisions

Anti Sonnet run20261012T013105Z-93daa81b completed all three staged review chunks;
its synthesis returned504. Native review read all three retained lane outputs
and checked their claims against source and targeted tests. No successful Anti
synthesis or blanket review approval is claimed. The preceding bounded attempt
20261012T012528Z-8f631ec1 stopped after one of two chunks at its call-admission cap.

## Confirmed and addressed

- Packet wrapper collided with the existing three-argument helper. Fixed the
  wrapper call and retained the existing helper; all private sync/replication tests pass.
- Sync status read/write needed serialization. Both now hold the profile lease.
  Advisory status failures preserve the original financial recovery exception.
- CSV field-size limits are global. CSV imports serialize setting/parsing/restoring
  the limit. There is no remote import endpoint.
- A supplied preview operation UUID is now validated; omission remains allowed.
- Added failure-of-pre-apply-backup evidence and populated trade/watch/partial-lot
  round trips. Earlier round trips already exercised explicit apply and backup.

## Checked and rejected

- Shared cache directory is intentional: provider pacing crosses profiles. The
  worker captures the call-site directory so a late worker cannot follow a restored
  test patch into another cache. It is not per-profile request pacing.
- Semaphore release exists only in the worker finally; no double release path.
- Body reads check the deadline before and after each read. The caller deadline
  additionally bounds uncancellable DNS/headers; residual workers are capped.
- Reentrant acquisition scopes restore the caller's deadline. Response handles
  and cache paths belong to distinct provider worker threads, not that caller.
- `_read_file` already exists. Pre-apply capture is inside the same profile lease;
  a crash after a durable backup safely leaves that backup, before any publication.
- Import errors are not silently swallowed by the sync helper. Readiness updates
  are advisory and report a bounded warning if a publication needs recovery.
- Export temp files share the destination directory; exclusive linking prevents
  overwrites and finally cleans scratch. A precheck plus rename would race.
- `profile_uuid` on inspected manifests is derived from backed-up activation;
  JSON/CSV reconstruction removes only this derived alias. Actual activation and
  explicit target UUID remain validated.
- Readiness JSON is consistent with the existing maintenance commands. Authorization
  runs before the readiness branch; real HTTP tests prove401 without a token.
- Transfer tests explicitly apply, check prior ZIP and compare restored bytes.
  An absent target after preview proves the read-only contract, not atomic apply.
- `provenance(None)` is an established safe unknown/stale result.
- Timing assertions run before the fixture cleanup sleeps. They distinguish the
  old four-second stream wait from a0.2second budget; cleanup is outside the bound.
- Cache-path mock matches its actual signature. Throttle-path assertions check
  an existing compatibility contract and raise on absence; they cannot silently pass.
- The shared file lock is held in a different thread from the provider worker.
  Context-manager teardown releases it even if an assertion fails.
- Status explicitly selects fields in every outcome; stalled/conflict responses
  use the same serializer and never expose `last_result`.
- ZIP inspector already rejects absolute/noncanonical/traversal members. Transfer
  reuses that inspector; the negative transfer test adds envelope coverage.
- A failed local import inside a test raises an error; it cannot silently skip.
- Slow fixture bodies intentionally remain incomplete. Server worker threads are
  daemonized; server shutdown closes the listening socket and joins its serve loop.

Remaining limit: OS DNS/header calls may outlive the caller; the four worker slots
bound residual work. No network limit is bypassed. Tests and GitHub CI, rather than
the timed-out advisory synthesis, are the release gates.

## Focused follow-up

The subsequent Sonnet review of current readiness/transfer modules completed with
success/complete. Checked all eight findings:

- Added explicit rejection of non-boolean authority metadata and tests for future
  cycle times. Future cycles already degrade; no extra reason taxonomy is needed.
- Existing and symlinked export targets refuse without changing their bytes; added
  a test. Destination parents remain an owner-controlled filesystem boundary,
  consistent with existing backups; concurrent hostile ancestor replacement by
  the same OS user is outside this CLI transfer contract.
- POSIX exclusive linking cannot overwrite an existing destination. Temp files
  use the same directory; no cross-device linking. CLI now reports I/O refusal cleanly.
- CSV's 513 rows include one manifest plus at most512 files, exactly matching the
  inspected ZIP and JSON budgets. There is no off-by-one content allowance.
- Profile UUID derivation is the existing inspected-backup contract; activation
  supplies the UUID and explicit target validation still runs.
- Validated JSON/TOML profile files are UTF-8; arbitrary binary files cannot pass
  export validation. Unknown/binary files are excluded by the backup allowlist.
- No API/readiness import cycle exists. CLI and HTTP integration tests call status;
  they cover runtime module loading as well as null market provenance.
