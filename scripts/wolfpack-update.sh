#!/usr/bin/env bash
# wolfpack-update — update the Jarvis runtime on a Wolfpack OS peer from the
# public repo. Pull-based, offline-safe to attempt (fails closed), with backup,
# health check, and automatic rollback.
#
# Usage:
#   sudo wolfpack-update            # update to the latest release tag (stable)
#   sudo wolfpack-update main       # track the edge (main branch)
#   sudo wolfpack-update v1.0.1     # a specific tag/branch/sha
#
# What it does:
#   1. clones the public repo (shallow) at the requested ref into a temp dir
#   2. backs up /opt/jarvis-src/jarvis_os + requirements.txt
#   3. rsyncs the new runtime over /opt/jarvis-src (runtime files only — local
#      config, personas, skills, and data are never touched)
#   4. re-installs python deps IF requirements.txt changed
#   5. restarts jarvis.service and health-checks (active + GUI on :8080)
#   6. on failure: restores the backup, restarts again, reports the rollback
#
# Logs: /var/log/wolfpack-update.log (and stdout). Lock: flock, one at a time.
set -euo pipefail

REPO="https://github.com/DomMasteroftheGame/wolfpack-os.git"
# Runtime home: current installers use /opt/jarvis-os; tolerate the legacy
# /opt/jarvis-src layout too.
SRC="/opt/jarvis-os"
[ -d "$SRC/jarvis_os" ] || SRC="/opt/jarvis-src"
BACKUP="$SRC/.update-backup"
LOG="/var/log/wolfpack-update.log"
LOCK="/run/wolfpack-update.lock"
GUI_PORT=8080
SERVICE=jarvis.service

REF="${1:-}"
log() { echo "[wolfpack-update $(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo wolfpack-update [ref]" >&2; exit 2; }
exec 9>"$LOCK"
flock -n 9 || { echo "another wolfpack-update is running" >&2; exit 3; }

# Resolve the ref: explicit arg, else newest v* tag on the remote, else main.
if [ -z "$REF" ]; then
  log "resolving latest stable tag from $REPO"
  REF="$(git ls-remote --tags --sort='-v:refname' "$REPO" 'v*' 2>/dev/null | head -1 | sed 's|.*/||' || true)"
  REF="${REF:-main}"
fi
log "target ref: $REF"

command -v git >/dev/null || { log "installing git"; apt-get update -qq && apt-get install -y -qq git >>"$LOG" 2>&1; }

WORK="$(mktemp -d /tmp/wolfpack-update.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

log "cloning $REPO @ $REF"
git clone --depth 1 --branch "$REF" "$REPO" "$WORK/repo" >>"$LOG" 2>&1 || {
  log "ERROR: could not fetch $REF (offline? bad ref?) — peer unchanged"
  exit 1
}
NEW_SHA="$(git -C "$WORK/repo" rev-parse --short HEAD)"
log "fetched runtime @ $NEW_SHA"

log "backing up current runtime"
mkdir -p "$BACKUP"
rm -rf "$BACKUP/jarvis_os" "$BACKUP/requirements.txt"
cp -a "$SRC/jarvis_os" "$BACKUP/jarvis_os"
[ -f "$SRC/requirements.txt" ] && cp -a "$SRC/requirements.txt" "$BACKUP/requirements.txt" || true

DEPS_CHANGED=0
if [ -f "$SRC/requirements.txt" ] && ! cmp -s "$SRC/requirements.txt" "$WORK/repo/requirements.txt"; then
  DEPS_CHANGED=1
fi

log "swapping runtime (jarvis_os + requirements.txt only)"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' \
  "$WORK/repo/jarvis_os/" "$SRC/jarvis_os/"
cp -a "$WORK/repo/requirements.txt" "$SRC/requirements.txt"

if [ "$DEPS_CHANGED" -eq 1 ]; then
  log "requirements changed — upgrading python deps"
  PYBIN="$SRC/.venv/bin/pip"
  [ -x "$PYBIN" ] || PYBIN="pip3"
  "$PYBIN" install --quiet --upgrade -r "$SRC/requirements.txt" >>"$LOG" 2>&1 || \
    log "WARN: pip upgrade reported errors (continuing; health check will judge)"
fi

log "restarting $SERVICE"
systemctl restart "$SERVICE"
sleep 6

healthy() {
  systemctl is-active --quiet "$SERVICE" || return 1
  curl -fsS -m 8 "http://127.0.0.1:$GUI_PORT/" >/dev/null 2>&1 || return 1
  return 0
}

if healthy; then
  log "OK — peer now runs $REF ($NEW_SHA); backup kept at $BACKUP"
  exit 0
fi

log "HEALTH CHECK FAILED — rolling back"
rm -rf "$SRC/jarvis_os"
cp -a "$BACKUP/jarvis_os" "$SRC/jarvis_os"
[ -f "$BACKUP/requirements.txt" ] && cp -a "$BACKUP/requirements.txt" "$SRC/requirements.txt" || true
systemctl restart "$SERVICE" || true
sleep 6
if healthy; then
  log "rollback OK — peer is back on the previous runtime"
  exit 4
fi
log "ERROR: rollback did not restore health — check journalctl -u $SERVICE"
exit 5
