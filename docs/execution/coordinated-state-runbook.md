# Coordinated state release and cutover

The owner approved the synthetic demo and staged private transition on
12 October 2026. Both real default profiles are identified: Mac financial
authority and VPS replica, with separate origins and retained history. The
initial live forward revision, explicit reverse packet and second forward
revision have exact applied receipts. The legacy Git workflow is retired;
`data/state` contains only the approved invented examples. Installation, final
release identity and continuing scheduled-delivery evidence belong in the
release handoff; these are separate from the initial transfer receipts.

## Identity and ownership

Declare one profile UUID shared by its replicas and a distinct source origin
UUID for each independent writer. The Mac trader is the planned financial
authority; the VPS is a financial replica. Origin is never inferred from a
hostname, folder, numeric ID or equal record counts.

| State | Replication rule |
| --- | --- |
| Positions and journal | Authority creates and realizes lots; replicas retain immutable creation and realization proof |
| Watchlist and alerts | Shared revisions and retained tombstones; divergent revisions produce an explicit conflict |
| Tuning log and selected snapshots | Informational copy by origin; does not replace the destination's local operational files |
| Config, active profile, cooldowns, volume baselines, recent exits, daemon state/PIDs/sockets | Local only |
| Identity manifests, activation, intents, batches, financial and replication receipts | Private proof retained with the profile; never public demo data |

Every identified writer takes the profile lease. Native creation proof binds its
operation UUID, request hash and immutable record hash; position proof also
binds creation quantity. Open quantity plus retained realized quantity must
equal the created quantity. Same-ID retries cannot change economics. Tombstones
and receipts have no automatic purge. File readers reject a publication marker;
profile snapshots recover pending redo before reading a coherent generation.

## Before a live transition

1. Record the exact main SHA, successful Actions run, GHCR digest, running image
   ID/baked identity and compatible rollback artifact. Verify both hosts run the
   compatible code and that VPS daemon controls remain disabled.
2. Inspect only schema/identity/count metadata, owned launchd labels and the
   exact `/opt/apps/rshelper/data` bind mount. Check free disk and SSH identity.
   Do not treat a health response or an equal count as a receipt or lineage proof.
3. Obtain the owner decision below. Then quiesce the three owned launchd jobs:
   `scripts/install-trader-launchd.sh quiesce`. The durable private checkpoint
   records previously loaded jobs and hashes of their plists. Bootout prevents
   KeepAlive from restarting an old writer. A repeat resumes the same checkpoint.
4. Capture and inspect private app-owned backups on each host. Store them outside
   the profile with mode 0600; retain the inspected source revision and profile
   UUID. Do not put backups, lineage plans or packets in public Git.

Commands below use the installed compatible release's Python with `PYTHONPATH=src`.
Select the profile before `state`; generate UUIDs once and retain each operation ID.

```sh
python -m rshelper --profile default profile backup /private/path/before.zip --json
python -m rshelper backup inspect --input /private/path/before.zip --json
python -m rshelper --profile default state migration-plan --origin ORIGIN_UUID --profile-uuid PROFILE_UUID --lineage /private/path/lineage.json --json
python -m rshelper --profile default state migrate --plan /private/path/plan.json --operation-id OPERATION_UUID --json
python -m rshelper --profile default state check --json
```

Lineage is an explicit JSON decision. Independent sources use `mode=independent`;
known copied ancestors use `mode=common` with `common_origin_uuid`; mixed sources
use `mode=resolved` with a complete `record_origins` inventory keyed by the
application's legacy migration keys. All forms require `financial_authority`
and `replication_origins`. Ambiguity, undeclared origins, duplicate source records
and an authority adopting foreign open lots fail before activation. Any change
to a core source hash invalidates its preview; generate and review a fresh plan.

## Private transfer and exact acknowledgement

The private destination is the installed application at `/opt/apps/rshelper` on
`Racknerd-Deploy`; transfer uses SSH's existing verified host key and identity
with BatchMode, IdentitiesOnly and IdentityAgent=none. The installed receiver
checks the running compatible image and exact writable private volume, takes
`production.lock`, and runs that image ID as UID 1000 with network disabled and
read-only packet staging. Apply and receipt publish in one recoverable transaction.

```sh
python scripts/sync-private-state.py --profile default --dry-run --json
python scripts/sync-private-state.py --profile default --json
python scripts/sync-private-state.py --profile default --status --json
python -m rshelper --profile default state receipt --origin ORIGIN_UUID --json
```

Pending reservation, packet and acknowledgement live in the profile's private
cache outbox, outside its state directory. After a lost response, the client
queries the durable destination receipt and resubmits the same packet if needed.
It only acknowledges matching profile, origin, revision and packet hash with
status applied/no_op. Wrong target, changed ancestry, conflict or corrupt
metadata leaves the pending packet intact. Logs and receipts contain metadata,
not rows or credentials. The authenticated owner endpoint is
`GET /api/state/receipt?origin=UUID`; anonymous requests are denied.

Full-profile validation and recoverable publication have a finite 150-second
receiver deadline and a 180-second apply RPC deadline; receipt queries retain
the shorter 60-second client deadline. Byte budgets, exact identity/hash checks
and helper cleanup remain enforced. The real 22,163-trade transition exceeded
the original 45-second receiver limit; the same retained packet applied after
extending that deadline and was acknowledged through the ordinary client.

Automatic scheduled transfer is Mac to VPS. Shared VPS edits return through an
explicit private reverse packet: capture with the running pinned application,
download the 0600 ZIP into a private Mac path, apply it with `state apply`, then
send the next Mac revision with the private sync client. Retain the exact packet
and receipt for retry; never use raw JSON or Git as the return path. The initial
live reverse transfer was proved, but an automatic reverse job is not installed.

Only after the first private receipt is proved, install the explicit private
job with `scripts/install-trader-launchd.sh install --private-sync` (add
`--with-monitor` only if the monitor was previously installed). Its staged
helper resolves `RSHELPER_REPO` to the compatible immutable checkout. The
default installer continues to select the legacy helper. Never run the legacy
Git publication helper against an activated profile: it refuses before capture.

For the compatible-code handoff before E08, use `install --keep-sync` from the
immutable checkout. It verifies the new trader's readiness while preserving the
installed sync plist/helper and loaded job. It cannot be combined with private
sync installation. Preserve any installed monitor with `--with-monitor`.

## Recovery and rollback

An interrupted migration/apply is recovered from the original bounded redo
intent, without regenerating an operation or resubmitting a replacement request.
Keep writers quiesced on any unexplained source/target mismatch. Inspect the
original migration or replication receipt before acknowledging or resuming.
`scripts/install-trader-launchd.sh resume` preflights every unchanged plist and
reloads only jobs that were loaded before quiescence. Verify daemon readiness
separately; a launchctl load receipt is not application readiness.

An approved change from raw Git sync to private sync changes the sync plist.
After private receipts are verified, archive the original quiescence checkpoint
and old helper with the private handoff backups, then use the explicit private
installer and its readiness gate. Do not call `resume` on changed plists or
reload the old raw job. Keep the original checkpoint for recovery evidence.

A legacy backup can be restored only to an empty inactive target, with an
explicit expected profile UUID and its exact inspected source revision. This
proves pre-activation recovery to the original bytes; it does not permit replacing
an active identified profile with old data. After identified writes, rollback
uses compatible code and the current durable private volume. Normal restore
refuses loss of acknowledged rows, financial proof or replication cursors.
Downgrade to legacy code and disaster recovery that discards newer acknowledged
operations are not provided by this release.

## Owner decision package (E08)

Approved choice on 12 October 2026: a **synthetic demo**. Publish only invented
fixture rows through the existing default-deny serializer, with approved fields:

| File | Proposed synthetic public fields |
| --- | --- |
| trades.json | item_id, qty, buy_price, sell_price, tax_paid, profit |
| positions.json | item_id, qty, buy_price, direction |

Names, notes, account labels, timestamps, watchlists, alerts, operational state,
identity and receipts remain private in this policy. The alternatives are a
separately reviewed real-data field policy or no public demo. Preview and
serialized output must agree before any publication. Unknown fields/profiles
fail closed; synthetic output is not a claim of real-data anonymization.

Private continuity was proved before retiring the legacy State Sync workflow
and generating the approved output. The raw Mac job remains quiesced until the
private installer handoff; the identified private volume must not consume demo
files as operational state. The exact policy is committed in
`public-demo-policy.json`. Existing public Git history remains retained.
Historical removal, repository visibility changes and receipt/tombstone deletion
require separate explicit decisions. Restoring an empty deployment requires a
private app backup and explicit identity; the synthetic examples are unusable as
an operational seed.

## Rehearsal evidence and release record

The local final-candidate evidence lives under `.execution/`, with summaries in
the retained execution ledger. Synthetic process tests cover killed publication,
lost response, revision ancestry, collisions, common lineage, shared edits,
closed-lot conservation and restore refusal. Docker Python 3.11 tests exercise
the native writers, packet merge, migration and restore. Disposable Docker apply
and Ansible failure exercises preserve unrelated containers and retained proof.
The initial real SSH receipts and explicit owner approval are separate evidence
from those synthetic rehearsals.

The compatible batching release is PR75/main
`d3f405dccd50034c9a72d3fdd62c1ab6f2f63b24`, deployment run38185360517, digest
`sha256:32364940ed16cc9864629bffabf6b40879b75c6a2f5d9f5692f2479cffeed691`.
Both hosts' six critical module hashes matched. Both real profiles migrated from
inspected private app backups; live Mac revision1, VPS reverse revision1 and Mac
revision2 applied with exact durable receipts. Final publication/client rollout,
installed-job readiness, later natural-update receipt and compatible current-state
rollback evidence must be recorded after those operations succeed.
