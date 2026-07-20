# Argus Terminal — Go-Live Runbook

The public signal terminal is **built, tested, and dormant**. It generates to
`public/index.html` every 10 min (launchd `com.argus.terminal`) but is not served
anywhere. Flipping it live is the steps below — and taking it back down is one line.

Prerequisite already done: the page is leak-tested (entry/target/secrets can't
appear), multi-source news works, deploy pipeline verified against a local target.

## Go live (≈ 5 minutes)

1. **Publish the page** to the `gh-pages` branch:
   ```
   ssh agent1
   zsh ~/argus_v2/ops/deploy_pages.sh
   ```
   Pushes only `index.html` + `.nojekyll` (force-push, single commit, no history).

2. **Enable GitHub Pages** (the actual public switch):
   ```
   gh api -X POST repos/VagabondCarlo/argus/pages \
     -f 'source[branch]=gh-pages' -f 'source[path]=/'
   ```
   or GitHub → repo → Settings → Pages → Source: `gh-pages` / root.
   Site goes live at: https://vagabondcarlo.github.io/argus/

3. **Auto-refresh** so the live site tracks the book (every 10 min):
   ```
   cp ~/argus_v2/ops/com.argus.pages.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.argus.pages.plist
   ```

4. **(Optional) custom domain**: add a `CNAME` file to the deploy and point DNS.
   Tell me the domain and I'll wire it in.

## Take it back down (instant)

```
launchctl unload ~/Library/LaunchAgents/com.argus.pages.plist 2>/dev/null
gh api -X DELETE repos/VagabondCarlo/argus/pages          # disable Pages
git push git@github.com:VagabondCarlo/argus.git --delete gh-pages
```

## Notes
- Nothing here exposes the Mac Mini — GitHub serves a static file; the Mini only
  pushes to it.
- Everything published is already scrubbed by `notifications/public_feed.py`; the
  gh-pages branch is force-replaced each deploy, so no data accumulates.
- Decide before launch: keep the track record on a delay (Pro = real-time) — the
  page footer already states "free feed is delayed."
