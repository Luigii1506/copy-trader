#!/bin/bash
# Installs the backup + health-alert job on the laptop (every 3h while it is awake, and at login).
# The script is copied out of ~/Documents because launchd can't read that folder without Full Disk Access.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HOME/.local/bin/copy-trader-backup"
LABEL="com.luisencinas.copytrader.backup"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/data/copy-trader-backup.log"

mkdir -p "$(dirname "$BIN")" "$HOME/data"
install -m 755 "$REPO/scripts/backup_from_studio.sh" "$BIN"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key><array><string>$BIN</string></array>
    <key>StartInterval</key><integer>10800</integer>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>$LOG</string>
    <key>StandardErrorPath</key><string>$LOG</string>
    <key>ProcessType</key><string>Background</string>
    <key>Nice</key><integer>10</integer>
    <key>LowPriorityIO</key><true/>
</dict>
</plist>
PLIST
# bootout is asynchronous: wait until a running job has actually exited before re-registering it.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
for _ in $(seq 30); do launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break; sleep 1; done
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL -> $BIN (log: $LOG)"
