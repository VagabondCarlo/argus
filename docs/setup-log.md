# Argus Setup Log

A running record of everything done, including blockers and how they were resolved.
This exists so the project is fully reproducible and auditable.

---

## MacBook Pro (Development Machine)

**Date:** June 11, 2026

### Completed
- [x] Installed Homebrew 6.0
- [x] Installed Python 3.11.15
- [x] Installed Ollama + pulled `llama3.1:8b` (4.9GB)
- [x] Created project structure at `~/Documents/argus/`
- [x] Initialized git repo, connected to GitHub (VagabondCarlo/argus)
- [x] Created virtual environment, installed all dependencies
- [x] Built Telegram bot (ArgusVagabondBot) with full bidirectional control
- [x] Built 3 daily scheduled reports (8:30AM / 12:30PM / 4:30PM ET)
- [x] Built guest mode — unknown users get read-only market intelligence
- [x] Built SQLite database layer for signals, trades, and stats
- [x] Generated SSH key pair for remote machine access

### Blockers Encountered
- **pandas-ta incompatible with Python 3.11** → replaced with `ta` library
- **GitHub PAT exposed in chat** → token revoked immediately, switched to SSH key auth
- **SSH key had 1-character typo when manually copied** → corrected and re-sent

---

## Mac Mini 1 (Analyst Agent — "Mac's Mac mini")

**Local IP:** 192.168.1.169
**Username:** Agent1
**Role:** Runs LLM analysis, generates trade signals

### Completed
- [x] macOS initial setup with Apple ID
- [x] FileVault disabled (required for headless auto-login)
- [x] iCloud sync disabled (photos, contacts, safari, etc.)
- [x] Energy settings: no sleep, auto-restart after power failure
- [x] Remote Login (SSH) enabled in Sharing settings
- [x] Screen Sharing enabled in Sharing settings
- [x] SSH public key added to authorized_keys

### Blockers Encountered
- **FileVault enabled by default** → blocked auto-login → disabled FileVault (30min decrypt)
- **`ipconfig getifaddr en0` returned nothing** → Mac Mini on WiFi not ethernet → used `en1`
- **SSH key typo** → character `l` misread as `1` during manual copy → corrected
- **SSH connection closing before password prompt** → Agent1 not in `com.apple.access_ssh` group → fix: `sudo dseditgroup -o edit -a Agent1 -t user com.apple.access_ssh`
- **Screen Sharing password auth failing** → same SSH group issue, resolved with above fix

### In Progress
- [ ] Add Agent1 to SSH allowed group (command below — run on Mac Mini directly)
- [ ] Verify SSH access from MacBook Pro
- [ ] Install Homebrew, Python 3.11, Ollama on Mac Mini
- [ ] Clone argus repo
- [ ] Set up auto-login
- [ ] Configure launchd to auto-start analyst agent on boot

### Command to run on Mac Mini (final step before going headless)
```bash
sudo dseditgroup -o edit -a Agent1 -t user com.apple.access_ssh
```

---

## Mac Mini 2 (Executor Agent)

**Status:** Not yet unboxed
**Role:** Receives signals from Analyst, executes trades via Alpaca API

---

## Pending Setup Items (All Machines)

- [ ] Alpaca paper trading API keys added to .env
- [ ] NewsAPI key obtained and added
- [ ] Analyst agent built and tested
- [ ] Executor agent built and tested
- [ ] End-to-end paper trading test
- [ ] SSH key added to GitHub (MacBook Pro)
