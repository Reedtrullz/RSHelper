# Paper lifecycle and shared budgets — implementation contract

The isolated branch integrates a durable financial core with CLI, owner HTTP,
dashboard and daemon callers. It is not activated. The complete integrated suite
passed954 tests across68 files with four explicit offline provider skips and zero
failures/errors. Seven live provider checks and16 Node scenarios passed.
The owner confirmed member capability (eight slots); synthetic free/member/unknown
fixtures remain separate. No owner book or bankroll was initialized.

## Reviewed source boundary

[Grand Exchange](https://oldschool.runescape.wiki/w/Grand_Exchange) confirms3
free/8 member slots and connected buying limits. Its
[buying-limit page](https://oldschool.runescape.wiki/w/Grand_Exchange/Buying_limits)
states that the4-hour timer starts at the first purchase and then resets the
whole window. Direct primary-page reads on12 October2026 were used; older search
index copies were not treated as current verification.

The initial paper policy is explicitly illustrative: at most1% of a fresh,
completed, side-specific Wiki5m execution window, shared across the profile.
It does not estimate a real queue position or certify fills. Unknown/proxy/zero
volume, unusable quotes, pre-stage windows and repeated windows hold progression.
The API retains the original window timestamp instead of deriving one from fetch
time. A sale requires its own later execution window and its pinned limit price.

The budget uses conservative rolling4-hour accounting. Until item-group metadata
is verified, all recent purchases/reservations share a pool bounded by the lowest
involved item limit. This can reserve less capacity than the game's anchored
windows and independent item groups; it prevents variants bypassing a shared
limit and must be labelled as a conservative model. Missing limits/history/account
capabilities remain unknown. Existing overflow stays visible, without liquidation.

## Core evidence

`paper_book.py` uses the existing profile transaction, identity attestation and
durable close batches. Reservations and operation receipts serialize under the
profile lock. An exact retry returns the original operation receipt and current
book revision. Conflicting requests fail. Initialization pins the paper bankroll
and financial baseline; an activation marker prevents a missing acknowledged
book from silently resetting spent capacity. Account slot facts can change only
through an explicit authority operation.

Twenty-seven actor cases cover reservation races, intent recovery, unknown account/
history/limits, partial cancellation, atomic confirmed-lot publication, shared
window allocation, separate sell windows, premature collection, interrupted
collection, pinned tax, profit/loss cash, journal hiding and a legacy partial
sale followed by sale of the remaining holding. Legacy holdings preserve their
old lot identity and have no invented buy-stage fills. In-flight collection
blocks new admission until the original operation completes.

The book is registered for strict persistence, profile transactions, private
backups and financial replication. Owned tests restore an unchanged reservation,
reject a pre-reservation backup, replicate authority reservations and refuse
replica mutation. A reverse packet preserves the same authority-owned book.
Publication rejects incomplete collection receipts and verifies financial rows
against the retained close-batch proofs.

A bounded Anti Sonnet review of the core was triaged. Its proposed retry of a
zero-fill window was rejected: profile allocation cannot decrease while that
window is eligible; this deliberate conservative rule has an explicit test.
The actor freezes the selected item's market evidence and uses the pure result's
canonical window. Sale overflow and loss collection are directly covered.
The initial review admission was refused before submission; its input allowance
was corrected to the helper's byte-based ceiling, retaining one call/no retry/
no fallback. This review does not cover later caller changes.

## Remaining integration and release acceptance

- Store pending purchases separately from positions. Partial buy quantities and
  cost remain visible/reserved; publish a financial lot only after completion or
  cancellation of the unfilled remainder, using `_stage_open_position` in the
  same profile transaction as the stage/budget receipt. Never create unbought
  financial quantity or adjust old attested quantities to match an invented fill.
- A stable offer/operation identity pins economics. Buy/sell/collect stages and
  partial cancellation conserve purchased/sold/remaining quantities. Preserve
  last considered windows and the shared profile allocation ledger under the
  profile lock. New selling stages cannot reuse pre-sale volume.
- Budget admission and offer creation share one transaction and expected revision.
  Lost responses replay the exact operation without double reservations. Account
  slots are explicit; no membership inference from scan filters. Native/manual
  holdings, pending buys and uncollected sales share the declared paper bankroll.
- Retained economic receipts underpin cash; journal visibility is not a refund.
  Capture the explicit initial baseline. Missing legacy purchase history requires
  a conservative4-hour boundary, not inferred historical entries. Pending close
  publication/reconciliation blocks new admissions until recovered.
- Collection validates owner/stage/quantity server-side and realizes the pinned
  modeled sell fills through existing durable close batches. Recovery resumes
  committed intent; it never creates a new quote/fill. Missing quotes never become
  entry-price exits. Legacy recorded holdings retain unknown purchase-stage
  evidence; explicit manual/automatic exit policy must label that distinction.
- CLI, dashboard and trader call the same actor; GET reads do not book trades.
  Replace manual/automatic instant-spread assumptions with queued simulations.
  All positions/overflow remain visible. Admission must retain C2 stance guards;
  completion of previously reserved buys is distinct from new entry admission.
- Register the protocol across persistence, transaction, private backup/restore,
  import/export and authority-owned replication. Reject absent/older budget state
  when it would restore spent capacity. Preserve immutable old lot identities,
  rows, tombstones and operation receipts. Public demos expose no private budget.
- Before activation: native/scoped review, race/crash/cancel/collect/conservation
  cases, owned CLI/HTTP checks, disposable migration/old-new rollback, full suites,
  signed CI/deployment, controlled Mac handoff and exact private receipt. Old
  financial writers remain quiesced during rollback; they cannot enforce this
  protocol. No strategy-default tuning or real game actions.

Activated callers reserve purchases without creating holdings, queue sales without
writing trades, and collect only persisted eligible sale fills. GET never advances
execution. An owned real HTTP chain verifies these transitions and private access.
The actual live Wiki CLI/open/paper/offers and owner HTTP advance returned a held
pre-entry-window reason with no invented holdings/profit; a one-shot daemon cycle
and private backup inventory passed. GE pages expose50 records plus continuation,
including55 historical holdings with unknown execution and explicit overflow.

Legacy new instant closes are refused at the CLI and owner HTTP boundary. Existing
durable close receipts remain replayable offline at their pinned economics. Pure
legacy elapsed-progress helpers remain for compatibility fixtures; the actual
daemon startup requires an identified initialized book. No price fallback books
a new sale. Auto holdings/offers reject manual takeover.

An owned Python3.11 Docker rehearsal preserved a migrated lot's original identity,
sold only four confirmed units, restored the resulting book and financial proofs,
rejected a pre-book restore, previewed private JSON transfer, and read the same
state across old/new/old/new images. Old financial writers must remain quiesced
during rollback because they cannot enforce the book. Candidate image identity
is local rehearsal evidence, not a GitHub deployment receipt.

The prepared C2 stance module must be integrated before activating a book with
stance state; an existing stance file with a missing module fails closed. C2 now
refuses drain completion if a book cannot be read or pending offers/collections
remain. Its922-test/66-file suite passed with four offline skips. Final combined
stance/publication/recipe/history integration still requires release verification.

## Integrated review dispositions

Bounded Sonnet run20261012T095057Z-fb5895dc covered the selected actor/budget files
and CLI/dashboard/daemon diffs in one submitted call, without retry/fallback.
All eight claims were checked locally:

- Missing-price fallback and the old collect endpoint: refusal is the intended
  contract. The UI uses `/api/paper` with stage identity/revision; legacy receipt
  replay does not fetch a quote. Actual owner HTTP and legacy replay tests pass.
- Default sizing and sale capital: zero quantity/capital still defaults to one;
  the close parser has no capital flag and explicitly defaults to all held units.
- Stale request snapshot: the actor rechecks expected revision under the profile
  lock. Conflicts cannot commit stale mutations; exact retry pins the operation.
- Missing adopted lot identity: initialization/financial proof validation require
  identified lots before adoption; uninitialized daemon startup fails before lease.
- Duplicate JS declarations: one declaration and logout assignments were found;
  both Node suites parse and run successfully.
- Missing offers profile and tests: the parent parser supplies profile; actual
  `trade offers --json` dispatch and offline receipt tests already pass.

Native real HTTP testing separately fixed the GE query parser and caught an
outdated HTTP action validator. All paper actions now share its strict schema,
including UUID/revision checks before the callback. HTTP tests cover all nine
actions, malformed receipts, duplicate/invalid page offsets and keepalive bodies.
The scoped review excludes other persistence changes and is not whole-repo or
physical accessibility acceptance. Signed CI/deployment/Mac/private receipt and
controlled owner migration remain required before closing16/17.
