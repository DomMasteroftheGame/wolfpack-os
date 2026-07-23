"""Web GUI dashboard for Jarvis OS.

Install GUI extras:
    pip install -e '.[gui]'

Run with:
    python -m jarvis_os --interface gui
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from jarvis_os.config import Config, LLMConfig, load_config
from jarvis_os.core.runtime import Runtime
from jarvis_os.core.discovery import PeerDiscovery
from jarvis_os.core.inbox_bus import create_inbox_router
from jarvis_os.core.personas import get_persona, load_personas
from jarvis_os.core.user_profile import PROFILE_FILENAME, default_config_dir
from jarvis_os.core.voice_manager import VoiceManager
from jarvis_os.interfaces.gui import netboot_router, usb_router
from jarvis_os.llm.providers import get_provider

try:
    import uvicorn
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The web GUI requires uvicorn. Install with: pip install -e '.[gui]'"
    ) from exc

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

STATIC_DIR = Path(__file__).parent / "static"
ONBOARDING_FILE = STATIC_DIR / "onboarding.html"
COPILOT_STORE_DIR = Path(__file__).resolve().parents[3] / "data" / "copilot"
MAX_FILE_BYTES = 2 * 1024 * 1024  # file editor cap
PROVIDER_TEST_TIMEOUT = 30.0  # seconds; the wizard's provider round-trip never hangs the request

# Providers the first-run wizard can configure. `binary` is the CLI looked up on
# PATH (None = probe a local HTTP service instead); `model` is the harmless
# default written into the generated jarvis.yaml and used for the test round-trip.
ONBOARDING_PROVIDERS = [
    {"id": "claude_cli", "label": "Claude Code CLI (subscription)", "binary": "claude", "model": "sonnet"},
    {"id": "kimi_cli", "label": "Kimi Code CLI (subscription)", "binary": "kimi", "model": ""},
    {"id": "ollama", "label": "Ollama (local models)", "binary": None, "model": "llama3.2"},
]

# The seven wolves shown as pack toggle cards in the wizard (all on by default).
ONBOARDING_PACK = [
    {"key": "ceo", "label": "CEO", "codename": "Alpha"},
    {"key": "tech", "label": "Tech", "codename": "Sentinel"},
    {"key": "marketing", "label": "Marketing", "codename": ""},
    {"key": "finance", "label": "Finance", "codename": "Ledger"},
    {"key": "analytics", "label": "Analytics", "codename": "Tracker"},
    {"key": "bizdev", "label": "BizDev", "codename": "Cassius"},
    {"key": "events", "label": "Events", "codename": "Ranger"},
]


class GoalRequest(BaseModel):
    goal: str
    agent: str = "simple"
    task_id: str | None = None


class FileWriteRequest(BaseModel):
    path: str
    content: str


class DelegateRequest(BaseModel):
    goal: str
    agent: str = "simple"
    peer_url: str | None = None  # if omitted, auto-pick the least-loaded peer


class MemoryAddRequest(BaseModel):
    role: str
    content: str
    metadata: dict[str, Any] = {}
    source: str | None = None


class VoiceSettingsRequest(BaseModel):
    enabled: bool | None = None
    output_enabled: bool | None = None
    always_listening: bool | None = None
    persona_id: str | None = None
    wake_word: str | None = None
    voice_model: str | None = None
    whisper_model: str | None = None


class MemoryRecallRequest(BaseModel):
    query: str
    limit: int = 5


class ClusterMapRequest(BaseModel):
    goals: list[str]           # one independent task per entry
    agent: str = "simple"


class JobSubmitRequest(BaseModel):
    goals: list[str]           # enqueue one job per entry
    agent: str = "simple"


class JobClaimRequest(BaseModel):
    worker: str


class JobCompleteRequest(BaseModel):
    job_id: str
    worker: str
    result: Any = None
    error: str | None = None


class AuthCallbackRequest(BaseModel):
    provider: str
    token: str
    extra: dict[str, Any] = Field(default_factory=dict)


class FleetGoalRequest(BaseModel):
    goal: str
    agent: str = "simple"


class FleetCommandRequest(BaseModel):
    command: str
    timeout: int = 30


class FleetConfigRequest(BaseModel):
    updates: dict[str, Any]


class PackRotateRequest(BaseModel):
    kind: str


class PackExecRequest(BaseModel):
    command: str


class WifiRequest(BaseModel):
    enabled: bool


class WifiConnectRequest(BaseModel):
    ssid: str
    password: str = ""


class TerminalRequest(BaseModel):
    command: str
    cwd: str | None = None
    timeout: int = 30


class ProviderTestRequest(BaseModel):
    provider: str


class CopilotImportRequest(BaseModel):
    provider: str | None = None  # when set, an LLM pass refines the heuristic suggestions


class OnboardingCompleteRequest(BaseModel):
    operator: dict[str, Any]
    business: dict[str, Any]
    pack: dict[str, bool] = Field(default_factory=dict)
    provider: str
    integrations: dict[str, bool] = Field(default_factory=dict)


def _nmcli_split(line: str) -> list[str]:
    """Split an nmcli terse (-t) line on unescaped ':' and unescape '\\' sequences."""
    fields: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            buf.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            fields.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    fields.append("".join(buf))
    return fields


def _deep_merge(base: dict, updates: dict) -> dict:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _copilot_records(limit: int = 50) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read the Dom Copilot progress store: latest summary + the last `limit` events.

    Only the file tail is read so a long progress.jsonl stays cheap. Missing or
    unreadable files yield empty results — the caller answers {"found": false}.
    """
    latest: dict[str, Any] = {}
    latest_path = COPILOT_STORE_DIR / "latest.json"
    if latest_path.is_file():
        try:
            data = json.loads(latest_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                latest = data
        except (OSError, json.JSONDecodeError):
            latest = {}
    records: list[dict[str, Any]] = []
    progress_path = COPILOT_STORE_DIR / "progress.jsonl"
    if progress_path.is_file():
        try:
            with progress_path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 256 * 1024))
                tail = f.read().decode("utf-8", errors="replace")
        except OSError:
            tail = ""
        for line in tail.splitlines()[-limit:]:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return latest, records


def _copilot_heuristics(latest: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, str]:
    """Rule-based guesses for the wizard's business fields from copilot data.

    The store knows the player's startup (latest.startup / structured.startup),
    the copilot's last nudge (a decent proxy for the current goal), and free
    text that may mention a target audience or $ prices. Suggestions only —
    the operator edits before anything is saved.
    """
    texts = [str(r["text"]) for r in records if r.get("text")]
    structured = [r["structured"] for r in records if isinstance(r.get("structured"), dict)]

    sells = str(latest.get("startup") or "").strip()
    if not sells:
        for blob in reversed(structured):
            sells = str(blob.get("startup") or "").strip()
            if sells:
                break

    goal = str(latest.get("last_nudge") or "").strip()
    if not goal and texts:
        goal = texts[-1].strip()

    customer = ""
    for text in reversed(texts):
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            lowered = sentence.lower()
            if any(phrase in lowered for phrase in ("target audience", "target customer", "ideal customer")):
                customer = sentence.strip().rstrip("?")
                break
        if customer:
            break

    amounts: list[str] = []
    for text in texts:
        for amount in re.findall(r"\$\d[\d,]*(?:\.\d+)?", text):
            if amount not in amounts:
                amounts.append(amount)

    return {
        "sells": sells,
        "customer": customer,
        "prices": ", ".join(amounts[:5]),
        "goal": goal,
    }


def _wizard_jarvis_config(provider: dict[str, Any]) -> dict[str, Any]:
    """jarvis.yaml content for a completed wizard, modeled on config/example.yaml."""
    cli_provider = provider["id"] in ("claude_cli", "kimi_cli")
    return {
        "llm": {
            "provider": provider["id"],
            "model": provider["model"],
            "api_key": "",
            "base_url": None,
            "temperature": 0.7,
            "max_tokens": 4096,
        },
        # The butler persona stays off; the operator's business profile is
        # injected into agent prompts from user_profile.yaml instead.
        "personality": {"enabled": False, "name": "Jarvis"},
        "safety": {
            "policy_file": "config/policy.yaml",
            "audit_file": "data/audit.log",
            "permissive": True,
            "allow_sudo": False,
            "allow_network": False,
            "allowed_paths": ["~", "/tmp"],
            "blocked_commands": ["rm -rf /", "mkfs", "dd", ":(){ :|:& };:"],
        },
        "scheduler": {"enabled": True, "check_interval_seconds": 1},
        "autonomy": {"enabled": True, "max_iterations": 50, "reflection_enabled": True},
        "network": {
            "gui_host": "127.0.0.1",
            "gui_port": 8080,
            "discovery_enabled": True,
            "discovery_port": 47600,
            "delegation_token": None,
        },
        "memory": {
            "mode": "local",
            "hub_url": None,
            "embed_url": None,
            "embed_model": "nomic-embed-text",
            # The CLI providers have no embeddings endpoint -> keyword recall only.
            "semantic": not cli_provider,
        },
        "cluster": {"worker_enabled": False, "queue_url": None, "max_concurrent": 2, "poll_interval": 2.0},
        "external_skills_dir": "./skills",
        "embedded_app": {
            "enabled": False,
            "url": "https://buildyourwolfpack.com/pages/game#/select-startup",
            "mode": "copilot",
            "cdp_url": None,
        },
        "memory_db": "data/memory.db",
        "log_level": "INFO",
        "share": {"enabled": False, "path": None, "poll_interval": 3.0},
    }


class WebGUI:
    """FastAPI-based web dashboard for the Jarvis OS runtime."""

    def __init__(
        self,
        runtime: Runtime,
        default_agent: str = "simple",
        config_path: Path | None = None,
    ):
        self.runtime = runtime
        self.default_agent = default_agent
        self.config_path = Path(config_path) if config_path else Path("config/jarvis.yaml")
        self.gui_port = 8080
        # live per-task progress for the wolf-hunt console (task_id -> {frac, state, agent, ts})
        self.progress: dict[str, dict[str, Any]] = {}
        self.discovery = PeerDiscovery(self._discovery_info)
        # Hub services live on Runtime so they run in CLI/voice/GUI modes.
        self.jobqueue = runtime.jobqueue
        self.worker = runtime.worker
        self.sharebus = runtime.sharebus
        self.inbox = runtime.inbox
        self.mesh = runtime.mesh
        voice_defaults = self.runtime.config.voice.model_dump() if hasattr(self.runtime.config.voice, "model_dump") else dict(self.runtime.config.voice)
        self.voice = VoiceManager(
            self.config_path.parent,
            voice_url=f"http://127.0.0.1:{self.runtime.config.network.gui_port}/api/voice?say=0",
            defaults=voice_defaults,
        )
        self.app = FastAPI(title="Jarvis OS Dashboard")
        self.app.include_router(create_inbox_router(self.inbox, self.runtime.config.inbox.token))
        self.app.include_router(netboot_router.router)
        self.app.include_router(usb_router.router)
        self._register_routes()

    def _discovery_info(self) -> dict[str, Any]:
        return {
            "name": self.runtime.config.personality.name,
            "gui_port": self.gui_port,
            "provider": self.runtime.config.llm.provider,
            "model": self.runtime.config.llm.model,
        }

    @staticmethod
    def _peer_ip(url: str | None) -> str:
        if not url:
            return "?"
        try:
            return urlparse(url).hostname or url
        except ValueError:
            return url

    def _fleet_auth(self, request: Request) -> bool:
        """Allow localhost or requests bearing the configured delegation token."""
        if request.client and request.client.host == "127.0.0.1":
            return True
        token = self.runtime.config.network.delegation_token
        if not token:
            return False
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            auth = auth[7:].strip()
        return auth == token

    async def _nmcli(self, *args: str, timeout: float = 10.0) -> tuple[int, str, str]:
        """Run an nmcli command. Returns (returncode, stdout, stderr); rc=-2 if nmcli is missing."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "nmcli", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return -2, "", "nmcli not found"
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return -1, "", "nmcli timed out"
        return (
            proc.returncode,
            out.decode("utf-8", errors="replace").strip(),
            err.decode("utf-8", errors="replace").strip(),
        )

    async def _pack_rotate(self, *args: str, timeout: float = 180.0) -> dict[str, Any]:
        """Run appliance/pack-rotate.sh via sudo. Returns {"ok": bool, "output": str}."""
        script = Path(__file__).resolve().parents[3] / "appliance" / "pack-rotate.sh"
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-n", "bash", str(script), *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError) as exc:
            return {"ok": False, "output": f"failed to launch pack-rotate.sh: {exc}"}
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"ok": False, "output": f"pack-rotate.sh timed out after {int(timeout)}s"}
        output = (out.decode("utf-8", errors="replace") + err.decode("utf-8", errors="replace")).strip()
        return {"ok": proc.returncode == 0, "output": output}

    async def _run_terminal(self, command: str, cwd: str | None, timeout: int) -> dict[str, Any]:
        """Run a shell command for the web terminal, subject to the safety policy."""
        command = command.strip()
        if not command:
            return {"ok": False, "error": "No command provided", "cwd": cwd or str(Path.cwd())}

        allowed, reason = self.runtime.policy._check_shell(command)
        if not allowed:
            return {"ok": False, "error": f"Policy denied: {reason}", "cwd": cwd or str(Path.cwd())}

        working_dir = Path(cwd).expanduser() if cwd else Path.cwd()
        try:
            working_dir = working_dir.resolve()
            if not working_dir.is_dir():
                working_dir = Path.cwd()
        except (OSError, RuntimeError):
            working_dir = Path.cwd()

        self.runtime.audit.record("terminal", {"command": command, "cwd": str(working_dir)})

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(working_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=float(timeout))
            except asyncio.TimeoutError:
                proc.kill()
                return {
                    "ok": False,
                    "error": f"Command timed out after {timeout}s",
                    "stdout": "",
                    "stderr": "",
                    "returncode": -1,
                    "cwd": str(working_dir),
                }
            return {
                "ok": proc.returncode == 0,
                "stdout": out.decode("utf-8", errors="replace"),
                "stderr": err.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
                "cwd": str(working_dir),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "cwd": str(working_dir)}

    async def _wifi_state(self) -> dict[str, Any]:
        """Report Wi-Fi radio state and active SSID via nmcli (Linux/NetworkManager only)."""
        if platform.system() != "Linux":
            return {"available": False, "enabled": False, "ssid": None,
                    "reason": f"Wi-Fi control needs Linux/NetworkManager (host is {platform.system()})."}
        rc, out, err = await self._nmcli("-t", "radio", "wifi")
        if rc == -2:
            return {"available": False, "enabled": False, "ssid": None,
                    "reason": "NetworkManager (nmcli) is not installed on this node."}
        if rc != 0:
            return {"available": False, "enabled": False, "ssid": None,
                    "reason": err or "nmcli radio query failed"}
        enabled = out.strip().lower() == "enabled"
        ssid = None
        if enabled:
            rc2, out2, _ = await self._nmcli("-t", "-f", "active,ssid", "dev", "wifi")
            if rc2 == 0:
                for line in out2.splitlines():
                    if line.startswith("yes:"):
                        ssid = line[4:].replace("\\:", ":").strip() or None
                        break
        return {"available": True, "enabled": enabled, "ssid": ssid, "reason": None}

    async def _wifi_scan(self) -> dict[str, Any]:
        """List nearby Wi-Fi networks (deduped by SSID, strongest signal wins)."""
        if platform.system() != "Linux":
            return {"available": False, "networks": [],
                    "reason": f"Wi-Fi control needs Linux/NetworkManager (host is {platform.system()})."}
        rc, out, err = await self._nmcli(
            "-t", "-f", "IN-USE,SIGNAL,SECURITY,SSID", "dev", "wifi", "list", "--rescan", "auto",
            timeout=20.0,
        )
        if rc == -2:
            return {"available": False, "networks": [], "reason": "NetworkManager (nmcli) is not installed on this node."}
        if rc != 0:
            return {"available": False, "networks": [], "reason": err or "Wi-Fi scan failed"}
        nets: dict[str, dict[str, Any]] = {}
        for line in out.splitlines():
            parts = _nmcli_split(line)
            if len(parts) < 4:
                continue
            inuse, signal, security, ssid = parts[0], parts[1], parts[2], parts[3]
            if not ssid:
                continue  # hidden network
            active = inuse.strip() == "*"
            try:
                sig = int(signal)
            except ValueError:
                sig = 0
            existing = nets.get(ssid)
            if existing is None or sig > existing["signal"]:
                nets[ssid] = {"ssid": ssid, "signal": sig, "security": (security or "").strip(), "active": active}
            if active:
                nets[ssid]["active"] = True
        networks = sorted(nets.values(), key=lambda n: (0 if n["active"] else 1, -n["signal"]))
        return {"available": True, "networks": networks, "reason": None}

    async def _connection_uuid_for_ssid(self, ssid: str) -> str | None:
        """Return the UUID of an existing NetworkManager connection whose SSID matches."""
        rc, out, _ = await self._nmcli("-t", "-f", "NAME,UUID,TYPE", "connection", "show")
        if rc != 0 or not out:
            return None
        target = ssid.strip().lower()
        for line in out.splitlines():
            parts = _nmcli_split(line)
            if len(parts) < 3 or parts[2] != "802-11-wireless":
                continue
            if parts[0].strip().lower() == target:
                return parts[1].strip() or None
        return None

    async def _wifi_connect(self, ssid: str, password: str) -> dict[str, Any]:
        """Connect to an SSID via nmcli.

        Prefers activating an existing saved connection profile; if none exists,
        creates a new one. This avoids duplicate profiles and respects netplan/system
        connections that the OS already knows about.
        """
        if not ssid:
            return {"ok": False, "error": "No SSID provided"}

        uuid = await self._connection_uuid_for_ssid(ssid)
        if uuid:
            # Existing profile: update password if supplied, then activate.
            if password:
                mod_rc, _, mod_err = await self._nmcli(
                    "connection", "modify", uuid,
                    "wifi-sec.key-mgmt", "wpa-psk",
                    "wifi-sec.psk", password,
                    timeout=15.0,
                )
                if mod_rc != 0:
                    return {"ok": False, "error": mod_err or f"Failed to update password for {ssid}"}
            up_rc, up_out, up_err = await self._nmcli("connection", "up", uuid, timeout=45.0)
            if up_rc != 0:
                return {"ok": False, "error": (up_err or up_out or f"Failed to activate {ssid}").splitlines()[-1]}
            return {"ok": True, "detail": up_out or f"Activated saved connection {ssid}"}

        # No existing profile: scan and connect directly.
        await self._nmcli("dev", "wifi", "rescan", timeout=15.0)
        args = ["dev", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
        rc, out, err = await self._nmcli(*args, timeout=45.0)
        if rc != 0:
            detail = (err or out or "connection failed").splitlines()[-1] if (err or out) else "connection failed"
            if "insufficient privileges" in detail.lower() or "permission denied" in detail.lower():
                detail += " ( kiosk mode may need the Wi-Fi polkit rule — see docs/WIFI.md )"
            return {"ok": False, "error": detail}
        return {"ok": True, "detail": out}

    def _wizard_required(self) -> bool:
        """First-run flag: the wizard runs until user_profile.yaml exists."""
        return not (default_config_dir() / PROFILE_FILENAME).is_file()

    async def _detect_providers(self) -> list[dict[str, Any]]:
        """Detect which wizard LLM providers are usable on this machine."""
        ollama_detected = False
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                resp = await client.get("http://localhost:11434/api/version")
                ollama_detected = resp.status_code == 200
        except Exception:  # noqa: BLE001 - any failure means "not running"
            ollama_detected = False
        detected = {
            "claude_cli": shutil.which("claude") is not None,
            "kimi_cli": shutil.which("kimi") is not None,
            "ollama": ollama_detected,
        }
        default = next((pid for pid in ("claude_cli", "kimi_cli", "ollama") if detected[pid]), "claude_cli")
        return [
            {"id": p["id"], "label": p["label"], "detected": detected[p["id"]], "default": p["id"] == default}
            for p in ONBOARDING_PROVIDERS
        ]

    async def _copilot_llm_suggestions(
        self,
        provider_id: str,
        latest: dict[str, Any],
        records: list[dict[str, Any]],
        heuristic: dict[str, str],
    ) -> dict[str, str]:
        """Refine the heuristic copilot suggestions with one LLM call. Falls back
        to the heuristics on any error (unknown provider, timeout, bad JSON)."""
        meta = next((p for p in ONBOARDING_PROVIDERS if p["id"] == provider_id), None)
        if meta is None:
            return heuristic
        excerpt = json.dumps({"latest": latest, "recent": records[-20:]}, ensure_ascii=False)[:6000]
        prompt = (
            "From this business-simulator copilot log, infer the player's real-world business and reply "
            "with ONLY a JSON object (no markdown, no commentary) with the keys sells, customer, prices, "
            "goal: what they sell, their target customer, their prices/offers, and their current #1 goal. "
            "Use an empty string for anything unknown.\n\n" + excerpt
        )
        try:
            llm = get_provider(LLMConfig(provider=meta["id"], model=meta["model"]))
            resp = await asyncio.wait_for(
                llm.chat([{"role": "user", "content": prompt}]),
                timeout=PROVIDER_TEST_TIMEOUT,
            )
            match = re.search(r"\{.*\}", (resp.get("content") or ""), re.DOTALL)
            data = json.loads(match.group(0)) if match else None
            if not isinstance(data, dict):
                return heuristic
        except Exception:  # noqa: BLE001 - suggestions are best-effort
            return heuristic
        merged = dict(heuristic)
        for key in ("sells", "customer", "prices", "goal"):
            value = str(data.get(key) or "").strip()
            if value:
                merged[key] = value
        return merged

    def _register_routes(self) -> None:
        @self.app.get("/")
        async def desktop():  # noqa: WPS430
            if self._wizard_required() and ONBOARDING_FILE.exists():
                return FileResponse(ONBOARDING_FILE, media_type="text/html")
            desktop_file = STATIC_DIR / "desktop.html"
            if desktop_file.exists():
                return FileResponse(desktop_file, media_type="text/html")
            return HTMLResponse(DASHBOARD_HTML)

        @self.app.get("/onboarding")
        async def onboarding_page():  # noqa: WPS430
            # Direct preview of the first-run wizard (also reachable after completion).
            if ONBOARDING_FILE.exists():
                return FileResponse(ONBOARDING_FILE, media_type="text/html")
            return JSONResponse(status_code=404, content={"error": "onboarding page not found"})

        @self.app.get("/static/{name}")
        async def static_file(name: str):  # noqa: WPS430
            f = STATIC_DIR / Path(name).name  # basename only (no path traversal)
            if f.is_file():
                return FileResponse(f)
            return JSONResponse(status_code=404, content={"error": "not found"})

        @self.app.get("/classic", response_class=HTMLResponse)
        async def classic_dashboard() -> str:  # noqa: WPS430
            return DASHBOARD_HTML

        @self.app.get("/api/config")
        async def get_config() -> dict[str, Any]:  # noqa: WPS430
            data = self.runtime.config.model_dump()
            llm = data.get("llm", {})
            llm["api_key_set"] = bool(llm.get("api_key"))
            llm["api_key"] = ""  # never send the key to the browser
            return data

        @self.app.post("/api/config")
        async def update_config(payload: dict[str, Any]) -> Any:  # noqa: WPS430
            current = self.runtime.config.model_dump()
            # blank api_key in the form means "keep the existing key"
            llm_updates = payload.get("llm")
            if isinstance(llm_updates, dict):
                llm_updates.pop("api_key_set", None)
                if not llm_updates.get("api_key"):
                    llm_updates.pop("api_key", None)
            merged = _deep_merge(current, payload)
            try:
                new_config = Config(**merged)
                self.runtime.apply_config(new_config)
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(status_code=400, content={"error": str(exc)})
            persisted = new_config.model_dump()
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(persisted, f, sort_keys=False, allow_unicode=True)
            except OSError as exc:
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Applied to runtime but failed to save {self.config_path}: {exc}"},
                )
            return {"ok": True, "message": "Settings applied and saved."}

        # --- First-run onboarding wizard ---
        @self.app.get("/api/onboarding/status")
        async def onboarding_status() -> dict[str, Any]:  # noqa: WPS430
            completed = not self._wizard_required()
            return {"wizard_required": not completed, "completed": completed}

        @self.app.get("/api/onboarding/providers")
        async def onboarding_providers() -> list[dict[str, Any]]:  # noqa: WPS430
            return await self._detect_providers()

        @self.app.post("/api/onboarding/test-provider")
        async def onboarding_test_provider(payload: ProviderTestRequest) -> Any:  # noqa: WPS430
            meta = next((p for p in ONBOARDING_PROVIDERS if p["id"] == payload.provider), None)
            if meta is None:
                return JSONResponse(status_code=400, content={"error": f"Unknown provider: {payload.provider}"})
            try:
                llm = get_provider(LLMConfig(provider=meta["id"], model=meta["model"]))
                resp = await asyncio.wait_for(
                    llm.chat([{"role": "user", "content": "Reply with exactly one word: ready"}]),
                    timeout=PROVIDER_TEST_TIMEOUT,
                )
                reply = (resp.get("content") or "").strip()
                return {"ok": True, "provider": payload.provider, "reply": reply[:500]}
            except asyncio.TimeoutError:
                return {"ok": False, "provider": payload.provider,
                        "error": f"Timed out after {int(PROVIDER_TEST_TIMEOUT)}s"}
            except Exception as exc:  # noqa: BLE001 - surface the CLI/API error to the wizard
                return {"ok": False, "provider": payload.provider, "error": str(exc)}

        @self.app.post("/api/onboarding/copilot-import")
        async def onboarding_copilot_import(payload: CopilotImportRequest) -> dict[str, Any]:  # noqa: WPS430
            latest, records = _copilot_records(limit=50)
            if not latest and not records:
                return {"found": False}
            suggestions = _copilot_heuristics(latest, records)
            source = "heuristic"
            if payload.provider:
                refined = await self._copilot_llm_suggestions(payload.provider, latest, records, suggestions)
                if refined != suggestions:
                    source = f"llm:{payload.provider}"
                suggestions = refined
            return {"found": True, "suggestions": suggestions, "source": source}

        @self.app.post("/api/onboarding/complete")
        async def onboarding_complete(payload: OnboardingCompleteRequest) -> Any:  # noqa: WPS430
            errors: list[str] = []
            name = str(payload.operator.get("name") or "").strip()
            sells = str(payload.business.get("sells") or "").strip()
            if not name:
                errors.append("operator.name is required")
            if not sells:
                errors.append("business.sells is required")
            provider = next((p for p in ONBOARDING_PROVIDERS if p["id"] == payload.provider), None)
            if provider is None:
                errors.append("provider must be one of: " + ", ".join(p["id"] for p in ONBOARDING_PROVIDERS))
            if errors:
                return JSONResponse(status_code=400, content={"error": "; ".join(errors)})

            target_dir = default_config_dir()
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return JSONResponse(status_code=500, content={"error": f"Cannot create {target_dir}: {exc}"})

            jarvis_path = target_dir / "jarvis.yaml"
            profile_path = target_dir / PROFILE_FILENAME
            profile_doc = {
                "operator": {
                    "name": name,
                    "timezone": str(payload.operator.get("timezone") or "").strip(),
                },
                "business": {
                    "sells": sells,
                    "customer": str(payload.business.get("customer") or "").strip(),
                    "prices": str(payload.business.get("prices") or "").strip(),
                    "goal": str(payload.business.get("goal") or "").strip(),
                },
                "pack": {w["key"]: bool(payload.pack.get(w["key"], True)) for w in ONBOARDING_PACK},
                "provider": provider["id"],
                "integrations": {
                    key: bool(payload.integrations.get(key, False))
                    for key in ("google", "shopify", "instagram", "tiktok")
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                with open(jarvis_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(_wizard_jarvis_config(provider), f, sort_keys=False, allow_unicode=True)
            except OSError as exc:
                return JSONResponse(status_code=500, content={"error": f"Failed to write {jarvis_path}: {exc}"})
            try:
                load_config(jarvis_path)
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(status_code=500, content={"error": f"Generated {jarvis_path} failed validation: {exc}"})
            # The profile is written last: its presence marks the wizard complete.
            try:
                with open(profile_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(profile_doc, f, sort_keys=False, allow_unicode=True)
            except OSError as exc:
                return JSONResponse(status_code=500, content={"error": f"Failed to write {profile_path}: {exc}"})
            self.runtime.audit.record("onboarding_complete",
                                      {"provider": provider["id"], "config_dir": str(target_dir)})
            return {"ok": True, "files": [str(jarvis_path), str(profile_path)]}

        @self.app.get("/api/system")
        async def system_stats() -> dict[str, Any]:  # noqa: WPS430
            info: dict[str, Any] = {
                "platform": f"{platform.system()} {platform.release()}",
                "hostname": platform.node(),
                "python": platform.python_version(),
                "provider": self.runtime.config.llm.provider,
                "model": self.runtime.config.llm.model,
                "permissive": self.runtime.config.safety.permissive,
            }
            if psutil is not None:
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage(os.path.abspath(os.sep))
                info.update({
                    "cpu_percent": psutil.cpu_percent(interval=0.1),
                    "cpu_count": psutil.cpu_count(),
                    "mem_total": mem.total,
                    "mem_used": mem.used,
                    "mem_percent": mem.percent,
                    "disk_total": disk.total,
                    "disk_used": disk.used,
                    "disk_percent": disk.percent,
                    "process_count": len(psutil.pids()),
                    "uptime_seconds": int(time.time() - psutil.boot_time()),
                })
            return info

        @self.app.get("/api/wifi")
        async def wifi_status() -> dict[str, Any]:  # noqa: WPS430
            return await self._wifi_state()

        @self.app.post("/api/wifi")
        async def wifi_set(payload: WifiRequest) -> dict[str, Any]:  # noqa: WPS430
            state = await self._wifi_state()
            if not state.get("available"):
                return JSONResponse(status_code=400, content={"error": state.get("reason") or "Wi-Fi control unavailable"})
            action = "on" if payload.enabled else "off"
            self.runtime.audit.record("wifi_toggle", {"enabled": payload.enabled})
            rc, _out, err = await self._nmcli("radio", "wifi", action, timeout=15.0)
            if rc != 0:
                return JSONResponse(status_code=500, content={"error": err or f"Failed to turn Wi-Fi {action}"})
            await asyncio.sleep(1.0)  # let the radio settle before re-reading state
            return await self._wifi_state()

        @self.app.get("/api/wifi/scan")
        async def wifi_scan_route() -> dict[str, Any]:  # noqa: WPS430
            return await self._wifi_scan()

        @self.app.post("/api/wifi/connect")
        async def wifi_connect_route(payload: WifiConnectRequest) -> dict[str, Any]:  # noqa: WPS430
            state = await self._wifi_state()
            if not state.get("available"):
                return JSONResponse(status_code=400, content={"error": state.get("reason") or "Wi-Fi control unavailable"})
            self.runtime.audit.record("wifi_connect", {"ssid": payload.ssid})
            res = await self._wifi_connect(payload.ssid, payload.password)
            if not res.get("ok"):
                return JSONResponse(status_code=500, content={"error": res.get("error") or "connection failed"})
            await asyncio.sleep(1.5)  # let association + DHCP settle
            new_state = await self._wifi_state()
            new_state["connected_to"] = payload.ssid
            return new_state

        @self.app.get("/api/skills")
        async def list_skills() -> list[dict[str, Any]]:  # noqa: WPS430
            return [
                {"name": s.name, "description": s.description, "schema": s.schema}
                for s in self.runtime.registry.list()
            ]

        @self.app.post("/api/terminal")
        async def terminal_run(payload: TerminalRequest) -> dict[str, Any]:  # noqa: WPS430
            """Execute a shell command from the web terminal, gated by the safety policy."""
            result = await self._run_terminal(payload.command, payload.cwd, payload.timeout)
            if not result.get("ok") and result.get("error", "").startswith("Policy denied"):
                return JSONResponse(status_code=403, content={"error": result["error"]})
            return result

        @self.app.post("/api/auth/callback")
        async def auth_callback(payload: AuthCallbackRequest) -> dict[str, Any]:  # noqa: WPS430
            """Store a provider token supplied by the user after interactive login."""
            skill = self.runtime.registry.get("credentials")
            if skill is None:
                return JSONResponse(status_code=500, content={"error": "credentials skill not found"})
            try:
                values: dict[str, str] = {payload.provider: payload.token}
                for field_name, field_value in (payload.extra or {}).items():
                    raw = field_value.get("value") if isinstance(field_value, dict) else str(field_value)
                    if raw:
                        values[f"{payload.provider}_{field_name}"] = raw
                result = await skill.run(action="set", provider=payload.provider, values=values)
                return {"ok": True, "provider": payload.provider, "result": result}
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(status_code=500, content={"error": f"Failed to store token: {exc}"})

        @self.app.post("/api/update_code")
        async def update_code_local() -> dict[str, Any]:  # noqa: WPS430
            """Trigger a self-update from the fleet share and restart in the background."""
            is_windows = sys.platform == "win32"
            share_root = r"\\CASHMONEY\Public\JarvisOS"
            try:
                if is_windows:
                    script = os.path.join(share_root, "Update-JarvisOS.ps1")
                    if not os.path.exists(script):
                        return JSONResponse(
                            status_code=500,
                            content={"error": f"Update script not found: {script}"},
                        )
                    cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script]
                    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so the updater survives our restart.
                    flags = 0x00000008 | 0x00000200
                    proc = subprocess.Popen(
                        cmd,
                        creationflags=flags,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                    )
                else:
                    script = "/mnt/jarvis-share/Update-JarvisOS.sh"
                    if not os.path.exists(script):
                        return JSONResponse(
                            status_code=500,
                            content={"error": f"Update script not found: {script}"},
                        )
                    cmd = ["bash", script]
                    proc = subprocess.Popen(
                        cmd,
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                    )
                return {
                    "ok": True,
                    "pid": proc.pid,
                    "script": script,
                    "note": "Update started. This Jarvis OS node will restart shortly.",
                }
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(status_code=500, content={"error": f"Failed to start update: {exc}"})

        @self.app.get("/api/files")
        async def list_files(path: str = "") -> Any:  # noqa: WPS430
            target = Path(path).expanduser() if path else Path.cwd()
            try:
                target = target.resolve()
                if not target.is_dir():
                    return JSONResponse(status_code=400, content={"error": f"Not a directory: {target}"})
                entries = []
                for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
                    try:
                        stat = entry.stat()
                        entries.append({
                            "name": entry.name,
                            "is_dir": entry.is_dir(),
                            "size": stat.st_size if entry.is_file() else None,
                            "modified": stat.st_mtime,
                        })
                    except OSError:
                        continue
            except (OSError, PermissionError) as exc:
                return JSONResponse(status_code=400, content={"error": str(exc)})
            return {"path": str(target), "parent": str(target.parent) if target.parent != target else None, "entries": entries}

        @self.app.get("/api/file")
        async def read_file(path: str) -> Any:  # noqa: WPS430
            target = Path(path).expanduser()
            try:
                target = target.resolve()
                if not target.is_file():
                    return JSONResponse(status_code=404, content={"error": f"Not a file: {target}"})
                if target.stat().st_size > MAX_FILE_BYTES:
                    return JSONResponse(status_code=400, content={"error": "File too large for the editor (2 MB cap)."})
                content = target.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError) as exc:
                return JSONResponse(status_code=400, content={"error": str(exc)})
            return {"path": str(target), "content": content}

        @self.app.post("/api/file")
        async def write_file(payload: FileWriteRequest) -> Any:  # noqa: WPS430
            target = Path(payload.path).expanduser()
            try:
                target = target.resolve()
                target.write_text(payload.content, encoding="utf-8")
            except (OSError, PermissionError) as exc:
                return JSONResponse(status_code=400, content={"error": str(exc)})
            return {"ok": True, "path": str(target)}

        @self.app.post("/goal")
        async def post_goal(payload: GoalRequest, say: bool = True) -> dict[str, Any]:  # noqa: WPS430
            agent = payload.agent if payload.agent in {"simple", "react", "codeact", "autonomous"} else self.default_agent
            tid = payload.task_id
            on_step = None
            if tid:
                # drop finished entries older than 2 min so the map can't grow unbounded
                for k in [k for k, v in list(self.progress.items())
                          if v.get("state") in {"done", "failed"} and time.time() - v.get("ts", 0) > 120]:
                    self.progress.pop(k, None)
                self.progress[tid] = {"frac": 0.0, "state": "running", "agent": agent, "ts": time.time()}

                def on_step(frac: float, _tid=tid, _agent=agent) -> None:  # noqa: WPS430
                    self.progress[_tid] = {"frac": max(0.0, min(0.97, float(frac))),
                                           "state": "running", "agent": _agent, "ts": time.time()}
            try:
                result = await self.runtime.run_with_agent(payload.goal, agent_type=agent, on_step=on_step)
            except Exception as exc:  # noqa: BLE001
                if tid:
                    self.progress[tid] = {**self.progress.get(tid, {}), "state": "failed", "ts": time.time()}
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Failed to handle goal: {exc}"},
                )
            if tid:
                self.progress[tid] = {**self.progress.get(tid, {}), "frac": 1.0, "state": "done", "ts": time.time()}
            try:  # speak the reply aloud (WolfPack voice); the voice listener passes say=0
                if say:
                    from jarvis_os.core.voice import speak
                    speak(result.get("summary") or result.get("answer") or "")
            except Exception:  # noqa: BLE001
                pass
            return result

        @self.app.get("/api/goal/progress")
        async def goal_progress(id: str) -> dict[str, Any]:  # noqa: WPS430
            p = self.progress.get(id)
            if not p:
                return {"state": "unknown", "frac": 0.0}
            return {"frac": p.get("frac", 0.0), "state": p.get("state", "running"), "agent": p.get("agent")}

        def _voice_persona_message() -> dict[str, str] | None:
            """Use the voice-specific persona if set, otherwise fall back to runtime persona."""
            persona_id = self.voice.settings.get("persona_id")
            if persona_id:
                persona = get_persona(persona_id, self.runtime.config.personas_dir)
                if persona:
                    return {"role": "system", "content": persona.system_prompt}
            return self.runtime.persona_message()

        @self.app.post("/api/voice")
        async def voice_reply(payload: GoalRequest, say: bool = True) -> dict[str, Any]:  # noqa: WPS430
            # Fast conversational reply for the voice listener: ONE LLM call, short spoken answer.
            text = "Sorry, I didn't catch that."
            try:
                messages: list[dict[str, str]] = []
                persona = _voice_persona_message()
                if persona:
                    messages.append(persona)
                messages.append({
                    "role": "system",
                    "content": "You are answering out loud by voice. Reply in one or two short, natural spoken sentences. No lists, no markdown, no code.",
                })
                for m in self.runtime.memory.recent_messages(limit=6):
                    messages.append({"role": m["role"], "content": m["content"]})
                messages.append({"role": "user", "content": payload.goal})
                resp = await self.runtime.llm.chat(messages)
                text = (resp.get("content") or "").strip() or text
            except Exception as exc:  # noqa: BLE001
                text = f"Sorry, I hit a problem. {exc}"
            try:
                self.runtime.memory.add_message("user", payload.goal)
                self.runtime.memory.add_message("assistant", text)
            except Exception:  # noqa: BLE001
                pass
            if say and self.voice.settings.get("output_enabled", True):
                try:
                    from jarvis_os.core.voice import speak
                    speak(text)
                except Exception:  # noqa: BLE001
                    pass
            return {"summary": text, "answer": text}

        @self.app.get("/api/voice/settings")
        async def voice_settings() -> dict[str, Any]:  # noqa: WPS430
            personas = [
                {"id": p.id, "name": p.codename, "role": p.role}
                for p in load_personas(self.runtime.config.personas_dir).values()
            ]
            return {"settings": self.voice.settings, "personas": personas, "running": self.voice.is_running()}

        @self.app.get("/api/voice/voices")
        async def voice_voices() -> dict[str, Any]:  # noqa: WPS430
            from jarvis_os.core import voice
            voices_dir = Path(voice.voice_model()).parent
            if not voices_dir.is_dir():
                voices_dir = Path(__file__).resolve().parents[3] / "data" / "voices"
            voices = sorted(p.name for p in voices_dir.glob("*.onnx")) if voices_dir.is_dir() else []
            return {"voices": voices}

        @self.app.post("/api/voice/settings")
        async def voice_settings_update(payload: VoiceSettingsRequest) -> dict[str, Any]:  # noqa: WPS430
            settings = {k: v for k, v in payload.model_dump().items() if v is not None}
            old = self.voice.settings
            new = self.voice.update(settings)
            restart = False
            if any(new.get(k) != old.get(k) for k in ("wake_word", "output_enabled", "persona_id", "voice_model", "whisper_model")):
                restart = old.get("always_listening") or new.get("always_listening")
            if new.get("always_listening") and not old.get("always_listening"):
                self.voice.start()
            elif not new.get("always_listening") and old.get("always_listening"):
                self.voice.stop()
            elif restart and self.voice.is_running():
                self.voice.restart()
            return {"settings": new, "running": self.voice.is_running()}

        @self.app.post("/api/voice/start")
        async def voice_start() -> dict[str, Any]:  # noqa: WPS430
            return self.voice.start()

        @self.app.post("/api/voice/stop")
        async def voice_stop() -> dict[str, Any]:  # noqa: WPS430
            return self.voice.stop()

        @self.app.get("/memory")
        async def get_memory() -> list[dict[str, Any]]:  # noqa: WPS430
            return self.runtime.memory.recent_messages()

        @self.app.get("/audit")
        async def get_audit() -> list[str]:  # noqa: WPS430
            audit_path = Path(self.runtime.config.safety.audit_file)
            if not audit_path.exists():
                return []
            try:
                with open(audit_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError:
                return []
            return [line.rstrip("\n") for line in lines[-100:]]

        # --- Fleet control endpoints (remote troubleshoot + control) ---
        @self.app.get("/api/fleet/health")
        async def fleet_health(request: Request) -> dict[str, Any]:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            return {
                "status": "ok",
                "instance_id": self.discovery.instance_id,
                "name": self.runtime.config.personality.name,
                "uptime_seconds": int(time.time() - psutil.boot_time()) if psutil else None,
            }

        @self.app.get("/api/fleet/system")
        async def fleet_system(request: Request) -> dict[str, Any]:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            info: dict[str, Any] = {
                "platform": f"{platform.system()} {platform.release()}",
                "hostname": platform.node(),
                "python": platform.python_version(),
                "provider": self.runtime.config.llm.provider,
                "model": self.runtime.config.llm.model,
                "permissive": self.runtime.config.safety.permissive,
            }
            if psutil is not None:
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage(os.path.abspath(os.sep))
                info.update({
                    "cpu_percent": psutil.cpu_percent(interval=0.1),
                    "cpu_count": psutil.cpu_count(),
                    "mem_total": mem.total,
                    "mem_used": mem.used,
                    "mem_percent": mem.percent,
                    "disk_total": disk.total,
                    "disk_used": disk.used,
                    "disk_percent": disk.percent,
                    "process_count": len(psutil.pids()),
                    "uptime_seconds": int(time.time() - psutil.boot_time()),
                })
            return info

        @self.app.get("/api/fleet/audit")
        async def fleet_audit(request: Request) -> list[str]:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            audit_path = Path(self.runtime.config.safety.audit_file)
            if not audit_path.exists():
                return []
            try:
                with open(audit_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError:
                return []
            return [line.rstrip("\n") for line in lines[-100:]]

        @self.app.post("/api/fleet/goal")
        async def fleet_goal(request: Request, payload: FleetGoalRequest) -> dict[str, Any]:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            try:
                agent = payload.agent if payload.agent in {"simple", "react", "codeact", "autonomous"} else self.default_agent
                return await self.runtime.run_with_agent(payload.goal, agent_type=agent)
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(status_code=500, content={"error": f"Failed to run goal: {exc}"})

        @self.app.post("/api/fleet/command")
        async def fleet_command(request: Request, payload: FleetCommandRequest) -> dict[str, Any]:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            if not self.runtime.config.safety.allow_remote_shell:
                return JSONResponse(status_code=403, content={"error": "Remote shell is disabled. Set safety.allow_remote_shell=true to enable."})
            self.runtime.audit.record("remote_command", {"command": payload.command})
            try:
                proc = await asyncio.create_subprocess_shell(
                    payload.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=payload.timeout)
                return {
                    "command": payload.command,
                    "returncode": proc.returncode,
                    "stdout": stdout.decode("utf-8", errors="replace").strip(),
                    "stderr": stderr.decode("utf-8", errors="replace").strip(),
                }
            except asyncio.TimeoutError:
                return {"command": payload.command, "error": "Command timed out"}
            except Exception as exc:  # noqa: BLE001
                return {"command": payload.command, "error": str(exc)}

        @self.app.post("/api/fleet/restart")
        async def fleet_restart(request: Request) -> dict[str, Any]:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            if not self.runtime.config.safety.allow_remote_restart:
                return JSONResponse(status_code=403, content={"error": "Remote restart is disabled. Set safety.allow_remote_restart=true to enable."})
            self.runtime.audit.record("remote_restart", {})
            asyncio.get_running_loop().call_later(1.0, self._self_restart)
            return {"status": "restarting", "note": "Server will restart in ~1 second."}

        @self.app.get("/api/fleet/config")
        async def fleet_config_get(request: Request) -> dict[str, Any]:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            data = self.runtime.config.model_dump()
            llm = data.get("llm", {})
            llm["api_key_set"] = bool(llm.get("api_key"))
            llm["api_key"] = ""
            return data

        @self.app.post("/api/fleet/config")
        async def fleet_config_post(request: Request, payload: FleetConfigRequest) -> Any:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            current = self.runtime.config.model_dump()
            llm_updates = payload.updates.get("llm")
            if isinstance(llm_updates, dict):
                llm_updates.pop("api_key_set", None)
                if not llm_updates.get("api_key"):
                    llm_updates.pop("api_key", None)
            merged = _deep_merge(current, payload.updates)
            try:
                new_config = Config(**merged)
                self.runtime.apply_config(new_config)
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(status_code=400, content={"error": str(exc)})
            return {"ok": True, "message": "Config applied live. Persist manually if desired."}

        # --- Pack operations (wraps appliance/pack-rotate.sh) ---
        @self.app.get("/api/pack/status")
        async def pack_status(request: Request) -> Any:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            return await self._pack_rotate("status")

        @self.app.post("/api/pack/rotate")
        async def pack_rotate(request: Request, payload: PackRotateRequest) -> Any:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            if payload.kind not in {"token", "password"}:
                return JSONResponse(status_code=400, content={"error": "kind must be 'token' or 'password'"})
            self.runtime.audit.record("pack_rotate", {"kind": payload.kind})
            return await self._pack_rotate(payload.kind, "--yes")

        @self.app.post("/api/pack/exec")
        async def pack_exec(request: Request, payload: PackExecRequest) -> Any:  # noqa: WPS430
            if not self._fleet_auth(request):
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
            command = payload.command.strip()
            if not command:
                return JSONResponse(status_code=400, content={"error": "No command provided"})
            self.runtime.audit.record("pack_exec", {"command": command})
            return await self._pack_rotate("exec", command, "--yes")

        # --- Shared memory hub endpoints (sync defs => run in a threadpool so the
        #     embedding + DB work never blocks the event loop). ---
        @self.app.post("/api/memory/add")
        def memory_add(payload: MemoryAddRequest) -> dict[str, Any]:  # noqa: WPS430
            cfg = self.runtime._memory_settings()
            emb = self.runtime.memory._embed(payload.content, cfg)
            self.runtime.memory.local.add_message(
                payload.role, payload.content, payload.metadata,
                embedding=emb, source=payload.source,
            )
            return {"ok": True, "embedded": emb is not None}

        @self.app.post("/api/memory/recall")
        def memory_recall(payload: MemoryRecallRequest) -> list[dict[str, Any]]:  # noqa: WPS430
            cfg = self.runtime._memory_settings()
            return self.runtime.memory._local_recall(payload.query, payload.limit, cfg)

        @self.app.get("/api/memory/recent")
        def memory_recent(limit: int = 20) -> list[dict[str, Any]]:  # noqa: WPS430
            return self.runtime.memory.local.recent_messages(limit)

        @self.app.get("/api/memory/stats")
        def memory_stats() -> dict[str, Any]:  # noqa: WPS430
            cfg = self.runtime.config.memory
            return {
                **self.runtime.memory.local.stats(),
                "mode": cfg.mode,
                "hub_url": cfg.hub_url,
                "semantic": cfg.semantic,
                "embed_model": cfg.embed_model,
            }

        # --- Work-stealing job queue ---
        # claim/complete are served by the HUB and called by workers.
        @self.app.post("/api/jobs/claim")
        def jobs_claim(payload: JobClaimRequest) -> dict[str, Any]:  # noqa: WPS430
            return {"job": self.jobqueue.claim(payload.worker)}

        @self.app.post("/api/jobs/complete")
        def jobs_complete(payload: JobCompleteRequest) -> dict[str, Any]:  # noqa: WPS430
            ok = self.jobqueue.complete(payload.job_id, payload.worker, payload.result, payload.error)
            return {"ok": ok}

        # submit/list/stats forward to the hub when this node is a worker/client.
        @self.app.post("/api/jobs/submit")
        async def jobs_submit(payload: JobSubmitRequest) -> dict[str, Any]:  # noqa: WPS430
            hub = self.runtime.config.cluster.queue_url
            if hub:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(f"{hub.rstrip('/')}/api/jobs/submit", json=payload.model_dump())
                    return r.json()
            ids = [self.jobqueue.submit(g, payload.agent) for g in payload.goals]
            return {"submitted": ids}

        @self.app.get("/api/jobs/list")
        async def jobs_list() -> Any:  # noqa: WPS430
            hub = self.runtime.config.cluster.queue_url
            if hub:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    return (await client.get(f"{hub.rstrip('/')}/api/jobs/list")).json()
            return self.jobqueue.list()

        @self.app.get("/api/jobs/stats")
        async def jobs_stats() -> Any:  # noqa: WPS430
            hub = self.runtime.config.cluster.queue_url
            if hub:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    return (await client.get(f"{hub.rstrip('/')}/api/jobs/stats")).json()
            return self.jobqueue.stats()

        # --- Cluster: aggregate compute view + parallel fan-out ---
        @self.app.get("/api/cluster/info")
        async def cluster_info() -> dict[str, Any]:  # noqa: WPS430
            self_cores = psutil.cpu_count() if psutil else None
            nodes = [{
                "name": self.runtime.config.personality.name + " (self)",
                "ip": self.discovery.lan_ip,
                "cores": self_cores,
                "cpu_percent": psutil.cpu_percent(interval=None) if psutil else None,
                "model": self.runtime.config.llm.model,
                "self": True,
                "role": self.mesh.role if self.mesh else "standalone",
            }]
            total_cores = self_cores or 0
            seen_urls = set()

            # Tailscale mesh peers (from config/wolfpack-hub.yaml).
            if self.mesh is not None:
                for peer in self.mesh.peers.values():
                    if peer.url in seen_urls:
                        continue
                    seen_urls.add(peer.url)
                    nodes.append({
                        "name": peer.id,
                        "ip": self._peer_ip(peer.url),
                        "url": peer.url,
                        "cores": None,
                        "cpu_percent": None,
                        "model": peer.role + (peer.agent_id and f" · {peer.agent_id}" or ""),
                        "reachable": peer.healthy,
                        "self": False,
                        "role": peer.role,
                        "agent_id": peer.agent_id,
                    })

            # LAN-discovered peers (same broadcast domain).
            for p in self.discovery.peers():
                url = p.get("url")
                ip = p.get("ip")
                key = url or ip
                if not key or key in seen_urls:
                    continue
                seen_urls.add(key)
                load = p.get("load", {})
                cores = load.get("cpu_count")
                total_cores += cores or 0
                nodes.append({
                    "name": p["name"], "ip": ip, "cores": cores,
                    "cpu_percent": load.get("cpu_percent"), "model": p.get("model"),
                    "reachable": bool(url), "self": False,
                })
            return {"node_count": len(nodes), "total_cores": total_cores, "nodes": nodes}

        @self.app.post("/api/cluster/map")
        async def cluster_map(payload: ClusterMapRequest) -> dict[str, Any]:  # noqa: WPS430
            # Workers = this node + every reachable mesh/ LAN peer. Tasks are assigned
            # round-robin and executed concurrently, so wall-clock ≈ the slowest
            # worker's share rather than the sum of all tasks.
            workers = [{"name": self.runtime.config.personality.name + " (self)", "url": None}]
            seen_urls = set()
            if self.mesh is not None:
                for peer in self.mesh.peers.values():
                    if peer.healthy and peer.url and peer.url not in seen_urls:
                        seen_urls.add(peer.url)
                        workers.append({"name": peer.id, "url": peer.url})
            for p in self.discovery.peers():
                url = p.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    workers.append({"name": p["name"], "url": url})

            async def run_one(idx: int, goal: str) -> dict[str, Any]:
                w = workers[idx % len(workers)]
                start = time.perf_counter()
                try:
                    if w["url"] is None:
                        res = await self.runtime.run_with_agent(goal, agent_type=payload.agent)
                    else:
                        async with httpx.AsyncClient(timeout=300.0) as client:
                            r = await client.post(f"{w['url']}/goal", json={"goal": goal, "agent": payload.agent})
                            r.raise_for_status()
                            res = r.json()
                    summary = res.get("summary") or res.get("answer") or ""
                    return {"goal": goal, "node": w["name"], "seconds": round(time.perf_counter() - start, 1), "summary": summary, "ok": True}
                except Exception as exc:  # noqa: BLE001
                    return {"goal": goal, "node": w["name"], "seconds": round(time.perf_counter() - start, 1), "error": str(exc), "ok": False}

            start = time.perf_counter()
            results = await asyncio.gather(*[run_one(i, g) for i, g in enumerate(payload.goals)])
            wall = round(time.perf_counter() - start, 1)
            serial = round(sum(r["seconds"] for r in results), 1)
            return {
                "nodes_used": len(workers),
                "tasks": len(payload.goals),
                "wall_seconds": wall,
                "serial_seconds": serial,
                "speedup": round(serial / wall, 2) if wall > 0 else 1.0,
                "results": results,
            }

        # --- Hub status: consolidated view of mesh, jobs, inbox, share-bus ---
        @self.app.get("/api/hub/status")
        async def hub_status() -> dict[str, Any]:  # noqa: WPS430
            mesh_info: dict[str, Any] = {"enabled": False}
            if self.mesh is not None:
                mesh_info = {
                    "enabled": True,
                    "hub_id": self.mesh.hub_id,
                    "role": self.mesh.role,
                    "leader": self.mesh.leader(),
                    "is_leader": self.mesh.is_leader(),
                    "peers": [
                        {"id": p.id, "url": p.url, "role": p.role, "healthy": p.healthy,
                         "last_seen": p.last_seen, "error": p.error}
                        for p in self.mesh.peers.values()
                    ],
                }
            share_cfg = self.runtime.config.share
            share_path = share_cfg.path
            if not share_path:
                from jarvis_os.core.share_bus import _autodetect_share
                share_path = _autodetect_share()
            return {
                "hub_enabled": self.runtime.config.hub.enabled,
                "node": self.runtime.config.personality.name,
                "mesh": mesh_info,
                "jobs": self.jobqueue.stats(),
                "inbox": {"recent": len(self.inbox.list(limit=100).get("messages", []))},
                "sharebus": {
                    "enabled": share_cfg.enabled,
                    "path": share_path,
                    "nodes": self.sharebus.nodes(),
                },
            }

        # --- Share task-bus: firewall-proof delegation through the NAS share ---
        @self.app.post("/api/share/submit")
        async def share_submit(payload: dict[str, Any]) -> dict[str, Any]:  # noqa: WPS430
            return self.sharebus.submit(
                payload.get("target", ""), payload.get("goal", ""), payload.get("agent", "simple")
            )

        @self.app.get("/api/share/result/{tid}")
        async def share_result(tid: str) -> Any:  # noqa: WPS430
            r = self.sharebus.result(tid)
            return r if r is not None else {"status": "pending"}

        @self.app.get("/api/share/nodes")
        async def share_nodes() -> dict[str, Any]:  # noqa: WPS430
            return {"self": self.runtime.config.personality.name, "nodes": self.sharebus.nodes()}

        @self.app.get("/api/peers")
        async def get_peers() -> dict[str, Any]:  # noqa: WPS430
            return {
                "self": {
                    "instance_id": self.discovery.instance_id,
                    "name": self.runtime.config.personality.name,
                    "ip": self.discovery.lan_ip,
                    "gui_port": self.gui_port,
                    "provider": self.runtime.config.llm.provider,
                    "model": self.runtime.config.llm.model,
                },
                "peers": self.discovery.peers(),
            }

        @self.app.post("/api/delegate")
        async def delegate(payload: DelegateRequest) -> Any:  # noqa: WPS430
            """Forward a goal to a peer instance (or auto-pick the least-loaded one)."""
            if payload.peer_url:
                target = payload.peer_url.rstrip("/")
            else:
                best = self.discovery.best_peer()
                if not best:
                    return JSONResponse(status_code=404, content={"error": "No reachable peers found on the network."})
                target = best["url"]
            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    resp = await client.post(
                        f"{target}/goal",
                        json={"goal": payload.goal, "agent": payload.agent},
                    )
                    resp.raise_for_status()
                    result = resp.json()
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(status_code=502, content={"error": f"Delegation to {target} failed: {exc}"})
            return {"delegated_to": target, "result": result}

    def _self_restart(self) -> None:
        """Re-run the same process. Best-effort; platform-specific."""
        import sys

        try:
            import os

            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as exc:  # noqa: BLE001
            logger.error("Self-restart failed: %s", exc)

    async def run(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        """Start the uvicorn server."""
        self.gui_port = port
        if self.runtime.config.network.discovery_enabled:
            await self.discovery.start()
        hub = self.runtime.config.hub.enabled
        # In hub mode Runtime starts worker/sharebus; otherwise start them here.
        if not hub:
            await self.worker.start()
            await self.sharebus.start()
        # Start the hands-free voice listener if the user has enabled always-listening.
        if self.voice.settings.get("always_listening"):
            self.voice.start()
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        try:
            await server.serve()
        finally:
            self.voice.stop()
            if not hub:
                await self.sharebus.stop()
                await self.worker.stop()
            await self.discovery.stop()


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JARVIS OS // Command Interface</title>
    <style>
        :root {
            --bg: #030712;
            --panel: rgba(11, 20, 36, 0.72);
            --panel-solid: #0b1424;
            --text: #e0f2fe;
            --muted: #7dd3fc;
            --accent: #00f0ff;
            --accent-2: #0ea5e9;
            --success: #00ff9d;
            --error: #ff3860;
            --warn: #facc15;
            --border: rgba(0, 240, 255, 0.18);
            --glow: rgba(0, 240, 255, 0.35);
        }
        * { box-sizing: border-box; }
        html, body { height: 100%; }
        body {
            margin: 0;
            font-family: "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            overflow-x: hidden;
            line-height: 1.5;
        }
        .bg-grid {
            position: fixed;
            inset: 0;
            z-index: -2;
            background-image:
                linear-gradient(rgba(0, 240, 255, 0.05) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0, 240, 255, 0.05) 1px, transparent 1px);
            background-size: 45px 45px;
            animation: gridMove 12s linear infinite;
            pointer-events: none;
        }
        .bg-grid::before {
            content: "";
            position: absolute;
            inset: 0;
            background:
                radial-gradient(circle at 50% 0%, rgba(0, 240, 255, 0.12), transparent 55%),
                radial-gradient(circle at 80% 90%, rgba(14, 165, 233, 0.08), transparent 45%);
        }
        @keyframes gridMove {
            0% { background-position: 0 0; }
            100% { background-position: 0 45px; }
        }
        .scanline {
            position: fixed;
            inset: 0;
            z-index: -1;
            background: linear-gradient(to bottom, transparent 50%, rgba(0, 240, 255, 0.03) 51%, transparent 52%);
            background-size: 100% 5px;
            pointer-events: none;
            animation: scanline 6s linear infinite;
        }
        @keyframes scanline {
            0% { transform: translateY(-100%); }
            100% { transform: translateY(100vh); }
        }
        .app {
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 1rem;
        }
        .hud-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1rem 1.5rem;
            margin-bottom: 1rem;
        }
        .logo {
            font-size: 1.85rem;
            font-weight: 800;
            letter-spacing: 0.18em;
            color: var(--accent);
            text-shadow: 0 0 14px var(--glow);
        }
        .logo span {
            color: var(--text);
            font-weight: 300;
            margin-left: 0.4rem;
            opacity: 0.9;
        }
        .status-bar {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.5rem 1rem;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--panel);
            backdrop-filter: blur(10px);
            box-shadow: 0 0 18px rgba(0, 240, 255, 0.1);
        }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--accent);
            box-shadow: 0 0 10px var(--accent);
            transition: all 0.3s ease;
        }
        .status-dot.idle { animation: pulseIdle 2.5s infinite; }
        .status-dot.processing { background: var(--warn); box-shadow: 0 0 14px var(--warn); animation: pulseFast 0.8s infinite; }
        .status-dot.done { background: var(--success); box-shadow: 0 0 14px var(--success); }
        @keyframes pulseIdle {
            0%, 100% { opacity: 0.7; transform: scale(1); }
            50% { opacity: 1; transform: scale(1.25); }
        }
        @keyframes pulseFast {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.35); }
        }
        .status-text {
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            color: var(--muted);
            min-width: 150px;
            text-align: center;
        }
        .hud-main {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
            max-width: 1200px;
            width: 100%;
            margin: 0 auto;
        }
        .glass {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 1rem;
            backdrop-filter: blur(14px);
            box-shadow: 0 0 30px rgba(0, 0, 0, 0.35), inset 0 0 30px rgba(0, 240, 255, 0.04);
            position: relative;
            overflow: hidden;
        }
        .glass::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 1px;
            background: linear-gradient(90deg, transparent, var(--accent), transparent);
            opacity: 0.6;
        }
        .command-center {
            padding: 2rem;
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }
        .input-mode {
            font-size: 0.75rem;
            letter-spacing: 0.22em;
            font-weight: 800;
            color: var(--accent);
            text-shadow: 0 0 8px var(--glow);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .input-mode::before {
            content: "▸";
            animation: blink 1.1s infinite;
        }
        .input-mode.directive { color: var(--warn); text-shadow: 0 0 10px rgba(250, 204, 21, 0.55); }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.25; } }
        .input-wrap { position: relative; }
        textarea {
            width: 100%;
            padding: 1rem;
            border: 1px solid var(--border);
            border-radius: 0.75rem;
            background: rgba(3, 7, 18, 0.7);
            color: var(--text);
            font-size: 1.05rem;
            font-family: inherit;
            resize: vertical;
            min-height: 110px;
            outline: none;
            transition: all 0.25s ease;
            box-shadow: inset 0 0 20px rgba(0, 240, 255, 0.05);
        }
        textarea:focus {
            border-color: var(--accent);
            box-shadow: 0 0 25px var(--glow), inset 0 0 20px rgba(0, 240, 255, 0.1);
        }
        textarea::placeholder { color: rgba(125, 211, 252, 0.42); }
        .command-actions {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }
        button {
            position: relative;
            padding: 0.85rem 2.2rem;
            border: none;
            border-radius: 0.6rem;
            background: linear-gradient(90deg, var(--accent-2), var(--accent));
            color: #001018;
            font-weight: 800;
            font-size: 0.95rem;
            letter-spacing: 0.08em;
            cursor: pointer;
            overflow: hidden;
            transition: transform 0.15s ease, box-shadow 0.25s ease;
            box-shadow: 0 0 22px var(--glow);
        }
        button:hover { transform: translateY(-2px); box-shadow: 0 0 34px var(--accent); }
        button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none; }
        .btn-shine {
            position: absolute;
            top: 0; left: -100%;
            width: 50%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.45), transparent);
            transform: skewX(-25deg);
            animation: shine 3s infinite;
        }
        @keyframes shine {
            0% { left: -100%; }
            20%, 100% { left: 200%; }
        }
        .shortcuts {
            font-size: 0.8rem;
            color: var(--muted);
            display: flex;
            flex-wrap: wrap;
            gap: 0.7rem;
            align-items: center;
        }
        .agent-select {
            background: rgba(0, 240, 255, 0.08);
            border: 1px solid var(--border);
            border-radius: 0.5rem;
            color: var(--accent);
            padding: 0.45rem 0.75rem;
            font-size: 0.8rem;
            font-family: inherit;
            outline: none;
            cursor: pointer;
        }
        .agent-select:focus { box-shadow: 0 0 12px var(--glow); }
        .kbd {
            display: inline-block;
            padding: 0.2rem 0.5rem;
            border: 1px solid var(--border);
            border-radius: 0.35rem;
            background: rgba(0, 240, 255, 0.08);
            color: var(--accent);
            font-family: ui-monospace, monospace;
            font-size: 0.75rem;
        }
        .response-deck {
            padding: 1.5rem;
            display: none;
            animation: fadeInUp 0.5s ease forwards;
        }
        .deck-header {
            font-size: 0.8rem;
            letter-spacing: 0.2em;
            color: var(--accent);
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-weight: 700;
        }
        .deck-header::after {
            content: "";
            flex: 1;
            height: 1px;
            background: linear-gradient(90deg, var(--accent), transparent);
            margin-left: 0.75rem;
        }
        .card {
            background: rgba(3, 7, 18, 0.55);
            border: 1px solid var(--border);
            border-left: 3px solid var(--accent);
            border-radius: 0.75rem;
            padding: 1rem 1.25rem;
            margin-top: 0.875rem;
            animation: fadeInUp 0.5s ease forwards;
            opacity: 0;
            transform: translateY(12px);
        }
        .card h3 {
            margin: 0 0 0.5rem;
            font-size: 0.8rem;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--accent);
        }
        .card pre {
            margin: 0;
            white-space: pre-wrap;
            word-break: break-word;
            font-size: 0.9rem;
            color: var(--muted);
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        .card.success { border-left-color: var(--success); }
        .card.success h3 { color: var(--success); }
        .card.error { border-left-color: var(--error); }
        .card.error h3 { color: var(--error); }
        .typing-cursor::after {
            content: "▋";
            animation: cursorBlink 0.8s infinite;
            color: var(--accent);
            margin-left: 2px;
        }
        @keyframes cursorBlink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        @keyframes fadeInUp {
            to { opacity: 1; transform: translateY(0); }
        }
        .lower-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 1.25rem;
        }
        .memory-panel, .audit-panel {
            padding: 1.25rem;
            min-height: 320px;
            display: flex;
            flex-direction: column;
        }
        .panel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 0.75rem;
            font-size: 0.82rem;
            letter-spacing: 0.12em;
            color: var(--accent);
            text-transform: uppercase;
            font-weight: 700;
        }
        .refresh-btn {
            padding: 0.35rem 0.75rem;
            font-size: 0.7rem;
            background: transparent;
            color: var(--accent);
            border: 1px solid var(--border);
            box-shadow: none;
            font-weight: 600;
        }
        .refresh-btn:hover { background: rgba(0, 240, 255, 0.1); box-shadow: 0 0 12px var(--glow); }
        .log-scroll {
            flex: 1;
            overflow-y: auto;
            max-height: 320px;
            padding-right: 0.5rem;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 0.82rem;
        }
        .log-scroll::-webkit-scrollbar { width: 6px; }
        .log-scroll::-webkit-scrollbar-track { background: rgba(0, 240, 255, 0.05); border-radius: 3px; }
        .log-scroll::-webkit-scrollbar-thumb { background: var(--accent-2); border-radius: 3px; }
        .entry {
            padding: 0.65rem 0.5rem;
            border-bottom: 1px solid rgba(0, 240, 255, 0.08);
            animation: fadeIn 0.4s ease;
        }
        .entry:last-child { border-bottom: none; }
        .entry .meta { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.35rem; }
        .entry .timestamp { color: var(--accent-2); font-size: 0.75rem; }
        .entry .role {
            padding: 0.15rem 0.45rem;
            border-radius: 0.25rem;
            background: rgba(0, 240, 255, 0.12);
            color: var(--accent);
            font-size: 0.7rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .entry .content { color: var(--text); line-height: 1.45; }
        .log-line {
            padding: 0.4rem 0.25rem;
            border-bottom: 1px solid rgba(0, 240, 255, 0.06);
            color: var(--muted);
            animation: fadeIn 0.3s ease;
        }
        .log-line:last-child { border-bottom: none; }
        .empty { color: rgba(125, 211, 252, 0.5); font-style: italic; padding: 0.5rem; }
        .error-msg { color: var(--error); }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        .hud-footer {
            display: flex;
            justify-content: space-between;
            padding: 1rem 1.5rem 0;
            font-size: 0.7rem;
            letter-spacing: 0.1em;
            color: rgba(125, 211, 252, 0.5);
            text-transform: uppercase;
        }
        @media (max-width: 640px) {
            .hud-header { flex-direction: column; gap: 1rem; align-items: flex-start; }
            .command-center { padding: 1.25rem; }
            .logo { font-size: 1.35rem; }
            .shortcuts { width: 100%; }
            .lower-grid { grid-template-columns: 1fr; }
            .status-text { min-width: auto; }
        }
    </style>
</head>
<body>
    <div class="bg-grid"></div>
    <div class="scanline"></div>
    <div class="app">
        <header class="hud-header">
            <div class="logo">JARVIS<span>OS</span></div>
            <div class="status-bar">
                <span class="status-dot idle" id="statusDot"></span>
                <span class="status-text" id="statusText">SYSTEM IDLE</span>
            </div>
        </header>
        <main class="hud-main">
            <section class="command-center glass">
                <div class="input-mode" id="inputMode">STANDARD MODE</div>
                <div class="input-wrap">
                    <textarea id="goal" placeholder="State your objective, sir..."></textarea>
                </div>
                <div class="command-actions">
                    <button id="submit" onclick="sendGoal()">
                        <span class="btn-text">EXECUTE</span>
                        <span class="btn-shine"></span>
                    </button>
                    <select id="agentMode" class="agent-select" onchange="updateModeFromSelect()">
                        <option value="simple">SIMPLE</option>
                        <option value="react">REACT</option>
                        <option value="codeact">CODEACT</option>
                        <option value="autonomous">AUTONOMOUS</option>
                    </select>
                    <div class="shortcuts">
                        <span><span class="kbd">Enter</span> execute</span>
                        <span><span class="kbd">Ctrl+Enter</span> autonomous</span>
                    </div>
                </div>
            </section>
            <section class="response-deck glass" id="responseDeck">
                <div class="deck-header">RESPONSE STREAM</div>
                <div id="results"></div>
            </section>
            <div class="lower-grid">
                <section class="memory-panel glass">
                    <div class="panel-header">
                        <span>Memory Log</span>
                        <button class="refresh-btn" onclick="loadMemory()">Refresh</button>
                    </div>
                    <div class="log-scroll" id="memory"></div>
                </section>
                <section class="audit-panel glass">
                    <div class="panel-header">
                        <span>Audit Log</span>
                        <button class="refresh-btn" onclick="loadAudit()">Refresh</button>
                    </div>
                    <div class="log-scroll" id="audit"></div>
                </section>
            </div>
        </main>
        <footer class="hud-footer">
            <span>JARVIS OS v1.0</span>
            <span>Secure Connection</span>
        </footer>
    </div>
    <script>
        const input = document.getElementById('goal');
        const submitBtn = document.getElementById('submit');
        const statusDot = document.getElementById('statusDot');
        const statusText = document.getElementById('statusText');
        const inputMode = document.getElementById('inputMode');
        const agentMode = document.getElementById('agentMode');
        const responseDeck = document.getElementById('responseDeck');
        const results = document.getElementById('results');

        function setStatus(state, text) {
            statusDot.className = 'status-dot ' + state;
            statusText.textContent = text;
        }

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const autonomous = e.ctrlKey || e.metaKey;
                if (autonomous) agentMode.value = 'autonomous';
                updateModeFromSelect();
                sendGoal();
            }
        });

        function updateModeFromSelect() {
            const mode = agentMode.value;
            const isAuto = mode === 'autonomous';
            inputMode.textContent = isAuto ? 'AUTONOMOUS MODE' : mode.toUpperCase() + ' MODE';
            if (isAuto) inputMode.classList.add('directive');
            else inputMode.classList.remove('directive');
            submitBtn.querySelector('.btn-text').textContent = isAuto ? 'EXECUTE AUTONOMOUS' : 'EXECUTE';
        }

        async function sendGoal() {
            const goal = input.value.trim();
            if (!goal) return;
            const agent = agentMode.value;
            updateModeFromSelect();

            submitBtn.disabled = true;
            responseDeck.style.display = 'block';
            results.innerHTML = '<div class="card"><h3>Initializing</h3><pre class="typing-cursor">Establishing neural link...</pre></div>';
            setStatus('processing', agent === 'autonomous' ? 'AUTONOMOUS DIRECTIVE ACTIVE' : 'PROCESSING REQUEST');

            try {
                const res = await fetch('/goal', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ goal, agent })
                });
                const data = await res.json();
                renderResponse(data, res.ok);
            } catch (err) {
                results.innerHTML = '<div class="card error"><h3>Connection Failure</h3><pre>' + escapeHtml(err.message) + '</pre></div>';
                setStatus('idle', 'SYSTEM IDLE');
            } finally {
                submitBtn.disabled = false;
                loadMemory();
                loadAudit();
            }
        }

        function renderResponse(data, ok) {
            results.innerHTML = '';
            const text = data.summary || data.answer || '';
            if (text) {
                const card = document.createElement('div');
                card.className = 'card';
                card.innerHTML = '<h3>' + (data.answer ? 'Agent Answer' : 'Mission Summary') + '</h3><pre id="summaryText" class="typing-cursor"></pre>';
                results.appendChild(card);
                streamText(document.getElementById('summaryText'), text, 10, () => {
                    appendDetails(data, ok);
                });
            } else {
                appendDetails(data, ok);
            }
        }

        function appendDetails(data, ok) {
            if (data.plan) {
                const card = document.createElement('div');
                card.className = 'card';
                card.innerHTML = '<h3>Strategic Plan</h3><pre>' + escapeHtml(data.plan) + '</pre>';
                results.appendChild(card);
            }
            if (Array.isArray(data.results) && data.results.length) {
                const wrapper = document.createElement('div');
                wrapper.className = 'card';
                wrapper.innerHTML = '<h3>Skill Results</h3>';
                for (const r of data.results) {
                    const okSkill = !r.error;
                    const skillCard = document.createElement('div');
                    skillCard.className = 'card ' + (okSkill ? 'success' : 'error');
                    skillCard.innerHTML = '<h3>' + escapeHtml(r.skill || r.step || 'step') + ' ' + (okSkill ? '✓' : '✗') + '</h3><pre>' +
                        escapeHtml(okSkill ? JSON.stringify(r.result, null, 2) : r.error) + '</pre>';
                    wrapper.appendChild(skillCard);
                }
                results.appendChild(wrapper);
            }
            if (Array.isArray(data.steps) && data.steps.length) {
                const wrapper = document.createElement('div');
                wrapper.className = 'card';
                wrapper.innerHTML = '<h3>Agent Steps</h3>';
                for (const s of data.steps) {
                    const stepCard = document.createElement('div');
                    stepCard.className = 'card';
                    stepCard.innerHTML = '<h3>Step ' + escapeHtml(String(s.step)) + '</h3><pre>' + escapeHtml(JSON.stringify(s, null, 2)) + '</pre>';
                    wrapper.appendChild(stepCard);
                }
                results.appendChild(wrapper);
            }
            if (Array.isArray(data.observations) && data.observations.length) {
                const wrapper = document.createElement('div');
                wrapper.className = 'card';
                wrapper.innerHTML = '<h3>Observations</h3>';
                for (const o of data.observations) {
                    const obsCard = document.createElement('div');
                    obsCard.className = 'card';
                    obsCard.innerHTML = '<pre>' + escapeHtml(String(o)) + '</pre>';
                    wrapper.appendChild(obsCard);
                }
                results.appendChild(wrapper);
            }
            if (data.stdout) {
                const card = document.createElement('div');
                card.className = 'card';
                card.innerHTML = '<h3>Code Output</h3><pre>' + escapeHtml(data.stdout) + '</pre>';
                results.appendChild(card);
            }
            if (data.error && !data.summary && !data.answer) {
                const card = document.createElement('div');
                card.className = 'card error';
                card.innerHTML = '<h3>System Error</h3><pre>' + escapeHtml(data.error) + '</pre>';
                results.appendChild(card);
            }
            setStatus(ok ? 'done' : 'idle', ok ? 'EXECUTION COMPLETE' : 'SYSTEM IDLE');
            if (ok) setTimeout(() => setStatus('idle', 'SYSTEM IDLE'), 2500);
        }

        function streamText(element, text, speedMs, done) {
            element.classList.add('typing-cursor');
            let i = 0;
            const raw = String(text || '');
            function step() {
                if (i < raw.length) {
                    element.textContent += raw.charAt(i);
                    i++;
                    setTimeout(step, speedMs);
                } else {
                    element.classList.remove('typing-cursor');
                    if (done) done();
                }
            }
            step();
        }

        async function loadMemory() {
            const container = document.getElementById('memory');
            try {
                const messages = await fetch('/memory').then(r => r.json());
                if (!messages.length) {
                    container.innerHTML = '<div class="empty">No memory entries found.</div>';
                    return;
                }
                container.innerHTML = messages.map(m => '<div class="entry">' +
                    '<div class="meta"><span class="timestamp">' + escapeHtml(m.timestamp) + '</span>' +
                    '<span class="role">' + escapeHtml(m.role) + '</span></div>' +
                    '<div class="content">' + escapeHtml(m.content) + '</div></div>').reverse().join('');
            } catch (err) {
                container.innerHTML = '<div class="empty error-msg">Failed to load memory: ' + escapeHtml(err.message) + '</div>';
            }
        }

        async function loadAudit() {
            const container = document.getElementById('audit');
            try {
                const lines = await fetch('/audit').then(r => r.json());
                if (!lines.length) {
                    container.innerHTML = '<div class="empty">No audit entries found.</div>';
                    return;
                }
                container.innerHTML = lines.map(line => '<div class="log-line">' + escapeHtml(line) + '</div>').reverse().join('');
            } catch (err) {
                container.innerHTML = '<div class="empty error-msg">Failed to load audit log: ' + escapeHtml(err.message) + '</div>';
            }
        }

        function escapeHtml(text) {
            if (text === null || text === undefined) return '';
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        loadMemory();
        loadAudit();
    </script>
</body>
</html>
"""