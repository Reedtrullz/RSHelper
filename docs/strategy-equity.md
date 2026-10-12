# Strategy attribution and observed paper equity

New entries retain a SHA-256 fingerprint of the full effective configuration,
its parameters and an aware UTC effective time. A running auto-trader supplies
its actual TraderConfig rather than pretending a newly edited configuration was
already adopted. A sale records its own exit configuration when queued;
collection keeps that evidence and the original entry configuration. Existing
records without entry evidence remain explicitly unknown. No historical money
or strategy defaults are rewritten.

Configuration context uses half-open UTC intervals: a change at10:00 applies
at10:00, not09:59:59. Context at exit is separate from immutable entry strategy
attribution. Turnover ROI divides realized profit by realized acquisition cost;
it excludes open holdings and is not account wealth growth.

Whole-profile marked equity uses the explicitly initialized paper bankroll,
available cash minus any deficit, reserved cash, and remaining holdings marked
to their own exit leg after per-unit GE tax. Open losses remain included. A
missing mark or unreconciled financial activity makes aggregate equity and
equity return unknown. Coverage retains marked/missing acquisition cost and item
IDs. Each observation carries its UTC timestamp, Book revision, source metadata
and whole-profile scope independently of Activity's trade filters.

`trade status --save-equity-snapshot --json` saves an observation, including
unknown observations. Scan commands accept `--intraday-snapshots`, which implies
snapshot saving. These options retain the latest96 intraday observations per
type and a daily alias. Retention touches only the matching timestamped snapshot
files; it never removes financial operations, collection receipts or tombstones.
Sampling is explicit. No historical equity is fabricated from realized trades.
The chart disconnects unknown marks and observation gaps over24hours; the table
shows every retained observation. This gap threshold is a display rule, not a
claim that a missing day was observed.

Configuration evidence on new native financial rows is included in its immutable
identity proof. Existing proofs without those fields remain unchanged. A reader
from before this feature may reject newly attested rows; rollback financial
writers must remain quiesced and use the preserved coherent backup or a reader
that understands the configuration proof. New readers preserve these fields
through private backup, transfer and replication. Public synthetic projections
retain the approved six trade/four position fields and omit configuration text.

## Review evidence

One bounded Sonnet review covered six complete files (tuning/history/bank/
snapshot/native identity and strategy fixtures), one generation with no retry or
fallback,15540 input/1217 output tokens/31seconds. Its nine claims were checked
locally: history self-comparison deliberately qualifies each stored scan's own
specification quality, with cross-snapshot comparisons owned by diff; it does
not always report compatible (legacy/proxy/incomplete cases are qualified).
Corrupt/falsy tuning state raises before append, with broken/empty-object fixtures.
Snapshot config hashing now reuses tuning.config_id. Invalid timestamp samples
cannot infer observation times; discarding them increases the measured interval,
and the chart explicitly describes observed-only samples. Budget unknown reasons
are strings produced by the validated shared calculator. Both snapshot branches
use the same scan-type whitelist, now covered by both traversal cases. Mixed
direction/tax bank fixtures already exist. Added exact-time conflict coverage
showing unknown exit context and no configuration ID. No model assertion was
treated as a verified defect without source or runtime evidence.

Local final checks:1034tests/75files/four explicit offline provider skips,
zero failures/errors;20 Node view scenarios plus authentication. Fresh owned
Wiki runs exercise all four scan intraday flags and two equity observations;
six timestamped files are retained, and authenticated bank/history/Activity
agree on the same revision2 shared budget. Partial collection36GP/remain4,
1108 marked equity/10.8% return, missing marks, exact UTC conflicts, native
configuration proof and private backup fields have deterministic fixtures.
Canonical integration, financial reader rehearsal and deployment remain pending.
