#!/bin/bash
# Installs the collector as a uv tool (outside ~/Documents, which launchd can't read without
# Full Disk Access) and registers its launchd jobs. Re-run after changing collector code.
#
# Schedule (local time), chosen to stay clear of brain-ops at 06:00 and 22:00:
#   leaderboard  17:05            daily leaderboard snapshot (~00:05 UTC)
#   wallets      02:30 08:30 14:30 18:30
#   normalize    04:15 19:45      raw JSON -> Parquet
# Jobs run at low CPU/IO priority under caffeinate so the Mac doesn't idle-sleep mid-run.
# A Mac that is asleep at a scheduled time runs the job once on wake.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${COPY_TRADER_DATA:-$HOME/data/copy-trader}"
AGENTS="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

uv tool install --reinstall --quiet "$REPO"
BIN="$(command -v copy-trader || echo "$HOME/.local/bin/copy-trader")"
mkdir -p "$DATA/logs" "$AGENTS"

calendar() {  # "HH:MM HH:MM ..." -> StartCalendarInterval entries
  for t in "$@"; do
    echo "        <dict><key>Hour</key><integer>$((10#${t%:*}))</integer><key>Minute</key><integer>$((10#${t#*:}))</integer></dict>"
  done
}

install_job() {
  local job="$1"; shift
  local label="com.luisencinas.copytrader.$job"
  local plist="$AGENTS/$label.plist"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$label</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string><string>-i</string>
        <string>$BIN</string><string>$job</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
$(calendar "$@")
    </array>
    <key>EnvironmentVariables</key>
    <dict><key>COPY_TRADER_DATA</key><string>$DATA</string></dict>
    <key>WorkingDirectory</key><string>$DATA</string>
    <key>StandardOutPath</key><string>$DATA/logs/$job.log</string>
    <key>StandardErrorPath</key><string>$DATA/logs/$job.log</string>
    <key>ProcessType</key><string>Background</string>
    <key>Nice</key><integer>10</integer>
    <key>LowPriorityIO</key><true/>
    <key>RunAtLoad</key><false/>
</dict>
</plist>
EOF
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$plist"
  echo "installed $label ($*)"
}

install_job leaderboard 17:05
install_job wallets 02:30 08:30 14:30 18:30
install_job normalize 04:15 19:45

echo "binary: $BIN"
echo "data:   $DATA"
echo "run now: launchctl kickstart gui/$UID_NUM/com.luisencinas.copytrader.<job>"
