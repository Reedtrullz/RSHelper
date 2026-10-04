# Bug Report: Anti sidecar — panel review reliability

**Reported:** 2026-07-31 · **Reporter:** Reidar's Codex session (RSHelper
project) · **Handoff target:** the agent building/maintaining Anti
(`codex-antigravity-auth` helper).

## Executive summary

The `$anti` sidecar helper is used for deep code reviews and design panels
on a local gateway. Three of three panel runs this session degraded in the
same ways: the **Opus lane did not produce a review** (once it asked for
direction, once it produced no output at all), the **judge's structured
findings JSON was malformed/truncated every time** (the same failure also
occurred on 2026-07-07), and **lane outputs were cut off mid-sentence at
exactly 2048 output tokens**. The helper falls back to prose and continues,
so the workflow survives — but findings are silently lost ("25+ defects"
claimed, only 5 delivered), there is never cross-lane corroboration, and
`panel --json` output is not schema-stable. The single most likely root
cause across all four bugs is the default output-token cap truncating lane
and judge responses, combined with the absence of lane validation and
judge-JSON repair/retry.

## Environment

- Helper: `python3 ~/.codex/skills/anti/scripts/anti.py` (V2 CLI)
- Gateway: `codex-antigravity` CLI v1.7.0 at `http://127.0.0.1:51122/v1`
  (sidecar mode; gateway advertises 15 models)
- Models in panels: `claude-3.5-sonnet`, `claude-opus-4-6`; judge: opus
- Host: macOS, Python 3.10 for the gateway, helper invoked via `anti.py`
- Repo context: `RSHelper` (stdlib-only Python), 13 source files reviewed,
  `--chunked auto`, `--output findings`, `--json` used on panels

## Evidence base

Observations are from three panel runs on 2026-07-31 (commands below) plus
one saved run from 2026-07-07 in `~/.codex/anti-runs/`. Today's primitive
commands saved no artifacts (`--save-output never` default), so quotes are
from captured stdout/stderr.

- Panel A (19:56): `panel --mode review --scope files --prompt-file ...`
  over 13 files, `--model sonnet --model opus --judge opus --output
  findings --json --chunked auto --max-review-chunks 8`
- Panel B (19:56): `panel --mode ask --prompt-file <GUI design brief>
  --model sonnet --model opus --judge opus`
- Panel C (21:50): same shape as Panel A (audit prompt)
- Review: `review --model sonnet --scope diff --base origin/main
  --chunked auto` (twice)

---

## Bug 1 — Opus panel lane does not deliver a review (High)

### Observed

- **Panel A**: the Opus lane returned a non-answer:
  > "The review summary appears to be truncated mid-entry (C-13 cuts off at
  > `_set_cooldown`), and no task has been specified yet. I have the bounded
  > context loaded. **What would you like me to do with it?**"
  It asked for direction instead of reviewing; the panel proceeded and the
  judge synthesized from the other lane's findings anyway.
- **Panel C**: the judge's own summary reported "Only claude-3.5-sonnet
  chunk outputs were available; claude-opus-4-6 panel output is absent, so
  all findings lack cross-lane corroboration." The Opus lane produced no
  output, and no failed lane was recorded (the prior saved artifact from
  July 7 shows the same shape: `failed_models: []` while a lane silently
  contributed nothing).
- **Panel B**: Opus reported success (`out 2048` tokens) but its output was
  truncated mid-sentence ("claude-opus-4-6 cuts off in §2d row hover").

### Impact

The "deep review" lanes are effectively single-model. No cross-lane
corroboration exists, which the helper itself flags as a quality gap. The
run ledger records these lanes as successful rather than failed.

### Root-cause hypotheses

1. The lane prompt is a truncated bounded summary (see Bug 4), which Opus
   interprets as an incomplete task rather than a review brief.
2. No validation of lane output: a non-answer or empty response is accepted
   as a successful lane.

### Expected behavior

- A lane that returns a non-answer, empty output, or truncated output is
  recorded in `failed_models` and either retried once (with a repaired or
  shorter prompt) or excluded from the judge synthesis with a visible
  warning.
- The panel summary states per-lane outcome (answered / truncated /
  absent) instead of "success".

---

## Bug 2 — Judge structured-findings JSON is always malformed; findings are lost (High)

### Observed

Every panel run produced the same helper caveat:

- Panel A: `Expecting ',' delimiter: line 120 column 6 (char 11567)`
- Panel C: `Expecting ',' delimiter: line 118 column 6 (char 9555)`
- 2026-07-07 (saved run `20260707T144707Z-720d9ab5.json`): `Expecting ','
  delimiter: line 43 column 6 (char 4131)`

Consequence in Panel C: the judge summary claimed "25+ concrete defects
across 12 files" but the structured findings array in the saved output
contains only **5 findings** — everything after the JSON break is lost.
The helper's fallback is prose, but it is the judge's *truncated* prose, so
the missing findings never reach the caller.

### Root-cause hypothesis

The judge's response is cut off by the output-token cap mid-JSON (same cap
as Bug 4). The helper catches the parse error (good) but does not repair,
cap the requested output, or retry, and it does not warn that findings were
dropped.

### Expected behavior

- Request bounded JSON from the judge (fewer findings, explicit
  `max_output_tokens` headroom).
- On parse failure: attempt a repair pass (e.g., truncate at the last
  complete object/array) or retry once with "output ONLY valid JSON, no
  prose, no code fence".
- Surface a `findings_dropped` / `parse_warning` field with a count so
  callers know the artifact is incomplete.

---

## Bug 3 — `panel --json` output schema is not stable (Medium)

### Observed

- Panel A emitted keys: `caveats, findings, gateway, judge_model,
  metadata, mode, output_text, panel_mode, panel_models, panel_results`
  (per-lane outputs present).
- Panel C emitted keys: `caveats, disagreements, findings,
  recommended_next_actions, summary, unverifiable` — no
  `panel_results` / `panel_models` / `judge_model` / `output_text`; the
  `findings` and `recommended_next_actions` arrays are empty, and the real
  content lives inside `summary` as a string containing a broken JSON blob
  wrapped in a markdown code fence.

### Impact

Automation cannot rely on a stable schema. Consumers must locate a broken
JSON string embedded in prose and partially parse it.

### Expected behavior

- Always emit the same top-level keys for the same command/mode.
- Never embed content as a JSON string inside `summary`; emit findings as a
  real array (empty with a caveat when the judge failed).

---

## Bug 4 — Lane outputs truncated at the output-token cap, silently (High, contributes to Bugs 1-2)

### Observed

- Panel B: both lanes ended at **exactly 2048 output tokens**
  (`sonnet: out 2048, total 2740`; `opus: out 2048, total 2740`), and both
  were truncated mid-sentence per the judge's caveats:
  > "claude-3.5-sonnet cuts off in §3 detail panel metrics,
  > claude-opus-4-6 cuts off in §2d row hover. Sections 4-7 of the original
  > brief ... received no coverage from either model."
- Panel A/C included the caveat "Prompt truncated to 30000 characters" and
  "Panel review used a bounded chunked summary instead of sending the full
  raw review context to every lane."

### Impact

Deep reviews lose their later sections (the judge in Panel C explicitly
blamed missing coverage on truncation). The helper still reports the lanes
as `success`.

### Expected behavior

- Default output-token budget for deep reviews should be much larger than
  2048 (or auto-scaled to the review/panel mode).
- A lane that hits the cap is marked truncated/incomplete and, at minimum,
  the run summary says so; optionally the lane is re-asked to continue from
  where it stopped.

---

## Bug 5 — Review scope handling: truncation vs "complete", empty-staged confusion (Low)

### Observed

- `review --scope diff --base origin/main` on a 78,527-char diff included
  only 28,944 chars ("Git diff truncated to fit max prompt budget (78527
  original chars, 28944 included)"), yet the same run's report opened with
  "Coverage: All 3 chunks reviewed; no omitted items" — conflicting claims
  of completeness and truncation in one artifact.
- `review --scope staged` with nothing staged returned "## Review Result:
  No Content Available — The manifest reports `included_files: none` with
  an empty s..." instead of a clear "no staged changes" error.

### Expected behavior

- The coverage/status line must reflect truncation (e.g., "truncated: N
  chars of M included").
- Empty staged scope should produce an explicit, actionable error.

---

## Reproducers

Each run consumes gateway quota; keep them bounded.

```bash
# 1. Opus lane non-answer / absent + judge JSON failure
python3 ~/.codex/skills/anti/scripts/anti.py panel --mode review \
  --scope files --file src/rshelper/scanner.py --file src/rshelper/api.py \
  --model sonnet --model opus --judge opus --output findings --json \
  --chunked auto --max-review-chunks 4 \
  --prompt "Review these two files for correctness."

# 2. Lane truncation at 2048 output tokens
python3 ~/.codex/skills/anti/scripts/anti.py panel --mode ask \
  --prompt-file /tmp/large-brief.txt --model sonnet --model opus --judge opus

# 3. Diff truncation caveat
python3 ~/.codex/skills/anti/scripts/anti.py review --model sonnet \
  --scope diff --base origin/main --chunked auto
```

Expected: Bug 1 (opus lane non-answer/absent), Bug 2 (`Expecting ','
delimiter` in caveats, empty `findings`), Bug 3 (schema drift), Bug 4 (both
lanes `out 2048`, truncated prose).

## Suggested fix order

1. **Raise/scale the output-token cap** for panel lanes and the judge in
   review/panel modes (addresses Bugs 2 and 4 at the root).
2. **Validate lanes**: non-answer or empty/truncated lanes go to
   `failed_models`, with one bounded retry and explicit per-lane status.
3. **Repair or retry judge JSON** before falling back; when the fallback is
   used, warn with a count of dropped findings.
4. **Stabilize the `panel --json` schema** (fixed keys, real arrays).
5. **Make coverage claims honest** in `review` (truncation-aware status;
   clear empty-scope error).

## What works (baseline to preserve)

- `smoke` and gateway readiness checks.
- Sonnet lanes produce usable findings; prose fallback retained most
  content in two of three panels.
- The diff reviews caught real defects, and per-chunk progress logging is
  useful.
- Run ledger + `runs` commands work; today's runs just didn't save
  artifacts because primitive commands default to `--save-output never`.
