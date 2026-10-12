# Reproducible replay datasets

Use `scripts/replay-dataset.py` with explicit market-only input files. No command reads the owner's journal, configuration or inventory. It uses the shared runtime replay model and preserves production settings.

`pin` creates a new directory containing the original candle and mapping bytes and a manifest. An existing destination is refused. The manifest records declared provider, URL, fetch time, selection note, five-minute item coverage, byte counts and SHA-256 hashes. Every later command checks bytes, hashes, metadata and chronological splits. Conflicting/invalid candles fail before publication; gaps and duplicate samples are disclosed through the existing normalizer.

```sh
.venv/bin/python scripts/replay-dataset.py pin --data candles.json --mapping mapping.json \
  --destination research-run --provider wiki --url https://prices.runescape.wiki/api/v1/osrs/timeseries \
  --fetched-at FETCH_EPOCH --selection-note 'How items and time range were chosen; limitations' \
  --train-end TRAIN_END_EPOCH --validation-end VALIDATION_END_EPOCH
.venv/bin/python scripts/replay-dataset.py inspect --dataset research-run
.venv/bin/python scripts/replay-dataset.py select --dataset research-run --configs candidates.json --slots 8 > selection.json
.venv/bin/python scripts/replay-dataset.py report --dataset research-run --selection selection.json > report.json
```

Each split is a contiguous, non-overlapping half-open interval: train, validation, then holdout. Every item needs at least two candles per split. Inputs and boundaries must be selected before examining holdout results. Store the manifest, predeclared candidate file and selection receipt together; freeze the receipt before running `report`. Hashes detect accidental changes, not dishonest provenance or deliberate reconstruction of a receipt after seeing results.

The candidate file is a JSON array of one to 64 explicit trader configuration objects. Missing fields use the documented runtime defaults. The first candidate is the frozen comparison baseline. Training and validation results are reported for every predeclared candidate; validation realized bankroll return percent chooses the configuration, with config hash breaking ties. Holdout candles cannot participate in selection. The report revalidates the selection from train/validation and evaluates only the frozen winner and baseline on holdout. Different capital assumptions are normalized by each candidate's initial bankroll and remain visible in the full configuration.

Reports include dataset/config/selection identities, per-item/window coverage, sample and collection counts, baseline, validation sensitivity, open-offer count, fill assumptions and explicit limitations. Each split starts empty and needs its own prior candle for decisions; there is no portfolio or lookback carry across boundaries. Realized metrics exclude uncollected offers and open marked losses. A candidate with poor open positions may therefore rank well; this is a disclosed research objective, never an automatic tuning decision or total-return claim. Do not infer statistical significance from zero or few collections.

## Available data inventory — 12 October 2026

The bounded fresh Wiki smoke acquired 365 five-minute candles each for item IDs 2 and 4151: 730 rows, from epoch 1791705600 through 1791814800, span 109200 seconds (30.33 hours), complete intervals and no rejected/conflicting samples. Actual fetch receipts identify Wiki network delivery at epochs 1791815378.288437 and 1791815379.4874089. Original market-only files and receipts are retained in ignored execution evidence; private trading data is excluded.

This snapshot can demonstrate pin/select/report reproducibility, but two intentionally selected items over roughly one day do not establish independent item/regime coverage. The old 30-item historical replay result has no new verified immutable manifest and is not fresh held-out evidence. Issue #20's empirical gate stays open until adequate independently chosen market-only coverage and its provenance are available. This tooling does not manufacture missing history or monitor indefinitely.

## Verification and review

Synthetic contracts check deterministic reports, write-once destinations, corrupt bytes, invalid provenance/metadata/conflicting candles, chronological boundaries, manifest/selection tampering, and unchanged selection when only holdout data changes. Real subprocess CLI checks run with a disposable HOME, produce clean JSON and fail clearly on corruption without creating owner configuration.

Scoped Sonnet review `20261012T145806Z-6cac5650` examined the complete new dataset/test files and the replay extraction diff in one generation (47.30 seconds, 7260 input/2227 output tokens), without retry or fallback. Native triage:

- `replay.asdict` absence claim: false; the actual module imports it and the real CLI test passed on local Python and production Python 3.11. The test now imports `dataclasses.asdict` directly to avoid an incidental module dependency.
- Metadata-boundary coverage: existing replay fixtures covered several invalid cases; added direct subtests for canonical IDs, root types, membership, buy-limit engineering boundaries and bounded names.
- Initial size check allegedly dead: false; it rejects oversized regular files before reading them. Native inspection identified the real concurrent-growth concern and replaced these dataset reads with a bounded binary read, preserving both the size cap and clear corruption handling.

The pinned Wiki smoke reports identical byte-for-byte reruns, dataset `f25b109f554d70043ba595216a74682b12663128716c6c7c864b4ada2aef6492` and selection `5e3b83b993f92c586ca20ef6353f6c1e6c8bb18cdf803a97ef0c7de1bb0f199c`. Holdout has 92 candles per item and zero realized collections for both selected configuration and baseline. These zero-sample results establish command reproducibility only; they provide no strategy superiority evidence.

Full release evidence is recorded with the implementation PR. Dataset tooling adds no persistent application schema, financial migration, runtime account capability change or production retune.
