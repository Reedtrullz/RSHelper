# Comparable scan snapshots

Daily snapshots include a version-1 manifest with effective scan settings,
SHA-256 of canonical JSON settings, units, selection limits and endpoint market
provenance. CLI overrides are recorded rather than inferred from the config file.
The existing full top-N selection is preserved for alch, flip and process scans:
their name filter narrows the display. Margin applies its name filter before
history acquisition, so that filter is part of its saved specification.

`diff` reports one of three comparison states before displaying numerical changes:

`diff flip --date 2026-10-01 --json` returns the same comparison reasons as pure
JSON. Processing specifications additionally fingerprint the complete recipe
model and account context, and explicitly label their units illustrative.
Changed recipe/account assumptions are incompatible; even matching illustrative
models remain partially comparable.

- Compatible: matching complete specifications and fresh, known source/volume
  quality/coverage. This compares observations; it does not prove strategy gains.
- Partially comparable: legacy or incomplete settings, unknown/stale provenance,
  or changed source/volume quality/coverage. Numerical differences are qualified.
- Incompatible: changed settings/units/direction/capital/truncation, unsupported
  manifest versions, or invalid fingerprints. Improvement/regression lists are
  withheld. Changing a manifest cannot make an altered specification comparable
  without also supplying its exact hash.

Missing items retain their old values with an unknown removal reason; no zero
profit is substituted. Legacy files are read without migration or byte changes.
Calls that omit the new optional settings retain a manifest with null settings:
null explicitly means provenance unknown. History summary consumers receive the
manifest and comparison qualification. Daily filenames/retention stay unchanged.

Local acceptance on 12 October 2026: all combined975 offline tests passed across
71 files with four explicit provider skips. Seven focused manifest cases include
actual CLI JSON qualification, model changes and byte-preserving rejection.
Browser authentication and 19 view scenarios passed. Actual Wiki CLI runs saved
and parsed three results each for alch, flip, process and margin snapshots.
An actual owned CLI invocation parsed the incompatible changed-capital comparison.

A bounded Sonnet diff review was triaged: null sentinels are documented;
strict version rejection is intentional; argparse supplies typed integers;
latest-price provenance has no executed-volume claim; sorted removed IDs replace
undefined ordering. The hash-reason assertion and non-finite preservation case
were added. These are local checks; signed commit, CI, deployment and runtime
handoff acceptance remain pending.
