#!/bin/zsh
# Argus v2 watchdog — runs from cron every 5 min on Agent 1.
# Alerts Mike's Telegram chat if the system dies. Alerts once per outage
# (state file), sends an all-clear on recovery.
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin

ARGUS=~/argus_v2
STATE=/tmp/argus_v2_watchdog_state
PROBLEMS=""

TOKEN=$(grep '^TELEGRAM_BOT_TOKEN' $ARGUS/.env | cut -d= -f2-)
CHAT=$(grep '^TELEGRAM_CHAT_ID' $ARGUS/.env | cut -d= -f2-)

# 1. All four tmux windows alive
WINDOWS=$(tmux list-windows -t argus_v2 2>/dev/null | wc -l | tr -d ' ')
if [ "$WINDOWS" != "4" ]; then
  PROBLEMS="tmux windows: $WINDOWS/4 alive."
fi

# 2. Executor API responding
MASTER=$(grep '^MASTER_KEY' $ARGUS/.env | cut -d= -f2-)
HTTP=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $MASTER" http://localhost:8002/status)
if [ "$HTTP" != "200" ]; then
  PROBLEMS="$PROBLEMS Executor /status returned $HTTP."
fi

# 3. Analyst still writing (DB touched within 45 min — scans run every 5-15 min)
if [ -f "$ARGUS/data/argus.db" ]; then
  AGE=$(( $(date +%s) - $(stat -f %m "$ARGUS/data/argus.db") ))
  if [ "$AGE" -gt 2700 ]; then
    PROBLEMS="$PROBLEMS Analyst silent: DB last written $((AGE/60)) min ago."
  fi
else
  PROBLEMS="$PROBLEMS Database missing."
fi

notify() {
  curl -s -m 10 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="${CHAT}" -d text="$1" > /dev/null
}

if [ -n "$PROBLEMS" ]; then
  # Alert once per outage, not every 5 minutes
  if [ ! -f "$STATE" ]; then
    touch "$STATE"
    notify "🚨 ARGUS V2 WATCHDOG: $PROBLEMS Restart: ssh agent1, then zsh ~/argus_v2/start_argus.sh"
  fi
else
  if [ -f "$STATE" ]; then
    rm -f "$STATE"
    notify "✅ Argus v2 watchdog: system healthy again."
  fi
fi

# Heartbeat — proves the watchdog itself is alive (a silent watchdog is
# indistinguishable from a dead one, which is how the cron version failed)
echo "$(date '+%Y-%m-%d %H:%M:%S') windows=$WINDOWS http=$HTTP problems=${PROBLEMS:-none}" > /tmp/argus_v2_watchdog_last
