# Changelog

## 2026-06-24

### Incident: Firewall Lockout — Both Mac Minis
**What happened:** During a security hardening pass, `socketfilterfw --setblockall on` was applied to both Agent 1 and Agent 2 alongside a bad SSH config (`UsePAM no` in `/etc/ssh/sshd_config.d/hardened.conf`). This blocked ALL incoming connections — SSH, VNC, everything. Both machines became completely inaccessible remotely.

**Root cause:** Changes were batched without verifying access between each one. The `--setblockall` flag overrides all per-app firewall exceptions. `UsePAM no` crashes sshd on macOS because PAM is required for session setup.

**Recovery:** Required physical monitor + keyboard on each Mac Mini. Fix script served from MacBook via `python3 -m http.server 8888`, pulled from each Mini with `curl 192.168.1.162:8888/fix|sudo bash`. Script removed the bad sshd config, disabled the firewall, and restarted sshd.

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
