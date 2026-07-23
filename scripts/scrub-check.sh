#!/usr/bin/env bash
# scrub-check.sh — hard gate: fail if any known secret pattern exists in the tree.
# Usage: bash scripts/scrub-check.sh [dir]   (default: repo root)
set -euo pipefail
ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
fail=0

# Token/key patterns that must never appear in the release tree.
PATTERNS=(
  'shptka_'                 # Shopify Theme Access token
  'GOCSPX-'                 # Google OAuth client secret
  'gho_[A-Za-z0-9]{20,}'    # GitHub OAuth token
  'ghp_[A-Za-z0-9]{20,}'    # GitHub PAT
  'github_pat_[A-Za-z0-9_]{20,}'
  'sk-[A-Za-z0-9_-]{20,}'   # OpenAI/Anthropic-style API keys
  'sk-ant-'                 # Anthropic
  'AIza[0-9A-Za-z_-]{35}'   # Google API key (see allowlist below for the public Firebase web key)
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  'WOLFPACK_MESH_TOKEN=[^n]'  # mesh token set to a real value
)

for pat in "${PATTERNS[@]}"; do
  if grep -rEn --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude=scrub-check.sh "$pat" "$ROOT" > /tmp/scrub-hits.txt 2>/dev/null; then
    # Allowlist: the Firebase web apiKey in the game is public by design.
    grep -v "build-your-wolfpack-pm-game" /tmp/scrub-hits.txt | grep -v "AIzaSyDLPjvJ1auvfpJo06X6WDkLZqhCufSpdAA" > /tmp/scrub-real.txt || true
    if [ -s /tmp/scrub-real.txt ]; then
      echo "SCRUB FAIL [$pat]:"
      head -5 /tmp/scrub-real.txt
      fail=1
    fi
  fi
done

if [ "$fail" -eq 1 ]; then
  echo "Scrub check FAILED — release blocked."
  exit 1
fi
echo "Scrub check clean ($ROOT)"
