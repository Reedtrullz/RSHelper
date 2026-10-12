# Remaining issue release evidence

Owner authorized execution of the remaining-issues deployment plan on 12 October 2026. Baseline main: `c27fd83c1c91c3afa1ca80d64b78c04483f5e5d3`.

This matrix records observed acceptance; pending rows are not implementation claims. Private state and rehearsal exports are excluded.

| Wave | Issues | Implementation / PR | Release evidence | Residual acceptance |
| --- | --- | --- | --- | --- |
| A | #31, #32 | PR #78 merged as `4c7e08a08b86d3581616436733023c3e73f55381`; issues closed, Project Done | PR CI38197004334 and main38197171322 passed; public/OCI revision matches; 882 offline tests/63 files/4 explicit provider skips; both Node suites;7 provider tests/0 skips; deployed-image recovery passed | Accepted |
| B | #22, #23, #40 | #22 snapshot/event implementation in progress | Controlled interleaving, failure/isolation,16-client HTTP ceiling/shutdown and memory fixtures pass; release pending | Full regression/review/release; #23/#40 pending |
| C | #15, #45, #50 | Pending | Pending | Atomic alerts, entry modes, measured container constraints |
| D | #18, #21, #39, #30 | Pending | Pending | Candle normalization, confidence, scan comparability, verified recipes |
| E | #16, #17 | Pending | Pending | Paper fill lifecycle and shared resource accounting |
| F | #29, #41, #43, #19, #20 | Pending | Pending | Strategy/equity, settings/reviews, replay alignment, held-out data |
| G | #38, #26, #24, #25, #27 | Pending | Pending | Discovery, explanations, accessibility/touch trials, safe saved views |
| H | #42, #46, #47, #48 | Pending | Pending | Offers, stress, reviewed events, bounded processing chains |
| I | #35, #36 | Pending | Pending | Planner and complete child issue reconciliation |

CI, production identity, private replication, domain facts and human/device trials require separate evidence. Every accepted release must include exact PR head, main revision, workflow results and public health identity before dependent tasks proceed.

## Wave A local acceptance

- CLI: reviewed parse/help matrix covers all43 leaf commands and flags; real
  scanner format/snapshot fixtures supplement existing action-specific tests.
- Browser: owner access/revocation, all9 view routes, Activity strategy routing,
  rejected mutations, retained drafts on error and durable close retries pass.
  #23's async response/form refresh work remains open.
- Providers: actual disposable-HOME Wiki acquisitions validate latest/mapping,
  executed-trade volume and history. Cached/unidentified data cannot certify live
  provider checks. Import no longer probes the network or silently skips failures.
- Restore: expected identified source revision and unsupported app versions fail
  before activation. All13 restore tests pass, including later acknowledged-state
  preservation and interrupted publication.
- Docker rehearsal: retained compatible8d4bc635 -> c27fd83c -> retained8d4bc635
  on an owned synthetic volume. Interrupted staging restore exited9, then another
  container recovered10 units/180GP with stable identities and exact source
  receipt; old-backup replacement of later writes was refused. Recovery check
  took0.178s in app code/3.638s including container+SSH. Source backup fingerprint
  `9327d940e90349ca2524147e807cfdfe232a1dacbefcee2575c5ed19ac2994d0`.
  The unreferenced owned volume was removed. This is a measured fixture, not a
  production recovery-time guarantee.
- Native review and one Anti Sonnet review completed; confirmed suggestions
  simplified the legacy guard, exercised native crypto and bounded Node CI runs.
  Other suggestions contradicted inspected code or executed evidence and were
  recorded in the private task ledger.

## Wave A deployed acceptance

PR head `c5009009d52e41a8d0201b2d0e8e3ad93b326feb` passed exact-head CI.
Main checks, GHCR publication, Ansible deployment and public verification passed
in run38197171322. Public health and OCI revision both equal `4c7e08a0`.
Declared digest: `sha256:401ecabae47c0608b7cda07d3a7af296f1ac785177e71295bc77629ef4b7cc33`;
physical image: `sha256:684b9fc9bb0646e4191dc766319922daed3edc82a2cf2bdc1809b98d002ee519`.

Retained c27fd83c -> deployed4c7e08a0 -> retained c27fd83c ran against an
owned synthetic Docker volume. Interrupted restore exited9; fresh-container
recovery preserved10 units/180GP, identities and receipts, and refused an old
backup over later writes. Recovery check:0.135s app/3.002s including Docker/SSH.
The unreferenced fixture volume was removed; rollback images remain retained.

The installed Mac runtime advanced to4c7e08a0 after a coherent backup and
quiesce. Owned jobs resumed, trader cycle was healthy, and private sync recovered
its retained packet idempotently: revision13 acknowledged with no pending packet.
Subsequent authenticated VPS HTTP readback showed natural advancement to14 with
equal requested/applied revision and hash. VPS controls remain disabled.

## Wave B1 connection budgets

Each SSE consumer holds at most8 event references; at most16 subscribers are
accepted. Events above16384 UTF-8 bytes disconnect with a small resync marker.
Disconnecting handlers retain their admission slot until unsubscribe, so slow
writes cannot bypass the16-stream ceiling by reconnecting immediately.
A full queue discards its backlog, emits resync and closes the stream; reconnect
receives the current revision and reloads authoritative HTTP data. Socket writes
are bounded by10s. Shutdown detaches subscribers and sends a shutdown marker.

The controlled tracemalloc fixture queued8 distinct approximately16KiB payloads
for16 consumers (128 references); observed peak235003 bytes. Payload strings
are shared between queues. The test asserts a512KiB ceiling for this fixture;
this excludes socket buffers, HTTP threads and the process's other allocations,
which #50 measures before choosing production container limits. HTTP fixture
accepted16 subscribers, rejected17th with503 and verified stream closure and
subscriber release on shutdown. These are measured fixtures, not load guarantees.
