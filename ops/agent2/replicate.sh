#!/bin/zsh
# Argus replica — runs on AGENT 2 every 10 min via launchd (com.argus.replica).
# Protects the crown jewel: the track-record database. Uses sqlite's .backup
# (consistent snapshot of a live DB — never a raw file copy), pulls it over,
# verifies integrity, then rotates: latest + one dated daily, 7 days retained.
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin

DEST=~/argus_replica
mkdir -p "$DEST"

run_remote() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 agent1 "$1" 2>/dev/null \
    || ssh -o BatchMode=yes -o ConnectTimeout=8 agent1-lan "$1" 2>/dev/null
}

# Consistent snapshot on agent1, then pull it
run_remote "sqlite3 ~/argus_v2/data/argus.db \".backup /tmp/argus_snapshot.db\"" || exit 0
scp -q -o BatchMode=yes -o ConnectTimeout=8 agent1:/tmp/argus_snapshot.db "$DEST/incoming.db" 2>/dev/null \
  || scp -q -o BatchMode=yes -o ConnectTimeout=8 agent1-lan:/tmp/argus_snapshot.db "$DEST/incoming.db" 2>/dev/null \
  || exit 0

# Verify before promoting — a corrupt replica is worse than a stale one
OK=$(sqlite3 "$DEST/incoming.db" "PRAGMA integrity_check;" 2>/dev/null)
SIGNALS=$(sqlite3 "$DEST/incoming.db" "SELECT COUNT(*) FROM signals;" 2>/dev/null)
if [ "$OK" = "ok" ] && [ -n "$SIGNALS" ] && [ "$SIGNALS" -gt 0 ]; then
  mv "$DEST/incoming.db" "$DEST/argus-latest.db"
  cp "$DEST/argus-latest.db" "$DEST/argus-$(date +%Y%m%d).db"
  ls -t "$DEST"/argus-2*.db 2>/dev/null | tail -n +8 | xargs rm -f 2>/dev/null
  echo "$(date '+%Y-%m-%d %H:%M:%S') replicated ok signals=$SIGNALS" > "$DEST/last"
else
  rm -f "$DEST/incoming.db"
  echo "$(date '+%Y-%m-%d %H:%M:%S') REJECTED integrity=$OK signals=$SIGNALS" > "$DEST/last"
fi
