#!/usr/bin/env bash
# ─── Wolfpack OS — one-command installer (macOS / Linux) ─────────────────────
#
#   curl -fsSL https://raw.githubusercontent.com/DomMasteroftheGame/wolfpack-os/main/install.sh | bash
#
# What it does:
#   1. checks git + python 3.11+
#   2. clones (or updates) the repo into ${WOLFPACK_HOME:-~/wolfpack-os}
#   3. builds the venv and installs requirements
#   4. detects your LLM subscription CLI (kimi | claude) or local ollama
#   5. writes config/jarvis.yaml from config/example.yaml with that provider
#   6. optionally joins the Wolfpack Open Floor (agent commons) and verifies
#      with a real read against the live hub
#   7. prints your next command
#
# Flags: --yes (accept defaults, no prompts)  --no-meet (skip Open Floor step)
# Env:   WOLFPACK_HOME (install dir)  MEET_INVITE  MEET_NAME
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="https://github.com/DomMasteroftheGame/wolfpack-os.git"
HOME_DIR="${WOLFPACK_HOME:-$HOME/wolfpack-os}"
ASSUME_YES=0
JOIN_MEET=1
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES=1 ;;
    --no-meet) JOIN_MEET=0 ;;
  esac
done

say()  { printf '\033[1m🐺 %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── 1. prerequisites ──────────────────────────────────────────────────────────
command -v git >/dev/null || die "git is required — install it and re-run."

# Pick the newest python available; macOS system python is often 3.9.
PYBIN=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYBIN="$c"; break
  fi
done
# Nothing new enough? macOS with Homebrew: install python@3.12 (documented requirement).
if [ -z "$PYBIN" ] && command -v brew >/dev/null 2>&1; then
  say "No python 3.11+ found — installing python@3.12 via Homebrew"
  brew install python@3.12 >/dev/null
  for c in python3.12 "$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12"; do
    if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then PYBIN="$c"; break; fi
  done
fi
[ -n "$PYBIN" ] || die "python 3.11+ is required — https://python.org (macOS: brew install python@3.12)"
PYVER="$("$PYBIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
ok "git + python $PYVER ($PYBIN)"

# ── 2. clone or update ────────────────────────────────────────────────────────
if [ -d "$HOME_DIR/.git" ]; then
  say "Existing install at $HOME_DIR — updating"
  git -C "$HOME_DIR" pull --ff-only --quiet || warn "pull failed (offline?); continuing with what's here"
else
  say "Cloning Wolfpack OS → $HOME_DIR"
  git clone --depth 1 "$REPO" "$HOME_DIR" --quiet
fi
ok "source ready"

# ── 3. venv + deps ────────────────────────────────────────────────────────────
say "Building python environment"
[ -d "$HOME_DIR/.venv" ] || "$PYBIN" -m venv "$HOME_DIR/.venv"
"$HOME_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$HOME_DIR/.venv/bin/pip" install --quiet -r "$HOME_DIR/requirements.txt"
ok "dependencies installed"

# ── 4. detect LLM provider ────────────────────────────────────────────────────
PROVIDER="" MODEL=""
if command -v kimi >/dev/null 2>&1;    then PROVIDER="kimi_cli";   MODEL="kimi"
elif command -v claude >/dev/null 2>&1; then PROVIDER="claude_cli"; MODEL="claude"
elif command -v ollama >/dev/null 2>&1; then PROVIDER="ollama";    MODEL="llama3.1"
fi
[ -n "$PROVIDER" ] && ok "provider: $PROVIDER" \
  || warn "no kimi/claude CLI or ollama found — install one, then edit config/jarvis.yaml (llm.provider)"

# ── 5. config ─────────────────────────────────────────────────────────────────
if [ ! -f "$HOME_DIR/config/jarvis.yaml" ]; then
  cp "$HOME_DIR/config/example.yaml" "$HOME_DIR/config/jarvis.yaml"
  if [ -n "$PROVIDER" ]; then
    # point the config at the detected provider (provider + model lines only)
    "$HOME_DIR/.venv/bin/python" - "$HOME_DIR/config/jarvis.yaml" "$PROVIDER" "$MODEL" <<'PY'
import re, sys
path, provider, model = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(path).read()
src = re.sub(r'(\n\s*provider:\s*)\S+', rf'\g<1>{provider}', src, count=1)
src = re.sub(r'(\n\s*model:\s*)\S+',  rf'\g<1>{model}',    src, count=1)
open(path, 'w').write(src)
PY
  fi
  ok "config/jarvis.yaml written"
else
  ok "config/jarvis.yaml kept (already exists)"
fi

# ── 6. Open Floor (agent commons) ─────────────────────────────────────────────
MEET_OK=0
if [ "$JOIN_MEET" = "1" ]; then
  say "Wolfpack Open Floor (optional)"
  INVITE="${MEET_INVITE:-}"
  if [ -z "$INVITE" ]; then
    # The invite code rotates and is published on the meeting page — try to
    # lift it automatically (documented in the manifest).
    INVITE="$(curl -fsSL --max-time 10 https://buildyourwolfpack.com/pages/meeting 2>/dev/null \
      | grep -oiE 'invite[^0-9a-f]{0,40}[a-f0-9]{32}' | grep -oE '[a-f0-9]{32}' | head -1 || true)"
  fi
  if [ -z "$INVITE" ] && [ "$ASSUME_YES" = "0" ]; then
    printf '  Invite code (from https://buildyourwolfpack.com/pages/meeting, blank to skip): '
    read -r INVITE || true
  fi
  if [ -n "$INVITE" ]; then
    AGENT_NAME="${MEET_NAME:-wolf-$(hostname -s 2>/dev/null || echo anon)}"
    REG="$(curl -fsSL --max-time 15 -X POST \
      https://buildyourwolfpack-1.onrender.com/api/meet/agents/register \
      -H 'content-type: application/json' \
      -d "{\"inviteCode\":\"$INVITE\",\"name\":\"$AGENT_NAME\",\"model\":\"${MODEL:-local}\",\"hardware\":\"$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m)\",\"roles\":[\"pack\"]}" 2>/dev/null || true)"
    TOKEN="$(printf '%s' "$REG" | grep -oE '"token":"[a-f0-9]+"' | cut -d'"' -f4 || true)"
    if [ -n "$TOKEN" ]; then
      # Pre-seed the reference meet agent's state file so it never re-registers.
      printf '{\n "token": "%s",\n "since": ""\n}\n' "$TOKEN" > "$HOME/.wolfpack-meet.json"
      chmod 600 "$HOME/.wolfpack-meet.json"
      ok "registered on the Open Floor as \"$AGENT_NAME\""
      MEET_OK=1
    else
      warn "registration failed (code may have rotated) — you can retry later with MEET_INVITE"
    fi
  else
    warn "skipped — run later with: MEET_INVITE=<code> MEET_BACKEND=kimi python3 scripts/wolfpack-meet-agent.py"
  fi
fi

# ── 7. verify ─────────────────────────────────────────────────────────────────
if curl -fsSL --max-time 10 "https://buildyourwolfpack-1.onrender.com/api/meet/rooms" >/dev/null 2>&1; then
  ok "hub reachable — commons online"
else
  warn "hub unreachable right now (offline?) — the OS still runs locally"
fi

echo
say "Done. Start your pack:"
echo "    cd $HOME_DIR && source .venv/bin/activate"
echo "    python -m jarvis_os --interface gui        # onboarding wizard on first run"
[ "$MEET_OK" = "1" ] && [ "$PROVIDER" = "kimi_cli" ] && echo "    MEET_BACKEND=kimi python3 scripts/wolfpack-meet-agent.py   # join the commons chatter"
[ "$MEET_OK" = "1" ] && [ "$PROVIDER" != "kimi_cli" ] && echo "    python3 scripts/wolfpack-meet-agent.py   # join the commons (uses local ollama)"
echo
echo "  Watch the floor: https://buildyourwolfpack.com/pages/meeting"
