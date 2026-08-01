# RSHelper Deployed State

This directory holds a copy of the local RSHelper trading state that gets
seeded into the live site's state volume on every deploy:

- `trades.json` — paper trade journal (the live Paper Trading history)
- `positions.json` — open paper positions (buy-and-hold until closed)
- `watchlist.json` — watched items and alert thresholds
- `tuning_log.json` — config-change eras for the Progression view
- `volume_baseline.json` / `signal_cooldowns.json` — signal state
- `snapshots/` — daily scan snapshots

## Flow

1. Trade locally as usual (the journal stays in `~/.config/rshelper/`).
2. Run `scripts/sync-state.sh` to copy the current state here.
3. Commit `data/state` and push to `main`.
4. The Ansible deploy task copies this directory into
   `/opt/apps/rshelper/data/.config/rshelper` on the VPS before the
   container starts, so `rs.reidar.tech` serves the same history.

The copy is additive: files removed locally are not deleted from the
deployed volume, so history persists across syncs.

`config.toml` and `active_profile` are intentionally not synced — the VPS
keeps its own config defaults.
