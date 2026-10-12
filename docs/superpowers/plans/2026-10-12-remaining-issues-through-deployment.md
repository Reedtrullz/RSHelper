# Remaining RSHelper Issues Through Deployment Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Native implementation is the default; delegation must satisfy the user's current model and acceptance policy. Steps use checkboxes for tracking.

**Goal:** Resolve the 29 remaining work issues, deploy and verify each accepted release through GitHub, and reconcile roadmap tracker #36 only when every child outcome is accounted for.

**Architecture:** Extend the existing stdlib CLI, inline dashboard, coherent profile transactions and immutable-image release pipeline. Reuse identity, realization, backup and private replication primitives. Separate coherent market, journal and configuration revisions; none substitutes for another.

**Tech Stack:** Python 3.11+, standard library only, built-in Node test tools, browser validation, Docker/GHCR, Ansible/Caddy, macOS LaunchAgents, GitHub Projects V2.

**Spec:** Current canonical issue bodies at https://github.com/Reedtrullz/RSHelper/issues, the current `AGENT_WORKFLOW.md` and `AGENTS.md`, and the issue-specific acceptance criteria below. Issue numbers are existing canonical work items; do not create replacements. This document is a planning artifact, not implementation or deployment evidence.

## Baseline and planning disposition

Observed 12 October 2026:

- Canonical main and public health: `c27fd83c1c91c3afa1ca80d64b78c04483f5e5d3`.
- Public immutable image digest: `sha256:0e5fe5def2c996edb29c0c35699681671699aa3cd2c8b00f35004c290d1f1ddc`.
- 30 open issues: 29 work items plus #36. No open PRs. Of the open Project items, 29 are Intake and #50 is Blocked. None is currently Ready.
- Project15 is accessible, correctly linked to Reedtrullz/RSHelper, with lifecycle fields and 11 saved views. `AGENT_WORKFLOW.md` is present. No planning bootstrap is needed.
- Most issue evidence was last reconciled against `dc031910` on 7 October, before releases74-77. Residual text must be rechecked before implementation, particularly #31 and #32.
- Development plan location: `/Users/reidar/.codex/worktrees/rshelper-all-issues/RSHelper/`. Its source at `17c8900d` matches the merged PR77 source; no source changes are made by this plan.
- Preserve primary WIP at `/Users/reidar/Projectos/RSHelper`. The installed clean Mac runtime at `/Users/reidar/.codex/worktrees/rshelper-coordinated-release/RSHelper` is an operational checkout, not a development workspace.

The latest request is planning only. The steps below describe future execution, including GitHub writes, merges and deployment. They do not authorize this planning turn to perform those actions.

## Global constraints

- Python 3.11+; no new PyPI dependencies. Keep the existing inline dashboard architecture.
- stdout is data; status/errors use stderr. Preserve JSON/CSV piping, `--quiet`, every documented command/flag and profile isolation.
- Route tax through `rshelper.market.ge_tax()`: repository contract is 2%, floor per item, 5M cap, no minimum. Reverify current game rules from authoritative sources when domain work starts; do not retune from old research notes.
- Preserve API high as buy price and API low as sell price; direction changes economics rather than field identities. Preserve reliability times profitability confidence and expected-GP/hr scanner rank.
- Preserve fresh cache -> Wiki -> Tracker -> stale cache, source/volume provenance, shared cooldowns, 30s provider and 60s acquisition deadlines.
- Freeze active strategy parameters unless a separately justified change is explicitly authorized. Historical replay defaults and comparisons are not current-performance evidence.
- Mac is financial authority; VPS is replica; VPS daemon controls stay disabled. Real state, backups, packets, free text and credentials remain private. Synthetic public fixtures and existing Git history remain unchanged.
- Financial changes use the profile transaction and durable operation IDs. New durable files require explicit schema, backup/restore and replication-class coverage; advisory derived files must not become accidental financial authority.
- Check disk before test/build loops, use bounded owned scratch and preserve backups. The owner has already authorized continuing despite low storage in this ongoing work; do not repeat that question or infer permission for destructive cleanup.
- Keep CI, deployment identity, private sync, domain correctness, physical-device/accessibility trials and owner usefulness trials as separate claims. Close only fully accepted issues.

## Review focus

1. Publication interrupted by a crash or retry: #32/#16/#17 must retain later writes, receipts and exact quantities.
2. Old async results crossing view, owner or revision boundaries: #22/#23/#21/#40 must reject stale completion without clearing good UI data.
3. Unknown quotes, volume, marks or historical coverage: #16/#18/#29/#30/#46 must retain unknowns rather than manufacture zeroes or successful fills.
4. Legacy state lacking new facts: #39/#29/#43/#42 must preserve bytes/economics and explicitly identify unknown attribution or provenance.
5. New private metadata accidentally leaking through URLs, demo responses or transfers: #27/#41/#42/#43/#47 must respect authentication, schema allowlists and export policy.

## Execution order and release boundaries

| Wave | Issues, in local order | Result | Prerequisites |
|---|---|---|---|
| A | #31, #32 | Complete contract coverage and recovery acceptance | Closed foundation issues and #28 |
| B | #22, #23, #40 | Coherent market reads, bounded SSE, stable browser refresh and paged Activity | A; #40 follows #23 |
| C | #15, #45, #50 | Atomic alert crossings, durable entry pause/drain, measured container constraints | #50 follows #22 and recovery acceptance |
| D | #18, #21, #39, #30 | Normalized history, correct confidence cache, comparable scans, audited recipes | Closed provenance/config foundations; #21 follows #18 |
| E | #16, #17 | Explicit paper fill stages and shared resource accounting | D; #17 follows #16 |
| F | #29, #41, #43, #19, #20 | Exact strategy/equity history, safe settings, private reviews, aligned replay and held-out reports | E; #41/#43 follow #29; #20 follows #19 |
| G | #38, #26, #24, #25, #27 | Catalog discovery, explanations, keyboard/mobile acceptance and saved views | B/D/E; #25 follows #24 |
| H | #42, #46, #47, #48 | Observed offers, conditional stress, reviewed events and small processing chains | Relevant E/F/G contracts |
| I | #35, final #36 reconciliation | Explainable paper portfolio planning and complete roadmap accounting | #17/#20/#26/#29 accepted |

These are sequencing waves, not giant PRs. Default one reviewable issue per PR; closely coupled changes may share a PR only if each acceptance gate remains traceable. Deploy an accepted software slice before building dependents against it. Independent #30 or bounded UI work may progress while an external acceptance trial is pending. Do not merge concurrent deployment waves onto the shared VPS.

All paths below are relative to the development checkout. Future new interface names are design decisions, not claims that functions already exist.

## Task A0: Revalidate and maintain the issue ledger (#36)

- [ ] Read canonical main, each issue's full body and relevant merged PRs, current Project state and actor activity before assigning an implementation task. Compare old findings with actual code and release evidence.
- [ ] Record an issue-to-PR-to-release acceptance matrix under `docs/execution/remaining-issues-progress.md`, with exact head, checks, release, residual acceptance and next dependency. Never overwrite earlier evidence ledgers.
- [ ] When execution is authorized, refine stale residuals without replacing history; move a work item to Ready only when current evidence and bounded acceptance meet `AGENT_WORKFLOW.md`. Keep #50 blocked until #22 and measured rehearsal prerequisites hold.
- [ ] Update #36 incrementally after each accepted release, retaining unrelated unmet device/domain/owner gates. The tracker closes only after all child work is accepted or explicitly dispositioned by the owner; deployment alone cannot close all 30 issues.

## Task A1: Finish CLI and browser contracts (#31)

**Files:** `scripts/run-tests.py`, `tests/test_output_contract.py`, `tests/test_cli.py`, `tests/test_http_inputs.py`, `tests/test_browser_auth.mjs`, `.github/workflows/ci.yml`, `HANDOFF-v4.0.md`; add `tests/test_cli_contracts.py` and `tests/test_browser_views.mjs` only for missing coverage.

**Interface:** Reuse the existing offline runner and CLI parser. Maintain a reviewed command/flag-to-fixture matrix covering the documented surface and parser additions. Commands that start daemons or mutate/delete state execute only against owned synthetic profiles with bounded teardown.

- [ ] Compare parser/docs with executable contracts; write failing contracts for uncovered flags, quiet/JSON/CSV output, private authorization, HTTP framing/SSE, view changes and mutation errors. Assert no real HOME access and no provider requests in offline mode.
- [ ] Extend the existing fixtures rather than building a second runner. CI must discover every test and report counts, skips, failures, errors and `not_run`; provider failures cannot silently skip deterministic coverage.
- [ ] Run `.venv/bin/python scripts/run-tests.py --offline --json` and both built-in Node scripts. Acceptance: zero failures/errors, `complete=true`, no undocumented command/flag gaps. Run a separately labelled disposable-HOME provider smoke with actual provenance.
- [ ] Follow the release checklist. This task improves the testing surface; it does not certify later UI/device changes before they exist.

## Task A2: Close verified recovery gaps (#32)

**Files:** `src/rshelper/backup.py`, `src/rshelper/recovery.py`, `src/rshelper/state_transaction.py`, `deploy/playbook.yml`, `docs/execution/coordinated-state-runbook.md`, `docs/execution/profile-backups.md`, `tests/test_backup_restore.py`, `tests/test_state_transaction.py`, `tests/test_production_lease.py`; add one bounded rehearsal script only if existing drills cannot produce the missing receipt.

**Interface:** Reuse `backup.restore_profile(...)`, the coherent bundle inspector, transaction recovery and existing immutable-image rollback. No second restore implementation or automatic production state rewind.

- [ ] Map issue acceptance to releases74-77: coherent identified restore, image/state compatibility, retained later writes and source/state receipts. Reuse valid evidence where sufficient; define only the missing failure scenarios.
- [ ] In separate owned state roots/volumes, inject a failure after migration/publication and after later acknowledged writes. Assert fresh-process recovery, stable lot/operation identities, exact receipts, duplicate retry safety and preservation of later writes. Reject corrupt/truncated/hash-mismatched bundles before publication.
- [ ] Rehearse old-compatible/new/old-compatible image behavior on disposable state, record checksums and measured recovery time, and document which version can read/write that state. Prove image rollback without overwriting current financial state with an old backup.
- [ ] Fix only demonstrated gaps; if existing implementation satisfies the issue, deliver evidence/runbook changes instead of a code rewrite. Production verification is read-only; no fault injection into the live owner volume.
- [ ] Follow the release checklist and require the rehearsal receipt before closing #32.

## Task B1: Coherent market snapshots and bounded SSE (#22)

**Files:** `src/rshelper/dashboard/server.py` (`refresh`, market callbacks, `EventHub`), `src/rshelper/dashboard/handlers.py` (SSE), `src/rshelper/market_data.py`; `tests/test_dashboard.py`, `tests/test_market_consumers.py`, new `tests/test_market_snapshots.py`.

**Interface:** Reuse `market_snapshot`; a successful refresh publishes one complete snapshot reference with `revision`, `items`, `latest`, `volume`, mapping and provenance. Each request captures one snapshot. Subscribers receive revision notifications and reload authoritative state on overflow/reconnect.

- [ ] Fail tests with interleaved refresh/read and slow SSE clients: all source/items/volume in one response must share a revision, no unbounded queues, no subscriber leak after disconnect/shutdown.
- [ ] Build/validate outside the publication lock and swap one snapshot under it; failures retain the last valid generation. Use bounded queues, an explicit resync/disconnect marker and a finite subscriber ceiling. Document the chosen numeric queue/subscriber budgets with measured fixture memory before release.
- [ ] Assert reconnect returns current state and cannot treat an old event as a new snapshot. Preserve lightweight public health and readiness's no-fetch contract.
- [ ] Follow the release checklist; record queue bound and concurrent fixture results.

## Task B2: Preserve forms and reject stale UI responses (#23)

**Files:** `src/rshelper/dashboard/scripts.py` (`setView`, `setStrategy`, `fetchData`, detail/Activity renders and SSE), `src/rshelper/dashboard/templates.py`, `tests/test_browser_views.mjs`, existing `tests/test_browser_auth.mjs`.

**Interface:** Add view/detail request generations to existing `authEpoch`/AbortController fences. Strategy changes render the active view. Refresh replaces data elements while retaining draft values, focus and scroll.

- [ ] Deliberately resolve requests in reverse order across tab/item changes; assert the newest view/revision wins. Type into a paper/config form during SSE/poll refresh and assert values/focus survive.
- [ ] Coalesce refreshes, abort obsolete requests and fence completion against owner, view and market revision. Retain good data and inputs on errors; show server errors with an actionable retry.
- [ ] Assert Activity strategy changes remain in Activity, disconnect clears private state, and mutation retry reuses the same operation ID where required.
- [ ] Run executable JS contracts and a bounded real-browser trial; follow the release checklist.

## Task B3: One journal read and bounded Activity pages (#40)

**Files:** `src/rshelper/journal.py`, `src/rshelper/history.py`, dashboard `server.py`/`handlers.py`/`scripts.py`; `tests/test_journal.py`, `tests/test_history.py`, `tests/test_browser_views.mjs`, new `tests/test_activity_pages.py`.

**Interface:** Add pure `summarize_trades(trades, filters)` and `page_trades(trades, *, revision, cursor, limit, filters)` over one validated journal snapshot. Return revision, total/filtered counts, bounded rows and next cursor. Keep explicit full-history CLI/export behavior.

- [ ] Instrument the loader: one history/summary snapshot must load once. Synthetic 1k/25k/100k histories must produce identical totals and bounded pages. Equal timestamps use stable record identity as tie-breaker.
- [ ] Derive summary and rows from the same immutable snapshot; bind cursor to journal revision and filter fingerprint. A changed revision returns an explicit restart result rather than silently mixing pages. Set a maximum page size of100 and validate date/strategy filters.
- [ ] Verify no duplicates/omissions within a stable revision, invalid cursors fail safely, UTC boundaries are explicit, and full CLI exports retain previous valid economics.
- [ ] Record before/after reads, bytes and timings, without inventing a latency guarantee. Follow the release checklist.

## Task C1: Atomic alert crossings (#15)

**Files:** `src/rshelper/alerts.py`, `src/rshelper/watchlist.py`, `src/rshelper/monitor.py`, dashboard `server.py`; `tests/test_alerts.py`, `tests/test_monitor.py`, `tests/test_watch_identity.py`.

**Interface:** Add `emit_watch_if_due(profile, item_id, margin, *, now, source_revision)` under the shared profile transaction. Persist rule crossing state and alert/dedupe together; notify only after durable commit. Keep recurring reminder versus crossing semantics explicit.

- [ ] Use two real processes for the same breach: exactly one persisted event. Concurrent edits to different watched items must retain both. Exercise breach/recovery/re-crossing, cooldown/hysteresis, threshold revision change and notification failure.
- [ ] Reuse existing identified threshold transactions; remove separated check-then-set callers. Failed delivery leaves the persisted alert and a bounded notification-status result.
- [ ] Cover legacy/profile isolation and private merge behavior; follow the release checklist.

## Task C2: Durable entry pause and drain (#45)

**Files:** add `src/rshelper/trading_mode.py`; modify `trader.py`, `cli.py`, dashboard `server.py`/`handlers.py`/`scripts.py`, backup and replication schema inventories; `tests/test_trader.py`, `tests/test_daemon_installer.py`, new `tests/test_trading_mode.py`.

**Interface:** `set_mode(profile, mode, *, expected_revision, reason, operation_id)` and `read_mode(profile)` return revisioned `running`, `entries-paused` or `draining`. The authority checks the mode within the transaction that authorizes opening; replica displays it without financial mutation authority.

- [ ] Race pause acknowledgment against an opening transaction: after acknowledged pause revision, no new entry can publish. TP/SL/time exits and idempotent realization continue.
- [ ] Persist reason/source/effective UTC time, require explicit resume, and record drain completion when no positions remain without force-selling or automatic restart into running.
- [ ] Prove restart/KeepAlive/profile isolation and CLI JSON; register the mode file as authority-owned durable state for backup/restore and private replication.
- [ ] Exercise controls on the Mac/synthetic owner server. Keep VPS `--control` disabled. Follow the release checklist and verify stance separately from process readiness.

## Task C3: Measured container constraints (#50)

**Files:** `deploy/templates/compose.production.yml.j2`, `deploy/playbook.yml`, `deploy/README.md`, `Dockerfile` only if writable-runtime adjustments require it; deployment fixtures and `tests/test_production_lease.py`.

**Interface:** The same non-root service, port5555 and durable HOME mount gain read-only root, dropped capabilities, no-new-privileges, bounded tmpfs and measured PID/memory limits. No state-path/mount migration.

- [ ] Inventory required writes and effective host/container limits read-only. Measure cold start, refresh/fallback, concurrent HTTP/SSE and state apply against synthetic volumes under the existing provider budgets.
- [ ] Enable constraints in a disposable deployment; assert `/home/rshelper` atomic writes and approved temp writes work while writes elsewhere fail. DNS/HTTPS, tokens, locks and health checks must still work.
- [ ] Choose PID/RSS/temp caps from measured peaks plus documented headroom, accounting for bounded residual provider workers and packet processing. Do not guess production numbers before measurements.
- [ ] Inject bounded overload and prove clean degradation/restart without corrupting durable data. Rehearse constraint rollback preserving state and verify `docker inspect`/cgroup settings after deployment. No Docker prune or shared-host cleanup.
- [ ] Follow the release checklist. Unblock #50 only when #22 and its rehearsal actually pass.

## Task D1: Normalize historical candles (#18)

**Files:** `src/rshelper/market_validation.py`, `src/rshelper/analysis.py`, `api.py`, `scanner.py`, dashboard `server.py`, replay loading; `tests/test_analysis.py`, `tests/test_market_validation.py`, `tests/test_replay.py`.

**Interface:** `normalize_candles(rows, timestep)` returns validated sorted unique rows and coverage/gap metadata for5m/1h/6h/24h. `analyze_timeseries(..., *, timestep='5m')` uses that explicit interval; update every caller.

- [ ] Fail on unsorted/conflicting duplicate, malformed, absent-timestamp and sparse fixtures. Deterministic duplicate policy: identical timestamp/value rows collapse; conflicting values are rejected/quarantined with coverage reasons, not selected by input order.
- [ ] Preserve real gaps; do not fabricate candles or assume missing timestamps are5m evidence. A malformed row cannot crash the whole batch; report rejected counts and actual observed span.
- [ ] Verify all timesteps, confidence factorization and unchanged price-leg/tax/rank conventions. Follow the release checklist.

## Task D2: Coalesce history acquisition and score current quotes (#21)

**Files:** `api.py`, `analysis.py`, `scanner.py`, dashboard `server.py` (`get_confidence`); `tests/test_request_budget.py`, `tests/test_provider_deadline.py`, new `tests/test_confidence_cache.py`.

**Interface:** Historical acquisition is keyed by profile/item/timestep; quote-dependent scoring is keyed additionally by market revision and effective configuration. An in-flight map shares one bounded fetch per history key and cannot publish to an expired generation.

- [ ] Controlled overlapping requests must dispatch once per key; duplicate batch IDs collapse and existing batch cap30 remains enforced. Different profiles stay isolated.
- [ ] A new market revision recomputes current profitability while reusing unchanged historical components. A late failed/expired completion cannot fill a newer generation.
- [ ] Bound in-flight/cache inventories and honor global pacing and acquisition deadline; unsupported history remains explicit. Follow the release checklist.

## Task D3: Comparable scan manifests (#39)

**Files:** `snapshot.py`, `cli.py`, `scanner.py`, `history.py`, dashboard summary consumers; `tests/test_snapshot.py`, `tests/test_history.py`, `tests/test_cli.py`.

**Interface:** Extend `snapshot.save(..., *, scan_spec, market_metadata)` with a versioned manifest and deterministic specification fingerprint. Comparisons return `compatible`, `partially-comparable` or `incompatible` with reasons.

- [ ] Assert changes in direction, units, membership/filter settings, capital and truncation cannot emit unqualified improvement/regression. Same-spec fixtures retain valid comparison behavior.
- [ ] Preserve coverage/selection provenance and unknown removal reasons; missing items are never zero-profit losses. Legacy data is provenance-unknown and original bytes remain intact.
- [ ] Keep daily behavior compatible; intraday retention belongs to #29. Follow the release checklist.

## Task D4: Recipe evidence and eligibility (#30)

**Files:** `recipes.py`, `scanner.py` (`ProcessScanner`), `models.py`, `config.py`, `cli.py`, dashboard process renderer; `tests/test_recipes.py`, `tests/test_scanner.py`, `tests/test_config.py`.

**Interface:** Extend curated recipe metadata with primary-source URL/review date, input/output/run units, rate basis, membership/level/unlock requirements and unknown evidence. `recipe_breakdown(recipe, prices, account)` produces eligibility and limiting factors shared by CLI/dashboard.

- [ ] Verify existing supported recipes from current authoritative Wiki/game sources; quarantine unverified timing/yield/eligibility claims rather than expanding the table. Unknown account facts remain unknown, not eligible.
- [ ] Fixtures cover batch outputs, success/yield assumptions, process fees, per-unit tax and zero/unknown buy limits. Distinguish input acquisition caps from sell-throughput estimates.
- [ ] Assert CLI/dashboard agree on economics and explain different filters explicitly. Follow the release checklist; record domain review separately from synthetic arithmetic.

## Task E1: Explicit paper fill lifecycle (#16)

**Files:** `ge_offers.py`, `positions.py`, `realization.py`, `trader.py`, `cli.py`, dashboard callbacks/renderers, strict schema/backup/replication inventories; `tests/test_ge_offers.py`, `tests/test_realization_callers.py`, `tests/test_native_writers.py`, `tests/test_profile_transfer.py`.

**Interface:** Persist a typed paper stage per stable lot/offer: buying, bought, selling, collectable, collected/canceled, with partial quantities, timestamps and explicit liquidity/fill assumptions. `advance_paper_offer(offer, market_snapshot, now, policy)` is shared by CLI/dashboard/trader. Collect validates stage/ownership server-side and realizes through existing operation receipts.

- [ ] Model fixtures use explicit participation parameters, not an inferred real queue position. Unknown/zero/proxy volume and stale/unusable quotes hold progression with reasons. Elapsed time alone cannot complete an unknown fill.
- [ ] Define a reviewed conservative paper participation policy before activation; distinguish illustrative simulation from measured execution. Preserve agreed price-leg and exit-policy semantics. No entry-price substitution for an unavailable exit quote.
- [ ] Exercise partial buy/sell/cancel/collect, repeated operation IDs, crash recovery, tax/basis/cash conservation, and insufficient collect eligibility. CLI/dashboard/runtime must consume the same state.
- [ ] Preserve old lot IDs/economics. Explicitly preview/back up legacy compatibility migration; missing stage facts are labelled legacy/unknown rather than invented. Register new files/fields across schemas, backup, import/export and replication.
- [ ] Rehearse migration/compatible image rollback in disposable volumes before the controlled Mac upgrade. Follow the release checklist, including private exact receipt verification.

## Task E2: Shared capital, slots and rolling limits (#17)

**Files:** add `src/rshelper/budget.py`; modify `positions.py`, `ge_offers.py`, `trader.py`, `cli.py`, dashboard callbacks, config and all durable-schema inventories; `tests/test_positions.py`, `tests/test_trader.py`, new `tests/test_budget.py`.

**Interface:** `budget_snapshot(profile, now)` reports available/reserved/unknown cash, slots and per-item purchase-window capacity. `reserve_budget(profile, request, *, expected_revision, operation_id, now)` validates and commits with the corresponding entry transaction; fill/cancel releases use the same receipt identity.

- [ ] Repeated manual/automatic entries cannot bypass caps, and two racing requests cannot both consume the last capacity. Partial fills/cancellation release correctly; retry does not double-reserve.
- [ ] Verify current authoritative slot/window rules before selecting account-specific numbers. Unknown historical capacity remains visible and blocks an unqualified available-capacity claim.
- [ ] Migrate conservatively: existing overflow positions stay visible and managed, with no forced liquidation. Test both paper entry surfaces and profile isolation.
- [ ] Reconcile durable reservations against lots/stages after crash/import/replication; stale packet replay cannot reintroduce spent capacity. Follow migration and release gates.

## Task F1: Exact strategy eras and marked equity (#29)

**Files:** `tuning.py`, `history.py`, `snapshot.py`, `journal.py`, `positions.py`, `bank.py`, `trader.py`, dashboard charts; schema/backup/replication inventories; `tests/test_tuning.py`, `tests/test_history.py`, `tests/test_snapshot.py`, `tests/test_bank.py`.

**Interface:** Immutable effective config IDs/time intervals attach to new entry/exit evidence; `config_at_timestamp(timestamp, entries)` uses UTC instants. Equity snapshots expose realized/unrealized value, cash, reserved cash and missing-mark coverage separately.

- [ ] Two changes on one UTC day attribute surrounding entries/exits correctly. Define interval boundaries consistently; an exit retains entry strategy identity and records its own effective exit config.
- [ ] Legacy rows remain attribution-unknown unless existing timestamp/config evidence proves attribution. Do not edit realized quantities/prices/profit. Distinguish turnover ROI/activity rates from marked equity returns.
- [ ] Include open losses and missing marks in gap-aware charts; prohibit misleading aggregate return when coverage is incomplete. Intraday scan retention is opt-in and bounded; it never deletes operation receipts/tombstones.
- [ ] Exercise partial closes, transfers, clock boundaries and retention; follow the release checklist.

## Task F2: Preview and apply configuration (#41)

**Files:** `config.py`, `tuning.py`, `cli.py`, add `src/rshelper/config_edit.py` if separation is warranted; dashboard callbacks/UI and strict schemas; `tests/test_config.py`, `tests/test_tuning.py`, `tests/test_browser_views.mjs`.

**Interface:** `preview_config(profile, candidate)` returns effective/default/profile values, field diff, current revision and restart requirements. `apply_config(profile, candidate, *, expected_revision, operation_id, backup_path)` validates, retains prior config and records one exact tuning transition atomically.

- [ ] Invalid TOML/fields and stale revision change no files; injected publication failure preserves config/attribution. A retry produces one transition, and rollback is a new explicit transition restoring prior values.
- [ ] Narrow writer supports only documented settings; preserve unknown/commented extensions or refuse apply, never silently rewrite arbitrary TOML. Display which config revision each process actually uses.
- [ ] Build CLI-first preview/apply, then authenticated owner settings using the same functions. Replica/VPS cannot mutate authority-owned financial/strategy settings. No automatic launchd restart or VPS daemon enablement.
- [ ] Verify JSON, owner/public denial, effective times and explicit restart guidance; follow the release checklist.

## Task F3: Private hypotheses and reviews (#43)

**Files:** add `src/rshelper/trade_reviews.py`; modify `history.py`, CLI/dashboard Activity/details, persistence/schema/backup/replication allowlists; `tests/test_history.py`, new `tests/test_trade_reviews.py`, browser contracts.

**Interface:** `append_review(profile, lot_uuid, entry, *, operation_id, expected_revision)` stores versioned annotations separately from immutable economics, with hypothesis/planned exit/tags/review history. Partial realized children retain parent lot attribution.

- [ ] Corrections append history; editing a review cannot change quantities/prices/tax/P&L. Retry/import/merge does not duplicate reviews and explicit tombstones remain respected.
- [ ] Retain documented legacy note filters through a tested compatibility path. Summaries disclose filters, sample counts and missing hypotheses.
- [ ] Exclude private free text from public/demo outputs and shared URLs; test explicit private export policies. Follow the release checklist.

## Task F4: Shared runtime/replay decisions (#19)

**Files:** `trader.py`, `ge_offers.py`, `budget.py`, `scripts/replay.py`, `scripts/sweep.py`, `config.py`, `tests/test_replay.py`, `tests/test_trader.py`.

**Interface:** Extract/reuse the smallest pure entry, exit, fill and budget decisions; one explicit adapter maps effective trader config into `ReplayConfig`. Replay has an injected clock and simulated state, never owner-file writes.

- [ ] Run aligned synthetic candle/poll traces through both paths: ranking, grace/blend, thin prints, reentry, stages, capital, tax and exit prices match. Publish a tested list of intentional candle-versus-poll differences.
- [ ] Resolve historical harness-default drift through explicit config selection, preserving production strategy defaults. No copied second implementation of money rules.
- [ ] Assert replay imports/execution never read/write owner financial state or invoke game actions. Follow the release checklist.

## Task F5: Reproducible held-out evaluation (#20)

**Files:** `scripts/replay.py`, `scripts/sweep.py`, add `scripts/replay-dataset.py` only if acquisition/inspection needs an owned command; `tests/test_replay.py`, new `tests/test_replay_dataset.py`; dataset runbook.

**Interface:** Explicit dataset path plus manifest with source, item/time coverage, timestep, hashes and immutable chronological train/validation/holdout splits. Report contains config hash, model/fill assumptions, baseline/sensitivity and sample counts.

- [ ] Deterministic synthetic manifest reruns yield the same report; missing/corrupt/incompatible data fails clearly. Assert holdout data cannot choose parameters or alter the selected config.
- [ ] Inventory available verified market-only historical data, normalize through #18 and pin immutable snapshots. Do not call the historical30-item result a fresh held-out experiment.
- [ ] Run one bounded experiment when independent coverage is adequate; publish actual item/regime limitations. If independent data is insufficient, ship the deterministic tooling and retain the issue's empirical gate instead of inventing results or monitoring indefinitely.
- [ ] Follow the release checklist. No automatic production retuning or profitability claim; empirical report acceptance is separate from CI.

## Task G1: Complete catalog discovery (#38)

**Files:** add `src/rshelper/catalog.py`; modify `cli.py`, dashboard `server.py`/`handlers.py`/`scripts.py`, watch resolution; `tests/test_cli.py`, `tests/test_dashboard.py`, new `tests/test_catalog.py`, browser contracts.

**Interface:** `resolve_item(query, mapping)` and `search_catalog(query, mapping, *, limit=50)` resolve full metadata independently of eligible scanner items. Item-details response includes stable ID, metadata, quote/source/time, server economics and exclusion reasons.

- [ ] Cover numeric IDs versus numeric names, exact/ambiguous names, absent mapping/quotes, escaped metadata and deterministic capped results. Excluded items remain searchable/watchable; no priced action is allowed without a usable quote.
- [ ] Reuse one resolver in direct CLI, alch/signals/watch and inspector. Keep scanner filters intact. Measure full-catalog response/render bytes/time before documenting a budget.
- [ ] Exercise owner/public route policy and current-view fencing; follow the release checklist.

## Task G2: Ranking explanations and onboarding (#26)

**Files:** scanner result serialization, `analysis.py`, `cli.py`, dashboard templates/scripts; `tests/test_scanner.py`, `tests/test_market_consumers.py`, browser contracts, README.

**Interface:** Server-computed explanation payload contains buy/sell legs, tax, confidence factors, throughput constraint, source/volume quality, exclusions and paper assumptions. UI reads these values rather than re-deriving economics.

- [ ] Build a short scan -> watch -> paper -> review path; explain empty eligibility, unavailable history and Tracker proxy volume separately. Unknowns and exclusions offer concrete next actions.
- [ ] Cross-display fixtures assert identical price/tax/rank numbers and no promised real returns. Run a bounded first-use owner trial; record usefulness separately from automated checks.
- [ ] Follow the release checklist; keep owner-trial acceptance open if feedback is unavailable.

## Task G3: Keyboard/dialog/chart accessibility (#24)

**Files:** dashboard templates/scripts, browser contracts; optional focused accessibility checklist under docs.

**Interface:** Native actionable buttons/dialogs, synchronized selected tabs/panels, focus restoration and live status messages; charts have text/table equivalents and reduced-motion behavior.

- [ ] Executable DOM/browser checks cover tab state, complete keyboard paths, Escape, focus return, invalid inputs/status announcements and chart equivalent data.
- [ ] Implement using native semantics and existing layout rather than a UI framework. Test owner connect/disconnect and every newly introduced primary workflow.
- [ ] Perform an actual keyboard and screen-reader review, retaining explicit human/device evidence. DOM assertions alone do not close this gate. Follow the release checklist.

## Task G4: Small-screen/touch workflows (#25)

**Files:** dashboard styles/templates/scripts, browser fixtures and responsive acceptance note.

**Interface:** Reachable navigation/actions, viewport-bounded dialogs, usable touch details and compact tables while retaining desktop density.

- [ ] Browser trials at320/375/768px and200% zoom must show no inaccessible actions or obscured inputs; verify dialog scrolling, viewport changes and current forms.
- [ ] Include touch-accessible alternatives to hover and appropriately sized targets. Record physical-touch owner acceptance separately; simulated touch/browser sizing is not a physical-device claim.
- [ ] Follow the release checklist; retain unmet physical trial if owner feedback is unavailable.

## Task G5: Saved views and safe URLs (#27)

**Files:** dashboard templates/scripts, profile-scoped preference schema and backup inventory if persisted server-side; browser contracts and `tests/test_profile.py`.

**Interface:** Validated URL parameters for public-safe view/item selection; bounded named scan presets scoped by profile identity. Private views still require owner access; URLs never contain notes, records or tokens.

- [ ] Reload/back/forward restores intended view/selection. Invalid/unsupported URLs safely fall back; ambiguous or unavailable item state stays explicit.
- [ ] Bound presets and supported values; prove profile isolation and correct refresh generation handling. Do not add arbitrary filter scripting or a sharing service.
- [ ] Follow the release checklist.

## Task H1: Separate observed GE offer ledger (#42)

**Files:** add `src/rshelper/observed_offers.py`; CLI and dashboard observed lane, strict persistence/identity/backup/replication schemas; new `tests/test_observed_offers.py`, transfer/browser tests.

**Interface:** `record_observation(profile, offer_uuid, event, *, operation_id, expected_revision)` appends planned/placed/partial/canceled/collected observed events with quantities, actual price/fees, provenance and UTC observation time. Use existing profile transactions/UUID primitives; narrow CSV preview/apply follows manual workflow.

- [ ] Synthetic observed receipt sequences reconcile units/fees and repeated receipts are idempotent. Corrections preserve the audit trail. Collected quantities cannot exceed recorded fills.
- [ ] Keep paper estimates permanently distinguishable; no silent promotion into observed P&L. Integrate #17 observed reservations without counting cash/slots twice or implying the game account was read automatically.
- [ ] Reuse #28 staging/validation and mandatory pre-apply backup for narrow CSV imports, with unknown-item/conflict preview. Test malformed/mixed provenance and disclosure boundaries.
- [ ] Follow financial migration/release gates; offer a bounded owner manual-offer trial for feedback without making it an extra mandatory closure gate. No game automation or inference of real account inventory.

## Task H2: Conditional stress/concentration (#46)

**Files:** add `src/rshelper/scenarios.py`; `bank.py`, dashboard view and CLI reporting; new `tests/test_scenarios.py`, bank/browser fixtures.

**Interface:** Pure `evaluate_scenario(holdings, cash, market_revision, specification)` returns exposure concentration, baseline/marked/after-tax values and missing coverage, with explicit per-item/group/all shocks and optional declared haircuts.

- [ ] Zero shock reconciles to the selected baseline; per-unit tax, partial lots, mixed directions and cash/reservations have deterministic fixtures. Unknown marks stay unknown; incomplete coverage blocks misleading total-return percentages.
- [ ] Pin input revision and every price-leg/haircut/group assumption in the exported scenario spec. Separate observed/paper holdings; no forecast, invented probabilities or liquidity guarantees.
- [ ] Follow the release checklist and record owner usefulness trial before adding richer models.

## Task H3: Reviewed event annotations (#47)

**Files:** add `src/rshelper/event_annotations.py`; dashboard charts/text alternatives, replay manifest/export; new `tests/test_event_annotations.py`, browser/replay tests.

**Interface:** Validated annotations carry UTC interval, type, item/group scope, uncertainty, review state/date, reviewer and primary-source URL. Only reviewed events render as verified; private observations remain a separate class.

- [ ] Start with a few freshly source-verified events, never bulk-promote historical research notes. Test interval boundaries, overlap/filtering, correction/deletion and accessible chart equivalents.
- [ ] Export event-linked windows through #20 with selection/missing-coverage disclosure, preventing hindsight contamination. Removing annotations must change no trading decisions or default replay outcome.
- [ ] Apply private free-text/export policy and bounded storage. Follow the release checklist.

## Task H4: Small curated processing chains (#48)

**Files:** add `src/rshelper/recipe_plan.py`; `recipes.py`, process CLI/dashboard; new `tests/test_recipe_plan.py`, recipe/browser fixtures.

**Interface:** `plan_processing(inventory, target, recipes, prices, constraints)` uses explicit manual inventory and only #30-reviewed recipes. Return integer batches, material shopping/manual steps, opportunity costs, separate GP/XP/time objectives and coverage limits.

- [ ] Begin with one supported reviewed recipe family. Assert material/intermediate conservation, no input double-counting, integer batch rounding, cycle rejection and clear unsatisfiable constraints. Single-step economics match #30.
- [ ] Bound depth/candidate exploration deterministically and report when search is truncated. Unknown XP/time/yield evidence remains unavailable rather than fabricated.
- [ ] Keep paper positions separate from actual entered inventory. Follow the release checklist and an owner trial demonstrating benefit beyond a single process scan before scope expansion.

## Task I1: Explainable paper portfolio planner (#35)

**Files:** add `src/rshelper/planner.py`; scanner/budget interfaces, replay/sweep report integration, CLI and optional read-only dashboard, private advisory trace schema/backup inventory; new `tests/test_planner.py`, replay/browser fixtures.

**Interface:** Pure `plan_portfolio(candidates, budget, config, market_revision)` proposes a bounded allocation with inclusion/exclusion reasons, remaining cash/slots/buy-limit capacity and confidence/liquidity assumptions. No execution or automatic tuning.

- [ ] Begin with a deterministic greedy baseline, using #17 capacity and disclosed #16 fills. Candidate order/ties are stable, oversized/unknown capacity is excluded explicitly, and the zero-feasible-candidate result explains constraints.
- [ ] Decision replay ties proposals to exact dataset/config/market revisions and compares the baseline on #20-held-out windows. Preserve #26 explanations and #29 strategy attribution.
- [ ] Persist opt-in bounded private decision traces, including proposals/skips, frozen input/config hashes and assumptions. Use an advisory-only file class with a documented count/byte retention bound; do not replicate or publish it as financial state. Verify a retained trace reproduces allocations/reasons exactly.
- [ ] Assert the pure proposal function and counterfactual replay never spend beyond known cash/slots/windows or mutate active trader/financial state. Only the explicit trace recorder writes advisory data. Do not label simulated returns optimal or predicted; richer optimization requires demonstrated owner utility.
- [ ] Follow the release checklist and owner trial, then reconcile #36 after all other acceptance gates are resolved.

## Mandatory release checklist for every implementation PR

1. **Scope/current truth:** Read exact main/head, issue/dependencies, actor activity and local WIP. Reuse an attached development worktree where safe; create `codex/<scope>` from current canonical main. Never use the installed runtime for development.
2. **Failing proof:** Add the task's meaningful regression/contract tests; verify RED, implement the smallest change, verify GREEN. Financial/schema changes also exercise compatibility/import/replication and killed-writer retry boundaries. No weakened tests or new dependencies.
3. **Complete local gates:** Run `.venv/bin/python scripts/run-tests.py --offline --json`; require zero failures/errors, all discovered files executed, and only named intentional offline skips. Run `node tests/test_browser_auth.mjs`, the new views suite where applicable, `git diff --check`, touched CLI JSON/CSV/quiet contracts and bounded live provider smokes in disposable HOME. Report real source/cache provenance.
4. **Review:** Native diff review and required Anti sidecar review for larger rounds. Revalidate capability/access; record unavailable review or timeout honestly. Triage every finding against local evidence. A successful partial chunk is not whole-diff approval. No role dispatch bypasses model/picker/same-chat acceptance gates.
5. **Private/migration readiness:** Validate new schema inventories, capture coherent private backups using app commands, inspect compatibility and exact receipts; rehearse changes and compatible rollback on owned disposable state. Keep backup/packet/credential artifacts out of Git/PR/Obsidian. No production corruption/overload injection.
6. **Commit and PR:** Use repository commit convention and required signing. Commit only the intended paths. Open and attach the PR to this chat. Describe final behavior/tests/limits and list every issue; use `Closes` only if merge satisfies the complete acceptance. Use `Refs` for human/data/live acceptance still pending.
7. **Exact-head CI:** Verify remote PR head/base and all required checks on that exact head. Fix real failures, rerun only checks affected by the fix, and re-review substantive changes. Never merge a stale/untested head.
8. **Authorized merge and GitHub deployment:** Once execution covers delivery, merge with matched head. Main push runs `.github/workflows/ci.yml`: checks -> GHCR build/push -> immutable-digest Ansible deploy -> exact-SHA public health. Capture the canonical merge SHA and matching run. Wait for all jobs, not just PR checks; serialize releases through existing production concurrency/host leases.
9. **Live identity/access:** Compare public health build revision/digest, running physical image and OCI revision with the merge. Verify actual private auth/readiness, public/demo denials and disabled VPS controls. Run the task's live acceptance through its real surface without publishing private rows; provider status is time-sensitive.
10. **Mac runtime upgrade when affected:** Quiesce only owned trader/private-sync jobs with `install-trader-launchd.sh quiesce`, fast-forward the clean runtime to the verified merge, use `install --private-sync`, verify staged helper/plist identity, then `resume`. Do not run the retired raw Git helper. Verify native cycle success and one actual sync exact revision/hash HTTP acknowledgment with no pending packet. A persisted quiescence checkpoint is recovered idempotently, never discarded blindly.
11. **Failure path:** On failed candidate deploy, retain compatible rollback image/state and inspect actual health before retry. Roll back code/constraints using the tested compatible image; never overwrite later financial writes with stale backups. If private sync fails, retain pending packet and continue receipt recovery with its same identity. Stop dependent release work until consistency holds; independent non-shared tasks may continue.
12. **Lifecycle/log/stop:** Re-read issue state and Project item after complete acceptance; set Done only for completed scope, retain residuals open with reasons. Update #36, the local release matrix, Obsidian daily/project notes and durable operational memory without secrets. Record temporary ownership and clean only inactive owned scratch. Stop after the bounded acceptance checks pass; no indefinite endurance loop or additional polishing.

## Owner/data acceptance and issue closure

No immediate owner action is required to begin the technical work after execution is requested. Later tasks need concrete human acceptance evidence:

| Gate | Issues | What is needed after implementation |
|---|---|---|
| Screen-reader and physical touch | #24, #25 | Actual principal-workflow trial; browser/DOM/simulated touch evidence recorded separately |
| New-user clarity | #26 | Short scan/watch/paper/review trial and specific points of confusion |
| Product usefulness | #35, #46, #48 | Small prepared scenario or supported recipe trial with reviewable outputs; #42 manual-offer trial is optional feedback |
| Game/recipe/event facts | #17, #30, #47, #48 | Fresh primary-source evidence; unknown account eligibility remains explicit |
| Independent evaluation data | #20, then #35 and #47 replay exports | Verified manifest, independent chronological coverage and no holdout selection leakage |

Prepare each complete technical artifact and instructions before asking for a trial. Missing human/data evidence does not block independent work, but it does prevent claiming that issue accepted. Software can deploy with truthful partial scope; use `Refs`, not premature closing keywords. The full roadmap finishes only once these gates are satisfied or the owner explicitly changes their scope.

## Coverage self-check and completion condition

Work-issue inventory: #15,#16,#17,#18,#19,#20,#21,#22,#23,#24,#25,#26,#27,#29,#30,#31,#32,#35,#38,#39,#40,#41,#42,#43,#45,#46,#47,#48,#50. Each appears in exactly one implementation task and one wave. #36 is governance throughout and final closure. All open prerequisites appear earlier; closed prerequisites are revalidated rather than reimplemented.

- [ ] No requested acceptance is omitted; every row maps to files, interfaces, failure fixtures and release checklist.
- [ ] New schemas/files have explicit identity/persistence/backup/replication/privacy decisions before activation.
- [ ] All accepted software changes are merged, exact-SHA CI/deployment verified, dependent Mac runtime upgraded where required and private sync acknowledged.
- [ ] Human/domain/data gates are explicitly accepted or remain open; no imagined trials or unqualified profitability claims.
- [ ] Final GitHub/project state and #36 match the evidence; primary WIP/private evidence/approved fixtures remain preserved.

Start with A0/A1, then determine whether A2 needs code or only a missing recovery receipt. Do not start the entire portfolio as one branch or one deployment.
