# Full-catalog discovery

Use **Find item** to search mapped names or exact IDs independently of scan
profitability. Choose a result to inspect metadata, instant quote legs, tax,
net profit, source/time and the current scanner's exact eligibility reasons.
Watching an unpriced mapped item is permitted for authenticated owners; priced
paper actions retain fresh quote, executed-volume and shared-budget guards.
The inspector distinguishes instant execution from the configured scan direction.
Its hourly figure is an illustrative volume extrapolation, not a promised return.

The CLI item-info, watch-add and shared direct-action resolver use the same
mapping lookup. Exact ID precedes exact name; ambiguous names require choosing
an ID. Missing quotes preserve metadata with null economics. Alchemy and signal
item selection use the full-catalog inspector rather than requiring a flip row.

GET /api/catalog accepts q (at most200 characters) and limit (1–50). GET /api/item
accepts one positive ID. Unknown/duplicate arguments are rejected. Public demos
can read only public market data; owner mode requires its existing bearer token.
Metadata and reasons are escaped. Authentication, view and selection generations
prevent old responses from restoring another selection or disconnected data.
No financial schema, configuration, backup inventory or replication class changes.

## Measured bounds

On2026-10-12 this Mac acquired4663 mappings and fresh latest quotes from the
Wiki network. The capped50-row pure search used4598 JSON bytes and about1.9ms.
A real local dashboard response used4889 bytes and21.7ms including HTTP; its
rendered context used5213 UTF-8 bytes with exactly50 result buttons. A browser
click through rendered accessibility observation took1072ms, including tool
and observation overhead, so this does not measure isolated browser rendering.
These are one-run fixture observations, not production latency guarantees.
The response cap50 and query cap200 are the current resource budget; narrowing
the query is the next action when the cap is reached.

The actual browser found Abyssal whip4151 outside eligible flips and displayed
fresh source/time, tax15720GP, instant loss23828GP and specific margin/profit
exclusions. Live disposable-HOME item-info produced valid JSON and watch-add
resolved the same ID; the app removed the test watch before HOME cleanup.
Physical touch and human screen-reader acceptance remain separate in25/24.

## Validation and review

1082 Python tests across79 files passed, with four explicitly offline provider
skips; seven fresh provider checks passed separately. All26 Node view scenarios
and the auth suite passed. The six catalog tests also passed on production
Python3.11. Fixtures cover numeric names, duplicate names, ordering, capped
queries, missing/unsafe quotes, metadata escaping, real HTTP authorization,
unpriced watch callbacks and shared scanner/display economics.

One scoped Anti Sonnet review20261012T151609Z-8201a258 completed. Its generic
exclusion concern was confirmed and fixed by extracting FlipScanner.explain;
scanner and inspector now use one calculation. The other five claims were
refuted locally: unique substring returns before the error path, validation
prevents the claimed undefined matches path, scan_kwargs exists before callback
execution, search and details deliberately have distinct whitelisted schemas,
and the existing positive-ID parser rejects id=abc. Explicit tests cover the
unique substring, actual runtime callbacks and real HTTP invalid-ID boundary.
The native review checked the remaining template, scanner extraction and result
escaping. The scoped review is not a claim that every project file was reviewed.
