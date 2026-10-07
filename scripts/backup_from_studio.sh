#!/bin/bash
# Runs on the laptop. Pulls an off-machine copy of the irreplaceable data from the Mac Studio and
# raises a macOS notification if the Studio's collector is unhealthy or unreachable.
#
# Copied: raw/, universe/, state/ and a consistent snapshot of the paper-trading database.
# processed/ is rebuilt from raw/. No --delete, so a file lost on the Studio is never removed here.
set -uo pipefail

HOST="${COPY_TRADER_HOST:-admin@100.88.239.107}"
KEY="$HOME/.ssh/mac_studio_ed25519"
DEST="$HOME/data/copy-trader-backup"
SSH="ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=15"

notify() {
  osascript -e "display notification \"$1\" with title \"copy-trader\" sound name \"Basso\"" || true
}

echo "== $(date -u +%FT%TZ) backup"
mkdir -p "$DEST"
# The paper-trading database is written continuously: take a consistent SQLite snapshot first.
$SSH "$HOST" 'db=~/data/copy-trader/papertrade/papertrade.db; [ -f "$db" ] && sqlite3 "$db" ".backup $HOME/data/copy-trader/papertrade/snapshot.db" || true'
if ! rsync -az -e "$SSH" --exclude '*.lock' --include 'raw/***' --include 'universe/***' --include 'state/***' \
     --include 'papertrade/' --include 'papertrade/snapshot.db' \
     --exclude '*' "$HOST:data/copy-trader/" "$DEST/"; then
  notify "Backup failed: Mac Studio unreachable?"
  exit 1
fi
du -sh "$DEST"

report="$($SSH "$HOST" '~/.local/bin/copy-trader health' 2>&1)"
status=$?
echo "$report"
if [ $status -ne 0 ]; then
  notify "Collector unhealthy: $(echo "$report" | grep -m1 FAIL)"
fi
