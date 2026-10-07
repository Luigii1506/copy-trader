#!/bin/bash
# Installs the collector as a uv tool (outside ~/Documents, which launchd can't read without
# Full Disk Access) and registers its launchd jobs. Re-run after changing collector code.
#
# Schedule (local time), chosen to stay clear of brain-ops at 06:00 and 22:00:
#   leaderboard  every hour       checks for a new leaderboard version; stores at most one per 6h
#   wallets      02:30 08:30 14:30 18:30
#   normalize    04:15 19:45      raw JSON -> Parquet
#   census       manual           one-off equity-history census (launchctl kickstart ...census)
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

schedule() {  # "manual", "every=SECONDS" or "HH:MM HH:MM ..." -> launchd schedule keys
  if [[ "$1" == manual ]]; then
    return  # no schedule: started with launchctl kickstart
  fi
  if [[ "$1" == every=* ]]; then
    echo "    <key>StartInterval</key><integer>${1#every=}</integer>"
    return
  fi
  echo "    <key>StartCalendarInterval</key>"
  echo "    <array>"
  for t in "$@"; do
    echo "        <dict><key>Hour</key><integer>$((10#${t%:*}))</integer><key>Minute</key><integer>$((10#${t#*:}))</integer></dict>"
  done
  echo "    </array>"
}

# Share of the 1200/min API weight limit per job. Jobs can overlap, so the shares must add up
# to less than 1200 (leaderboard and normalize don't use the weighted API).
weight() { case "$1" in wallets) echo 500 ;; census) echo 650 ;; *) echo 100 ;; esac; }

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
$(schedule "$@")
    <key>EnvironmentVariables</key>
    <dict>
        <key>COPY_TRADER_DATA</key><string>$DATA</string>
        <key>COPY_TRADER_WEIGHT_PER_MINUTE</key><string>$(weight "$job")</string>
    </dict>
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
  # bootout is asynchronous: wait until a running job has actually exited before re-registering it.
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  for _ in $(seq 30); do launchctl print "gui/$UID_NUM/$label" >/dev/null 2>&1 || break; sleep 1; done
  launchctl bootstrap "gui/$UID_NUM" "$plist"
  echo "installed $label ($*)"
}

install_job leaderboard every=3600
install_job wallets 02:30 08:30 14:30 18:30
install_job normalize 04:15 19:45
install_job census manual

echo "binary: $BIN"
echo "data:   $DATA"
echo "run now: launchctl kickstart gui/$UID_NUM/com.luisencinas.copytrader.<job>"
