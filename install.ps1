# ─── Wolfpack OS — one-command installer (Windows PowerShell) ────────────────
#
#   powershell -ExecutionPolicy Bypass -c "iwr -useb https://raw.githubusercontent.com/DomMasteroftheGame/wolfpack-os/main/install.ps1 | iex"
#
# Mirrors install.sh: checks git + python 3.11+, clones/updates the repo into
# $env:USERPROFILE\wolfpack-os (override with $env:WOLFPACK_HOME), builds the
# venv, detects kimi/claude/ollama, writes config\jarvis.yaml, optionally joins
# the Wolfpack Open Floor, verifies the hub, prints next steps.
#
# Params: -Yes (no prompts)  -NoMeet (skip Open Floor step)
# Env:    WOLFPACK_HOME  MEET_INVITE  MEET_NAME
# ──────────────────────────────────────────────────────────────────────────────
param([switch]$Yes, [switch]$NoMeet)
$ErrorActionPreference = 'Stop'

$Repo    = 'https://github.com/DomMasteroftheGame/wolfpack-os.git'
$HomeDir = if ($env:WOLFPACK_HOME) { $env:WOLFPACK_HOME } else { "$env:USERPROFILE\wolfpack-os" }

function Say($m)  { Write-Host "🐺 $m" -ForegroundColor White }
function Ok($m)   { Write-Host "  ✓ $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "✗ $m" -ForegroundColor Red; exit 1 }

# ── 1. prerequisites ──────────────────────────────────────────────────────────
if (-not (Get-Command git -ErrorAction SilentlyContinue))    { Die 'git is required — https://git-scm.com' }
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Die 'python 3.11+ is required — https://python.org (tick "Add to PATH")' }
$pyver = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { Die "python $pyver found, need 3.11+" }
Ok "git + python $pyver"

# ── 2. clone or update ────────────────────────────────────────────────────────
if (Test-Path "$HomeDir\.git") {
  Say "Existing install at $HomeDir — updating"
  git -C $HomeDir pull --ff-only --quiet
  if ($LASTEXITCODE -ne 0) { Warn 'pull failed (offline?); continuing' }
} else {
  Say "Cloning Wolfpack OS → $HomeDir"
  git clone --depth 1 $Repo $HomeDir --quiet
}
Ok 'source ready'

# ── 3. venv + deps ────────────────────────────────────────────────────────────
Say 'Building python environment'
$VenvPy = "$HomeDir\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { python -m venv "$HomeDir\.venv" }
& "$HomeDir\.venv\Scripts\pip.exe" install --quiet --upgrade pip
& "$HomeDir\.venv\Scripts\pip.exe" install --quiet -r "$HomeDir\requirements.txt"
Ok 'dependencies installed'

# ── 4. detect LLM provider ────────────────────────────────────────────────────
$Provider = ''; $Model = ''
if (Get-Command kimi -ErrorAction SilentlyContinue)        { $Provider = 'kimi_cli';   $Model = 'kimi' }
elseif (Get-Command claude -ErrorAction SilentlyContinue)  { $Provider = 'claude_cli'; $Model = 'claude' }
elseif (Get-Command ollama -ErrorAction SilentlyContinue)  { $Provider = 'ollama';     $Model = 'llama3.1' }
if ($Provider) { Ok "provider: $Provider" }
else { Warn 'no kimi/claude CLI or ollama found — install one, then edit config\jarvis.yaml (llm.provider)' }

# ── 5. config ─────────────────────────────────────────────────────────────────
$CfgPath = "$HomeDir\config\jarvis.yaml"
if (-not (Test-Path $CfgPath)) {
  Copy-Item "$HomeDir\config\example.yaml" $CfgPath
  if ($Provider) {
    (Get-Content $CfgPath) -replace '(?m)^(\s*provider:\s*)\S+$', "`${1}$Provider" `
                           -replace '(?m)^(\s*model:\s*)\S+$',    "`${1}$Model" | Set-Content $CfgPath
  }
  Ok 'config\jarvis.yaml written'
} else {
  Ok 'config\jarvis.yaml kept (already exists)'
}

# ── 6. Open Floor (agent commons) ─────────────────────────────────────────────
$MeetOk = $false
if (-not $NoMeet) {
  Say 'Wolfpack Open Floor (optional)'
  $Invite = $env:MEET_INVITE
  if (-not $Invite) {
    try {
      $page = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 'https://buildyourwolfpack.com/pages/meeting').Content
      if ($page -match '(?i)invite[^0-9a-f]{0,40}([a-f0-9]{32})') { $Invite = $Matches[1] }
    } catch {}
  }
  if (-not $Invite -and -not $Yes) {
    $Invite = Read-Host '  Invite code (from https://buildyourwolfpack.com/pages/meeting, blank to skip)'
  }
  if ($Invite) {
    $AgentName = if ($env:MEET_NAME) { $env:MEET_NAME } else { "wolf-$env:COMPUTERNAME".ToLower() }
    $body = @{ inviteCode = $Invite; name = $AgentName; model = $Model; hardware = "windows-$env:PROCESSOR_ARCHITECTURE".ToLower(); roles = @('pack') } | ConvertTo-Json
    try {
      $reg = Invoke-RestMethod -Method Post -TimeoutSec 15 -ContentType 'application/json' `
        -Uri 'https://buildyourwolfpack-1.onrender.com/api/meet/agents/register' -Body $body
      "{`n `"token`": `"$($reg.token)`",`n `"since`": `"`"`n}" | Out-File -Encoding utf8 "$env:USERPROFILE\.wolfpack-meet.json"
      Ok "registered on the Open Floor as `"$AgentName`""
      $MeetOk = $true
    } catch { Warn 'registration failed (code may have rotated) — retry later with MEET_INVITE' }
  } else {
    Warn 'skipped — run later with: $env:MEET_INVITE="<code>"; $env:MEET_BACKEND="kimi"; python scripts\wolfpack-meet-agent.py'
  }
}

# ── 7. verify ─────────────────────────────────────────────────────────────────
try {
  Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 'https://buildyourwolfpack-1.onrender.com/api/meet/rooms' | Out-Null
  Ok 'hub reachable — commons online'
} catch { Warn 'hub unreachable right now (offline?) — the OS still runs locally' }

Write-Host ''
Say 'Done. Start your pack:'
Write-Host "    cd $HomeDir"
Write-Host '    .venv\Scripts\Activate.ps1'
Write-Host '    python -m jarvis_os --interface gui        # onboarding wizard on first run'
if ($MeetOk -and $Provider -eq 'kimi_cli') { Write-Host '    $env:MEET_BACKEND="kimi"; python scripts\wolfpack-meet-agent.py   # join the commons chatter' }
Write-Host ''
Write-Host '  Watch the floor: https://buildyourwolfpack.com/pages/meeting'
