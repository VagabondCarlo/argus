#!/bin/zsh
# ARGUS FAILOVER — Agent 2 warm standby. HUMAN-GATED, deliberately.
#
# Run this ONLY when you are certain Agent 1 is dead (power/hardware failure),
# NOT merely unreachable from where you are. If Agent 1 is still alive and
# trading, starting this stack means TWO executors on one Alpaca account —
# double orders. When in doubt: log into Alpaca first; the broker is the
# source of truth for open positions.
set -e
cd ~/argus_v2

echo "════════════════════════════════════════════════════"
echo "  ARGUS FAILOVER — start live trading on AGENT 2"
echo "  Preconditions you are confirming:"
echo "   1. Agent 1 is DOWN (not just unreachable to you)"
echo "   2. No other Argus executor is running anywhere"
echo "════════════════════════════════════════════════════"
read "REPLY?Type GO to proceed: "
if [ "$REPLY" != "GO" ]; then echo "Aborted."; exit 1; fi

if [ ! -f ~/argus_replica/argus-latest.db ]; then
  echo "No replica found at ~/argus_replica/argus-latest.db — aborting."; exit 1
fi

mkdir -p data
cp ~/argus_replica/argus-latest.db data/argus.db
echo "Book restored from replica ($(sqlite3 data/argus.db 'SELECT COUNT(*) FROM signals;') signals)."

zsh start_argus.sh
sleep 8
tmux list-windows -t argus_v2
echo "Stack is live on AGENT 2. Watch it: tmux attach -t argus_v2"
echo "Remember to shut this down before reviving Agent 1."
