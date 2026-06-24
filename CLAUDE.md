# CLAUDE.md — Argus Project Rules

## Golden Rules

1. **Test every change before moving on.** After any system-level change (SSH, firewall, networking, login), verify access still works BEFORE making the next change. If access breaks, fix it immediately.

2. **Never touch firewall or security settings without a rollback path.** Always confirm you can still SSH in after each individual change. Never batch security changes.

3. **Do what was asked. Nothing more.** If the user asks for one thing, do that one thing. Don't chain 5 tasks together. Don't "while I'm here" something that wasn't requested.

4. **Agent 2 is the test bed. Agent 1 is production.** Test risky changes on Agent 2 first. Never experiment on Agent 1.

5. **Finish before starting.** Complete the current task fully, verify it works, then ask what's next. Don't start new work unprompted.

6. **Parity rule: both machines get the same setup.** Every infrastructure change applies to both Mac Minis. Don't leave one half-configured.

7. **Don't ask the user to run commands.** If they gave permission, execute it. Don't send them to a terminal, don't make them paste things, don't make them VNC in. Handle it.

8. **Protect capital above everything.** Argus trades real money. Conservative defaults. No experimental signals on live accounts. The user said "I don't have $500 to lose."

9. **No unnecessary output.** Don't explain what you're about to do in 3 paragraphs. Do it, report the result in one line.

10. **Own your mistakes immediately.** Don't hedge, don't explain why it happened. Say what broke, say how you're fixing it.

## Security

- `.env` must NEVER be committed to GitHub
- MASTER_KEY stored only in `.env`, never in code
- No passwords, IPs, keys, or credentials in any committed file
- SSH key-based auth only for GitHub

## Architecture

- 3 services: analyst, executor, bot — all on Agent 1 in tmux session `argus`
- Agent 2: Ollama LLM backend (llama3.1:8b), accessed from Agent 1 over Tailscale
- Both machines: SSH + Tailscale + Screen Sharing + auto-login

## Current State (2026-06-24)

- Both Mac Minis have firewall --setblockall on — LOCKED OUT
- Fix required: physical keyboard on Agent 1, run: sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setblockall off
- Then same on Agent 2 with password: none
- After fix: redo security hardening ONE CHANGE AT A TIME with access verification between each step
