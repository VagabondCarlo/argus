# Changelog

## 2026-07-17 (afternoon) — Selective + active: the two-book model

**Mike's call after the first loss posted: not keen on constant losses — something missing.**
Diagnosis: two conflicting jobs (public track record vs calibration data) were sharing
one account. Fixed by splitting them:

- **Real book: execution floor back to 0.72** — every live trade is in the replay-proven
  band (56% at ~2:1). The record only carries evidence-backed trades.
- **Shadow book (new): virtual outcome scoring** — nightly job (analyst/shadow_book.py,
  launchd com.argus.shadowbook 21:37 ET) replays every untraded 0.62+ signal against
  actual 15-min bars and records win/loss/expired + R to a virtual_outcomes table.
  Full calibration dataset, zero real losses. Same conservative rules as the July replay.
  First run: 23 scored, 4 resolved (0.66-0.72 band 2W-0L, +2R virtual).
- **Crypto universe 9 → 19 pairs** — DOT, LTC, BCH, AAVE, SHIB, FIL, CRV, SUSHI, YFI, BAT
  added; each validated Alpaca-tradable AND yfinance-data-rich before inclusion.
  Breadth is the flow lever, not looser gates.
- Note for the record: the 0W-1L on the books at this decision was the six-cent BTC
  pipeline-verification close, not a strategy loss.

## 2026-07-17 (midday) — Guest LLM guardrails

- Input screening (jailbreak playbook regexes, length cap, URL limits) — flagged
  messages never reach the LLM and do not consume guest question quota
- 3 strikes in 24h = 24h mute per user_id; every flag logged
- Prompt hardening: guest text wrapped as untrusted data; security restatement at
  prompt end; model pinned to llama3.1:8b (host also serves an uncensored model)
- Output screening: prompt leaks, persona breaks, directive trading language
  ("you should buy"), and "guaranteed profit" claims replaced before sending
- Research agent (OpenClaw) now receives ticker-only prompts, never raw guest text
- 17 guardrail tests; suite at 38

## 2026-07-17 (midday) — User interaction layer

- Public track-record feed: every position close posts a card (entry/exit/P&L/
  running record) + daily recap 16:40 ET; preview mode until TRACK_RECORD_CHANNEL_ID set
- Free tier broadcast redesigned in the same visual language; upsell removed (Tier 2 TBD)
- Digest notification mode: routine trade pushes off; only risk/failure events ping Mike
- Fixed: v1 SELL-close left the entry trade row open forever

## 2026-07-17 — Data-collection phase begins

- **Full-slots mode (same day, Mike's call):** execution floor lowered to 0.62 and the
  scorer's directional cutoff aligned to it (0.15 -> 0.12 score). The old cutoff made
  every sub-0.65 signal WATCH by construction — stocks could never trade at any
  executor threshold. Now the ranked batch fills all 3 slots with the best available
  fresh signals. Known cost: replay expectancy in the 0.62-0.66 band was slightly
  negative; the daily/weekly loss rails are the budget. Recalibration from live fills
  after ~2 weeks draws the real line.
- **Execution threshold lowered 0.72 → 0.66 (paper account).** Goal: aggregate live
  outcome data across the full 0.66–0.82 confidence band (~5+ trades/day instead of
  1–2). Every trade records its signal's confidence; after ~2 weeks the threshold
  gets recalibrated from live fills instead of replayed bars. 0.72 remains the
  evidence bar from the v1 replay. All risk limits unchanged.
- Incident: analyst down 07:08–08:20 ET — a stale yfinance tz-cache WAL left by
  v1's July 7 hard kill broke v2's first pre-market full-universe scan ("unable to
  open database file" loop). Fix: clear ~/Library/Caches/py-yfinance. If it recurs,
  same fix.
- Watchdog moved from cron to launchd (com.argus.watchdog) — macOS cron silently
  never ran it. Heartbeat file added: /tmp/argus_v2_watchdog_last.


## 2026-07-16 — v2.0

### Why v2
The v1 trial (June 16 – July 6) generated 2,559 signals but stopped trading after June 17.
Root-cause chain: oversized June 17 entries → hard-cut close failed (resting stop orders
held the shares, Alpaca rejected with "insufficient qty") → 10 positions stuck over the
3-position limit → every subsequent BUY skipped → 0 trades for 19 days, undetected.

A replay of all 733 archived BUY/SELL signals against actual 15-min price history found:
signals ≥0.72 confidence won 56% at ~2:1 R/R (+20.4R across stocks and crypto); the
0.70–0.72 slice lost ~23R; everything below 0.66 was net negative. The active .env
threshold was 0.66.

### Execution engine
- **Threshold 0.72** everywhere — one value in shared config, no more code-vs-.env drift
- **Ranked batch selection** — executor pulls every fresh candidate, ranks by confidence
  (R/R tiebreak), fills open slots best-first. v1 took the first signal over threshold
- **30-min signal expiry** — stale entries never execute at prices that no longer exist
- **Crypto executes via Alpaca 24/7** (GTC market orders, position monitor as the stop —
  Alpaca doesn't support stop/bracket orders on crypto). Non-listed coins skipped cleanly
- **Audit path removed from the watcher** — the 0.70–0.72 zone it served was the money
  loser in replay; /audit REST endpoint remains
- Forex/metals stay signal-only (no broker route)

### Bug fixes from v1
- Hard cut now cancels resting stop/take-profit orders before closing (the June 17 jam)
- Monitor-driven closes recorded in trades/daily_stats (risk limits can now see them)
- Breakeven is a real software stop — v1 only sent the notification, nothing enforced it
- High-confidence WATCH signals could fall through to a live SELL order — now filtered
- Position monitor runs 24/7 for crypto; crypto position sizing uses 6-decimal qty
  (2-decimal rounding zeroed out BTC-sized orders)

### Tests
- `tests/test_execution_path.py` — 10 integration tests driving the real
  process_pending_signals() against a temp DB with only the broker/Telegram mocked.
  Run after ANY pipeline change: `venv/bin/python -m pytest tests/ -v`

### Timing (sharpened same-day)
- Analyst scans: market hours 15 → 5 min; pre/after-hours 30 → 15 min; overnight 60 → 15 min
- Per-ticker cooldowns: scalp stocks 1 h → 20 min; crypto/forex/metals 2 h → 30 min
- Executor signal watcher and position monitor: 30s flat, 24/7 (monitor cadence = the
  crypto stop's granularity)
- Signal expiry 30 → 15 min — a fresh scan batch always lands before signals go stale
- Watch item: 3x yfinance request rate — if 429/throttle errors appear in analyst logs,
  back the market-hours interval off to 600s before touching anything else

### Flaw-review fixes (same-day)
- **Software stop/target enforcement** — the monitor now looks up each position's
  originating signal and closes at its actual stop/target. Critical: crypto and
  fractional stock positions (any stock >$100/share at the $100 cap) carry NO
  broker-side protective orders, so without this the replayed edge (exit at target/stop)
  never happens live. Exit priority: signal stop → signal target → -3% hard cut
  (backstop) → breakeven exit
- **Entry drift guard** — a signal executing minutes after birth is skipped if price
  already ran past half the risk distance toward target, or through the stop
- **Notify-once** — order failures mark the signal handled (no 30s retry+ping loop);
  risk-limit alerts fire once per distinct reason; failing monitor closes retry
  quietly after the first alert
- **Pre-market signals execute at the open** — for the first 15 min after 9:30 the
  stock window reaches back through the pre-market session; drift guard rejects gaps
- Weekly trade cap counts entries only (round trip = 1 trade, so 25/week means 25 entries)
- Watcher and /audit endpoint serialized by a lock (no racing past the position limit)
- Breakeven-armed flags persist across restarts (data/breakeven_armed.json)
- Closes record actual fill price when available, not the last snapshot
- Test suite now 15 tests

### Config notes
- Tier 1/Tier 2 channel IDs commented out in .env — no public posts until relaunch decision
- v1 archive untouched at ~/argus_backup_20260707/

## 2026-06-24

### Incident: Firewall Lockout — Both Mac Minis
**What happened:** During a security hardening pass, `socketfilterfw --setblockall on` was applied to both Agent 1 and Agent 2 alongside a bad SSH config (`UsePAM no` in `/etc/ssh/sshd_config.d/hardened.conf`). This blocked ALL incoming connections — SSH, VNC, everything. Both machines became completely inaccessible remotely.

**Root cause:** Changes were batched without verifying access between each one. The `--setblockall` flag overrides all per-app firewall exceptions. `UsePAM no` crashes sshd on macOS because PAM is required for session setup.

**Recovery:** Required physical monitor + keyboard on each Mac Mini. Fix script served from MacBook via `python3 -m http.server 8888`, pulled from each Mini with `curl <macbook-lan>:8888/fix|sudo bash`. Script removed the bad sshd config, disabled the firewall, and restarted sshd.

**Lesson:** Never batch security changes. Test each one individually and verify SSH access before proceeding to the next.

### Infrastructure
- Auto-login configured on Agent 1 (was missing — should have been done with Agent 2 weeks ago)
- Tailscale LaunchDaemon created on Agent 1 (starts on boot)
- Hostnames standardized: `agent1` and `agent2`
- SSH config updated with `.local` fallback paths for DHCP resilience
- Screen Sharing (ARD) activated on both machines
- `bridge` command installed on all three machines (MacBook, Agent 1, Agent 2) — quick-connect menu for SSH and Screen Share
- Live HUD dashboards deployed to both Mac Mini screens — real-time service, trading, network, and system monitoring

### Argus
- LLM three-committee framework wired into scan pipeline — top 5 BUY/SELL candidates scored by llama3.1:8b on Agent 2 via Tailscale
- Ollama on Agent 2 configured to listen on all interfaces (0.0.0.0:11434)
- `OLLAMA_HOST` added to shared config
- LLM reasoning field normalized (list → string)

## 2026-06-22

### Argus
- Entry price added to signals table and `/signals` display
- SELL label fixed ("close position" not "Short")
- Disclaimer spam fixed (once per day per user)
- `/positions` command added (live Alpaca P&L)
- Welcome DM on `/addpaid`
- Maintenance mode implemented (flag file blocks guest users, owner unaffected)

### Agent 2 Setup
- Mac Mini 2 configured headless: auto-login, Tailscale, SSH, Screen Sharing
- Ollama + OpenClaw installed, llama3.1:8b model pulled
- GitHub repo `VagabondCarlo/agent2` created
- Phantom WiFi auditor built (ISP fingerprinting, LLM wordlist generation, hashcat pipeline)

## 2026-06-18

### Argus Debug Pass
- Fixed `datetime.utcnow()` deprecation across codebase
- Fixed hardcoded trade limit (was 3, now reads from config)
- Fixed HOLD vs WATCH logic bug
- Fixed bot startup crash on bad TELEGRAM_CHAT_ID
- Security: `secrets.compare_digest` for master key, SSRF hardening, input sanitization
- Signal deduplication for extended scans
- Grouped `/signals` display by asset class
