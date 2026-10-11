# RSHelper Deployed State

Before the reviewed private-channel transition, this directory holds the legacy
copy of local RSHelper trading state used to seed an inactive deployed profile:

- `trades.json` — paper trade journal (the live Paper Trading history)
- `positions.json` — open paper positions (buy-and-hold until closed)
- `watchlist.json` — watched items and alert thresholds
- `tuning_log.json` — config-change eras for the Progression view
- `volume_baseline.json` / `signal_cooldowns.json` — signal state
- `snapshots/` — daily scan snapshots

## Flow

1. Trade locally as usual (the journal stays in `~/.config/rshelper/`).
2. Run `scripts/sync-state.sh` for coherent locked capture and transactional copy here.
3. Commit `data/state` and push to `main`.
4. The Ansible deploy task copies this directory into
   `/opt/apps/rshelper/data/.config/rshelper` on the VPS before the
   container starts, so `rs.reidar.tech` serves the same history.

The copy is additive: files removed locally are not deleted from the
deployed volume, so history persists across syncs.

`config.toml` and `active_profile` are intentionally not synced — the VPS
keeps its own config defaults.

This repository is public. Owner HTTP authentication does not remove published
copies or existing Git history. Identified profiles refuse raw Git publication
and skip this seed; they require the authenticated private packet channel and
exact applied receipt. The owner must approve the public field policy and the
existing-feed transition first. See [the coordinated state runbook](../../docs/execution/coordinated-state-runbook.md).
