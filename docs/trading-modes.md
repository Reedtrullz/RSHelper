# Durable paper entry controls

`trading-mode --json` reports the current profile's stance separately from the
trader process status. `running` permits new paper entries, `entries-paused`
blocks entries, and `draining` blocks entries while ordinary exits continue.
Drain completion is recorded when positions are empty. Resuming always requires
an explicit change to `running`; restarting a process does not resume entries.

Read the current revision, then supply it, a reason, and a fresh UUID:

```sh
PYTHONPATH=src .venv/bin/python -m rshelper trading-mode --json
PYTHONPATH=src .venv/bin/python -m rshelper trading-mode \
  --mode entries-paused --expected-revision 0 \
  --reason 'Operator review' --operation-id '<fresh UUID>' --json
```

Use the same complete request and UUID after an uncertain response. A committed
retry returns the current stance plus the original operation revision; it cannot
rewind a later resume. A stale new request fails and requires another status read.
The receipt inventory retains the most recent128 operator changes. An older
evicted request fails its revision check rather than replaying an old change.

Mode publication and position opening share the profile transaction lock. After
pause acknowledgment, a new entry cannot publish. Exits and retries of already
published entries remain available. Activated profiles require financial
authority to change stance. The Mac publishes its stance to the VPS replica;
the replica displays it and cannot declare drain completion or resume entries.
Existing dashboard controls expose these changes only when `--control` is
enabled. Production VPS controls remain disabled.

`trading_mode.json` belongs to the private backup and packet inventories. Legacy
profiles retain their stance when explicit migration binds it to the approved
authority. Restore rejects a backup that would rewind an acknowledged stance.
Unknown or corrupt mode state fails closed. A missing file means the legacy
running default; no synthetic revision-zero record is persisted.

Before upgrading, capture and inspect a coherent private backup, quiesce owned
jobs, deploy the compatible image, and resume the upgraded Mac jobs. Verify the
current stance, daemon health, and exact private receipt separately. During code
rollback, keep financial writers quiesced: older builds preserve the file during
readback but do not enforce this new entry guard. Never restore an older financial
backup over later writes to make an old build run. A compatible current build can
recover transactions and preserve the operator's last stance.

Local acceptance on12 October2026:921 tests across66 files, four explicit offline
provider skips, zero failures/errors; both Node suites,16 view contracts, actual
synthetic HTTP pause/retry/blocked-entry/resume with Wiki network data, and a
Python3.11 Docker migration/backup/restore/private-packet rehearsal passed.
Old/new/old/new readback preserved the mode hash and existing position. The
financial-writer rollback restriction above is part of that acceptance.

Native review fixed legacy authority binding and backup rewind. Three bounded
Anti Sonnet scopes completed. Proposed defects in the in-memory default, drain
receipt, newest retained operation, activation schema, and authority guard were
refuted against the typed source and executed migration/drain/receipt tests;
comma spacing is not a parse defect. Unset trader status retains its prior `None`
contract, and replicas do not publish local completion. Physical owner trials
and production mode acceptance remain separate from these synthetic checks.
