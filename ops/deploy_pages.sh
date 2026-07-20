#!/bin/zsh
# Argus GitHub Pages deploy — the GO button for the public terminal.
#
# Regenerates the page and force-pushes ONLY public/index.html (+ .nojekyll)
# to an orphan `gh-pages` branch. Uses a throwaway temp repo, so the main
# repo's history is never touched and NOTHING but the current page ships —
# no accumulated history, no chance of leaking anything the feed didn't emit.
#
# This does NOT make the site live by itself: GitHub Pages must be enabled once
# in repo Settings → Pages (source: gh-pages branch). That enable is the true
# public switch — see ops/agent2/../GO_LIVE.md. Until then this is inert.
#
#   REMOTE override lets us test against a local bare repo without publishing.
set -e
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin

REPO=~/argus_v2
REMOTE="${ARGUS_PAGES_REMOTE:-git@github.com:VagabondCarlo/argus.git}"

cd "$REPO"
./venv/bin/python -m notifications.render_terminal

if [ ! -s public/index.html ]; then
  echo "render produced no page — aborting deploy"; exit 1
fi

TMP=$(mktemp -d)
cp public/index.html "$TMP/index.html"
touch "$TMP/.nojekyll"
cd "$TMP"
git init -q
git checkout -q -b gh-pages
git -c user.email=argus@localhost -c user.name=Argus add -A
git -c user.email=argus@localhost -c user.name=Argus commit -qm "deploy $(date '+%Y-%m-%d %H:%M')"
git push -qf "$REMOTE" gh-pages
cd /; rm -rf "$TMP"
echo "deployed public/index.html to gh-pages on $REMOTE"
