#!/usr/bin/env bash
# Sync local RSHelper trading state into data/state so the deploy pipeline
# can seed the live site's state volume with the same journal.
#
# Usage: scripts/sync-state.sh
#   Override the source config dir with RSHELPER_CONFIG_DIR if needed.
#
# After running, commit data/state and push to deploy the history.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${RSHELPER_CONFIG_DIR:-$HOME/.config/rshelper}"
DEST="$REPO_DIR/data/state"

FILES=(trades.json positions.json watchlist.json tuning_log.json volume_baseline.json signal_cooldowns.json trader_state.json alerts.json)
mkdir -p "$DEST" "$DEST/snapshots"

changed=0
for f in "${FILES[@]}"; do
  if [ -f "$SRC/$f" ]; then
    cp "$SRC/$f" "$DEST/$f"
    changed=$((changed + 1))
  fi
done

if [ -d "$SRC/snapshots" ] && [ -n "$(ls -A "$SRC/snapshots" 2>/dev/null)" ]; then
  cp -R "$SRC/snapshots/." "$DEST/snapshots/"
  changed=$((changed + 1))
fi

echo "Synced $changed state file groups from $SRC to $DEST"
echo "Commit and push to deploy it:"
echo "  git add data/state && git commit -m 'state: sync trading history' && git push"
