#!/usr/bin/env bash
# Launch a CDP-enabled browser for the game copilot.
#
# A human logs into the game ONCE in this window; the copilot then attaches over CDP
# (port 9222) and reuses that logged-in session — never a fresh automation login.
# Keep this window open. Close it gracefully; do NOT force-kill it (logs out the session).
set -euo pipefail
PORT="${CDP_PORT:-9222}"
URL="${GAME_URL:-https://buildyourwolfpack.com/pages/game#/select-startup}"
PROFILE="${CDP_PROFILE:-$HOME/.wolfpack-cdp-profile}"
mkdir -p "$PROFILE"

CHROME=""
for c in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium" \
  "$(command -v google-chrome 2>/dev/null || true)" \
  "$(command -v google-chrome-stable 2>/dev/null || true)" \
  "$(command -v chromium 2>/dev/null || true)" \
  "$(command -v chromium-browser 2>/dev/null || true)" \
  "$(command -v microsoft-edge 2>/dev/null || true)"; do
  if [ -n "$c" ] && [ -x "$c" ]; then CHROME="$c"; break; fi
done
[ -z "$CHROME" ] && { echo "No Chrome/Edge/Chromium found — install one."; exit 1; }

echo "Launching: $CHROME"
echo "  CDP port : $PORT     profile: $PROFILE"
echo "  -> Log into the game in this window (Google sign-in), then run:"
echo "     python -m jarvis_os.core.copilot_runner --config config/jarvis.yaml"
echo "  Keep this window open. Close gracefully when done."
exec "$CHROME" --remote-debugging-port="$PORT" --user-data-dir="$PROFILE" "$URL"
