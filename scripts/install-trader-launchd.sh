#!/usr/bin/env bash
# Install the RSHelper paper trader and its state sync as user LaunchAgents.
# The trader runs continuously (paper-only; no real GP); the sync agent
# pushes new trading state to the repo every SYNC_INTERVAL seconds so the
# live site tracks the Mac trader.
#
# Usage:
#   scripts/install-trader-launchd.sh install   # write plists + load
#   scripts/install-trader-launchd.sh uninstall # unload + remove plists
#   scripts/install-trader-launchd.sh status    # show launchctl state
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.reidar.rshelper-trader"
SYNC_LABEL="com.reidar.rshelper-state-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SYNC_PLIST="$HOME/Library/LaunchAgents/$SYNC_LABEL.plist"
LOG_DIR="$HOME/Library/Logs/rshelper"
VENV_PY="$REPO_DIR/.venv/bin/python"
SYNC_SCRIPT="$HOME/.config/rshelper/bin/sync-and-push-state.py"
SYNC_INTERVAL="${SYNC_INTERVAL:-900}"  # 15 min default

if [ ! -x "$VENV_PY" ]; then
  echo "error: venv python not found at $VENV_PY" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

# The repo lives under ~/Documents, which macOS TCC blocks for launchd
# jobs; the trader's venv python is allowed (it has been granted access),
# but /bin/bash cannot open scripts there. Stage the sync script outside
# the protected tree and point the LaunchAgent at the staged copy.
if [ ! -x "$SYNC_SCRIPT" ]; then
  mkdir -p "$(dirname "$SYNC_SCRIPT")"
  cp "$REPO_DIR/scripts/sync-and-push-state.py" "$SYNC_SCRIPT"
  chmod +x "$SYNC_SCRIPT"
fi

xml_escape() {
  printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'
}

write_plist() {
  LABEL_X="$(xml_escape "$LABEL")"
  VENV_X="$(xml_escape "$VENV_PY")"
  SRC_X="$(xml_escape "$REPO_DIR/src")"
  DIR_X="$(xml_escape "$REPO_DIR")"
  OUT_X="$(xml_escape "$LOG_DIR/trader.out.log")"
  ERR_X="$(xml_escape "$LOG_DIR/trader.err.log")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL_X</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_X</string>
    <string>-m</string>
    <string>rshelper</string>
    <string>auto-trade</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key><string>$SRC_X</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>WorkingDirectory</key><string>$DIR_X</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
  </dict>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$OUT_X</string>
  <key>StandardErrorPath</key><string>$ERR_X</string>
</dict>
</plist>
EOF
}

write_sync_plist() {
  SYNC_X="$(xml_escape "$SYNC_SCRIPT")"
  VENV_X="$(xml_escape "$VENV_PY")"
  OUT_X="$(xml_escape "$LOG_DIR/sync.out.log")"
  ERR_X="$(xml_escape "$LOG_DIR/sync.err.log")"
  cat > "$SYNC_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$SYNC_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_X</string>
    <string>$SYNC_X</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>RSHELPER_REPO</key><string>$REPO_DIR</string>
  </dict>
  <key>StartInterval</key><integer>$SYNC_INTERVAL</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$OUT_X</string>
  <key>StandardErrorPath</key><string>$ERR_X</string>
</dict>
</plist>
EOF
}

case "${1:-install}" in
  install)
    write_plist
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "Installed and started $LABEL"
    echo "  plist: $PLIST"
    echo "  logs:  $LOG_DIR/trader.{out,err}.log"
    write_sync_plist
    launchctl bootout "gui/$(id -u)" "$SYNC_PLIST" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$SYNC_PLIST"
    echo "Installed state sync $SYNC_LABEL (every ${SYNC_INTERVAL}s)"
    echo "  plist: $SYNC_PLIST"
    echo "  logs:  $LOG_DIR/sync.{out,err}.log"
    ;;
  uninstall)
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    launchctl bootout "gui/$(id -u)" "$SYNC_PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    rm -f "$SYNC_PLIST"
    echo "Uninstalled $LABEL and $SYNC_LABEL"
    ;;
  status)
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null >/dev/null \
      && echo "trader: loaded" || echo "trader: not loaded"
    launchctl print "gui/$(id -u)/$SYNC_LABEL" 2>/dev/null >/dev/null \
      && echo "sync: loaded" || echo "sync: not loaded"
    ;;
  *)
    echo "usage: $0 [install|uninstall|status]" >&2
    exit 1
    ;;
esac
