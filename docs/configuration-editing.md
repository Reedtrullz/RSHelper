# Configuration preview and apply

The owner CLI and Settings screen share `config_edit`. A preview returns the
exact current TOML document, profile values, inherited defaults, effective
values, field differences and an optimistic revision. Preview never creates a
missing configuration. Unknown sections/keys, invalid values, malformed TOML
and text over64KiB are rejected; comments and supported sparse documents are
published byte-for-byte. HTTP also enforces its existing64KiB whole-body limit.

```sh
rshelper config preview --input candidate.toml --json
rshelper config apply --input candidate.toml --expected-revision REVISION \
  --operation-id UUID --backup NEW_PRIVATE_ARCHIVE.zip --json
rshelper config rollback --restore-operation-id PRIOR_UUID \
  --expected-revision CURRENT_REVISION --operation-id NEW_UUID \
  --backup NEW_PRIVATE_ARCHIVE.zip --json
```

Apply requires the identified financial authority, a matching current revision
and a new coherent private backup. It uses the existing profile transaction to
publish the exact document and tuning log together. Config readers recover the
publication before reading; a retry replays its stored receipt without a second
transition. Missing middle receipt revisions are rejected at publication,
backup and private replication boundaries. Effective times must advance beyond
every timezone-aware prior transition, including unsorted legacy evidence.
Rollback is a new explicit transition restoring the prior document, with its
own pre-change backup. Preserved configuration receipts are never pruned.

The revision combines the operation ordinal and exact document hash; the
effective config ID hashes the full validated parameter values. A comment-only
edit changes the document revision without inventing a strategy change. Each
actual process exposes its used effective ID: dashboard/trader retain startup
configuration until an explicit restart; monitor reloads each successful poll.
Unavailable or old process evidence remains unknown. Settings refresh does not
replace the editing form. An apply requires previewing that exact text; failed
or ambiguous HTTP responses retain the operation UUID for retry.

Settings is owner-only. HTTP apply/rollback additionally require enabled local
controls; the replica/VPS stays read-only. The screen shows local profile TOML
and local process IDs, while replicated tuning history retains source evidence.
Private TOML and backup paths never enter shared URLs or public/demo responses.
No launchd restart or configuration change to the live owner is performed by
deployment. Trader strategy defaults, initialized paper bankroll, membership,
slots and historical trade economics are unchanged by this release.

## Verification and review

Ten focused cases cover exact comments/default inheritance, CLI JSON roundtrip,
missing-document preview, stale revision and replica denial, four injected
publication boundaries, recovery through `load_config`, one transition on
retry, fresh rollback, unsorted UTC time and missing receipt validation across
backup/replication boundaries. Node contracts cover owner/private routing and
stable settings apply retries. A disposable-HOME actual Wiki CLI/HTTP trial
applies and retries a candidate, restores it through HTTP, observes a pending
dashboard restart and proves unchanged initialized bankroll/eight slots and
historical economics. All trial state is removed with its owned server stopped.

Scoped Sonnet review `20261012T123045Z-44e431b4` sent six complete files in one
generation (33.65seconds,25538input/1293output tokens; no retry/fallback).
The confirmed interior receipt gap is fixed with a regression. Other claims
were checked locally: profile root locks are reentrant and rollback's outer
handle stages no state; sparse candidates expand through validated defaults;
read transactions recover durable publication without staging an intent;
HTTP parsing failures return before action dispatch; `_read_json_object`
returns the cached body; empty corrupt logs raise while genuinely absent logs
return an empty inventory. SSE remains bearer-authenticated and same-origin
fetch, with authorization before subscription; the review's unauthenticated
cross-origin disclosure claim does not bypass that boundary. Existing HTTP,
SSE, replica and transaction tests remain required and unweakened.

Older financial writers stay quiesced during rollback; coherent private
backups retain exact documents, receipts and financial state. Observed
technical checks do not establish human screen-reader/touch acceptance or
held-out strategy performance.
