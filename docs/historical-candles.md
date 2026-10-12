# Historical candle evidence

Wiki histories are normalized before caching, analysis, charts and replay. The
declared interval is 5m, 1h, 6h or 24h. Timestamps must be positive integer UTC
seconds. Valid rows are sorted; identical duplicates collapse. Conflicting rows
at one timestamp are all rejected so input ordering cannot select a price.
Malformed rows are counted and rejected without crashing the remaining series.

Coverage reports the actual span, expected windows, missing windows, gap
intervals, irregular intervals and rejected/duplicate/conflicting counts. No
missing candle is invented. Analysis requires six usable priced windows and
rejects irregular spacing. Its reliability includes priced-window coverage;
historical volume scoring retains the existing five-minute units across declared
intervals. Price legs, tax, ranking and trader defaults retain their conventions.

CLI margin JSON, item-info JSON and dashboard timeseries responses carry
`candle_coverage`. Margin CSV includes scalar coverage columns. Cached histories
contain canonical valid rows: rejection counts describe the current input read,
not a persistent lifetime count of provider errors.

Replay expects five-minute input and reports per-item coverage. Empty or
irregular series stop the dataset with an explicit error; they are not silently
removed from the tested universe. Reordered input and identical duplicate rows
produce the same financial result while quality metadata records the duplicates.

Local acceptance on 12 October 2026: 915 tests in 66 files, four explicit offline
provider skips, browser authentication and 15 view scenarios. Live Wiki CLI and
authenticated HTTP checks returned 365 unique samples for all four intervals;
the hourly response disclosed one real missing window. Two bounded Sonnet diff
reviews were triaged against local tests, including a fail-closed replay fix.
These are local checks; GitHub CI and exact-revision deployment remain pending.
