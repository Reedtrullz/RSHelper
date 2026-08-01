#!/usr/bin/env bash
# Install the RSHelper paper trader as a user LaunchAgent so it runs
# continuously on this Mac (paper-only; no real GP).
#
# Usage:
#   scripts/install-trader-launchd.sh install   # write plist + load
#   scripts/install-trader-launchd.sh uninstall # unload + remove plist
#   scripts/install-trader-launchd.sh status    # show launchctl state
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.reidar.rshelper-trader"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/rshelper"
VENV_PY="$REPO_DIR/.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
  echo "error: venv python not found at $VENV_PY" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

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

case "${1:-install}" in
  install)
    write_plist
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "Installed and started $LABEL"
    echo "  plist: $PLIST"
    echo "  logs:  $LOG_DIR/trader.{out,err}.log"
    ;;
  uninstall)
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Uninstalled $LABEL"
    ;;
  status)
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null || echo "not loaded"
    ;;
  *)
    echo "usage: $0 [install|uninstall|status]" >&2
    exit 1
    ;;
esac
