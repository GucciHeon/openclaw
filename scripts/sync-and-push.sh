#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="/home/user/mission-control-test"
cd "$REPO_DIR"
node scripts/sync-openclaw-data.mjs
node scripts/build-site-data.mjs
node scripts/generate-agent-state.mjs
if [[ -n "$(git status --porcelain)" ]]; then
  git add .
  git commit -m "chore(sync): update OpenClaw workspace snapshot $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  git push origin master
  echo "Pushed updates"
else
  echo "No changes"
fi
