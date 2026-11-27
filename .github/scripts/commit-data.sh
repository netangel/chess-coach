#!/usr/bin/env bash
# Commit pipeline state (data/, journal/, plan/) and push to the current branch.
# Usage: commit-data.sh "<message>" [push=true|false]
set -euo pipefail
msg="$1"
push="${2:-true}"

git config user.name "chess-coach-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add data/
if git diff --cached --quiet; then
  echo "no data changes"
  exit 0
fi
git commit -q -m "$msg [skip ci]"
git --no-pager show --stat --oneline HEAD | head -30
if [ "$push" != "true" ]; then
  echo "push disabled; commit not pushed"
  exit 0
fi
for attempt in 1 2 3; do
  if git push origin HEAD; then
    exit 0
  fi
  echo "push rejected (attempt $attempt), rebasing on remote"
  git pull --rebase origin "$(git rev-parse --abbrev-ref HEAD)"
done
echo "::error::could not push data commit"
exit 1
