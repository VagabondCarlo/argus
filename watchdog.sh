#!/bin/zsh
# Argus v2 watchdog — runs every 5 min via launchd (com.argus.watchdog).
# ACTIVE SUPERVISOR: detects a down service, restarts the stack itself, and
# tells Mike what it did. Recovery does not depend on SSH or a human being
# present. Escalates only if a restart fails to fix things.
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin

ARGUS=~/argus_v2
STATE=/tmp/argus_v2_watchdog_state          # marks an active (already-alerted) outage
COOLDOWN=/tmp/argus_v2_last_restart          # timestamp of last auto-restart
COOLDOWN_SECS=900                            # don't auto-restart more than once / 15 min
PROBLEMS=""

TOKEN=$(grep '^TELEGRAM_BOT_TOKEN' $ARGUS/.env | cut -d= -f2-)
CHAT=$(grep '^TELEGRAM_CHAT_ID' $ARGUS/.env | cut -d= -f2-)

notify() {
  curl -s -m 10 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="${CHAT}" -d text="$1" > /dev/null
}

# ── Health checks ──────────────────────────────────────────────
WINDOWS=$(tmux list-windows -t argus_v2 2>/dev/null | wc -l | tr -d ' ')
[ "$WINDOWS" != "4" ] && PROBLEMS="tmux windows ${WINDOWS}/4."

MASTER=$(grep '^MASTER_KEY' $ARGUS/.env | cut -d= -f2-)
HTTP=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $MASTER" http://localhost:8002/status)
[ "$HTTP" != "200" ] && PROBLEMS="$PROBLEMS executor /status=$HTTP."

if [ -f "$ARGUS/data/argus.db" ]; then
  AGE=$(( $(date +%s) - $(stat -f %m "$ARGUS/data/argus.db") ))
  [ "$AGE" -gt 2700 ] && PROBLEMS="$PROBLEMS analyst silent ${AGE}s."
else
  PROBLEMS="$PROBLEMS db missing."
fi

# ── Reverse watch: Agent 2's Ollama (LLM dependency) ───────────
# Notify-only — LLM being down degrades guest chat, not trading,
# so it must never trigger a stack restart.
OLLAMA=$(curl -s -m 8 -o /dev/null -w '%{http_code}' http://[REDACTED-TS]:11434/api/tags 2>/dev/null)
if [ "$OLLAMA" != "200" ]; then
  if [ ! -f /tmp/argus_ollama_notified ]; then
    touch /tmp/argus_ollama_notified
    notify "⚠️ ARGUS: Agent 2 Ollama unreachable — LLM features degraded, trading unaffected."
  fi
else
  if [ -f /tmp/argus_ollama_notified ]; then
    rm -f /tmp/argus_ollama_notified
    notify "✅ ARGUS: Agent 2 Ollama reachable again."
  fi
fi

# ── Active recovery ────────────────────────────────────────────
if [ -n "$PROBLEMS" ]; then
  NOW=$(date +%s)
  LAST=$(cat "$COOLDOWN" 2>/dev/null || echo 0)
  SINCE=$(( NOW - LAST ))

  if [ "$SINCE" -ge "$COOLDOWN_SECS" ]; then
    # First response to this outage: restart the stack ourselves.
    echo "$NOW" > "$COOLDOWN"
    notify "🔧 ARGUS WATCHDOG: detected [$PROBLEMS] — auto-restarting the stack. Will confirm recovery next check (~5 min)."
    zsh "$ARGUS/start_argus.sh" >/tmp/argus_v2_watchdog_restart.log 2>&1
    touch "$STATE"
  else
    # We already restarted within the cooldown and it's STILL broken → escalate.
    if [ ! -f "$STATE.escalated" ]; then
      touch "$STATE.escalated"
      notify "🚨 ARGUS WATCHDOG: auto-restart did NOT recover [$PROBLEMS]. Needs you: ssh agent1, then zsh ~/argus_v2/start_argus.sh — or Screen Share vnc://[REDACTED-LAN]."
    fi
  fi
else
  # Healthy. If we were in an outage, announce recovery and clear all state.
  if [ -f "$STATE" ]; then
    notify "✅ ARGUS WATCHDOG: system recovered and healthy again."
  fi
  rm -f "$STATE" "$STATE.escalated"
fi

# Heartbeat — proves the watchdog itself is alive
echo "$(date '+%Y-%m-%d %H:%M:%S') windows=$WINDOWS http=$HTTP problems=${PROBLEMS:-none}" > /tmp/argus_v2_watchdog_last
