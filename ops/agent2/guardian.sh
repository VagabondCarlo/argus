#!/bin/zsh
# Argus guardian — runs on AGENT 2 every 5 min via launchd (com.argus.guardian).
# External supervisor for Agent 1: catches what Agent 1's own watchdog cannot —
# total machine failure (power, kernel panic, network death) and outages its
# self-recovery fails to fix.
#
# Escalation ladder (each step gets a chance before the next):
#   unhealthy x1        -> silent (Agent 1's own watchdog restarts within 5 min)
#   unhealthy x2 (10m)  -> guardian remote-restarts the stack over SSH + notifies
#   unreachable x3 (15m)-> notifies Mike: machine-level failure, replica is safe
# Recovery clears all state and sends an all-clear.
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin

source ~/.argus_guardian.env
STATE_DIR=/tmp/argus_guardian
mkdir -p "$STATE_DIR"

notify() {
  curl -s -m 10 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" -d text="$1" > /dev/null
}

bump() {  # bump <counter-file> -> echoes new count
  local f="$STATE_DIR/$1" n
  n=$(( $(cat "$f" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$f"; echo "$n"
}

clear_state() {
  # explicit names — zsh aborts on unmatched globs
  rm -f "$STATE_DIR/unreach" "$STATE_DIR/unhealthy" \
        "$STATE_DIR/notified_unreach" "$STATE_DIR/notified_unhealthy"
}

# ── Probe Agent 1 (tailscale, then LAN fallback) ────────────────────────────
HEALTH=$(ssh -o BatchMode=yes -o ConnectTimeout=8 agent1 \
  'W=$(/opt/homebrew/bin/tmux list-windows -t argus_v2 2>/dev/null | wc -l | tr -d " "); A=$(( $(date +%s) - $(stat -f %m ~/argus_v2/data/argus.db 2>/dev/null || echo 0) )); echo "$W $A"' 2>/dev/null)
if [ -z "$HEALTH" ]; then
  HEALTH=$(ssh -o BatchMode=yes -o ConnectTimeout=8 agent1-lan \
    'W=$(/opt/homebrew/bin/tmux list-windows -t argus_v2 2>/dev/null | wc -l | tr -d " "); A=$(( $(date +%s) - $(stat -f %m ~/argus_v2/data/argus.db 2>/dev/null || echo 0) )); echo "$W $A"' 2>/dev/null)
fi

if [ -z "$HEALTH" ]; then
  # ── Agent 1 unreachable on BOTH routes ──
  N=$(bump unreach)
  rm -f "$STATE_DIR/unhealthy"
  if [ "$N" -ge 3 ] && [ ! -f "$STATE_DIR/notified_unreach" ]; then
    touch "$STATE_DIR/notified_unreach"
    REPLICA_AGE="unknown"
    [ -f ~/argus_replica/argus-latest.db ] && REPLICA_AGE="$(( ( $(date +%s) - $(stat -f %m ~/argus_replica/argus-latest.db) ) / 60 )) min old"
    notify "🚨 GUARDIAN (Agent 2): Agent 1 unreachable for 15+ min on tailscale AND LAN — possible power/network/machine failure. Trading is DOWN. Track-record replica on Agent 2 is ${REPLICA_AGE}. Warm standby ready: ssh agent2, zsh ~/argus_v2/takeover.sh (manual GO only — never run while Agent 1 might still be trading)."
  fi
  echo "$(date '+%Y-%m-%d %H:%M:%S') agent1=UNREACHABLE count=$N" > "$STATE_DIR/last"
  exit 0
fi

rm -f "$STATE_DIR/unreach" "$STATE_DIR/notified_unreach"
WINDOWS=${HEALTH%% *}
DB_AGE=${HEALTH##* }

if [ "$WINDOWS" != "4" ] || [ "$DB_AGE" -gt 2700 ]; then
  # ── Reachable but unhealthy ──
  N=$(bump unhealthy)
  if [ "$N" -ge 2 ]; then
    # Agent 1's own watchdog had its 5-min window and didn't fix it — we act.
    ssh -o BatchMode=yes -o ConnectTimeout=8 agent1 'zsh ~/argus_v2/start_argus.sh' >/dev/null 2>&1 \
      || ssh -o BatchMode=yes -o ConnectTimeout=8 agent1-lan 'zsh ~/argus_v2/start_argus.sh' >/dev/null 2>&1
    if [ ! -f "$STATE_DIR/notified_unhealthy" ]; then
      touch "$STATE_DIR/notified_unhealthy"
      notify "🔧 GUARDIAN (Agent 2): Agent 1 unhealthy (windows=$WINDOWS, db_age=${DB_AGE}s) and its own watchdog didn't recover it — I restarted the stack remotely. Will confirm next check."
    fi
    echo 0 > "$STATE_DIR/unhealthy"
  fi
  echo "$(date '+%Y-%m-%d %H:%M:%S') agent1=UNHEALTHY windows=$WINDOWS db_age=$DB_AGE" > "$STATE_DIR/last"
else
  # ── Healthy ──
  if [ -f "$STATE_DIR/notified_unreach" ] || [ -f "$STATE_DIR/notified_unhealthy" ]; then
    notify "✅ GUARDIAN (Agent 2): Agent 1 back to healthy."
  fi
  clear_state
  echo "$(date '+%Y-%m-%d %H:%M:%S') agent1=HEALTHY windows=$WINDOWS db_age=$DB_AGE" > "$STATE_DIR/last"
fi
