"""Roblox Studio control skill.

Drives a running Roblox Studio through its official MCP server (``StudioMCP.exe``,
the same bridge Claude Code's Roblox_Studio MCP uses). WolfPack spawns the server,
speaks MCP (line-delimited JSON-RPC 2.0) over stdio, and exposes the useful Studio
operations as skill actions: read the game tree, run Luau, read the console, start
and stop a playtest, inspect instances, etc.

Requires Roblox Studio to be **installed on this node** (StudioMCP.exe ships with
it) and **open with a place loaded + MCP enabled** for anything that touches the
live game. On a node without Studio (e.g. the Linux fleet boxes) every action
returns a clear "Studio not available here" error rather than hanging.
"""

from __future__ import annotations

import asyncio
import base64
import glob
import json
import logging
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

# A Luau base64 decoder, prepended to injection code so the game's source can be
# passed as a plain base64 string literal -- no Luau string-escaping headaches.
_LUAU_B64 = """
local function _wpB64(data)
	local b = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
	data = string.gsub(data, '[^' .. b .. '=]', '')
	return (data:gsub('.', function(x)
		if x == '=' then return '' end
		local r, f = '', (b:find(x) - 1)
		for i = 6, 1, -1 do r = r .. (f % 2 ^ i - f % 2 ^ (i - 1) > 0 and '1' or '0') end
		return r
	end):gsub('%d%d%d?%d?%d?%d?%d?%d?', function(x)
		if #x ~= 8 then return '' end
		local c = 0
		for i = 1, 8 do c = c + (x:sub(i, i) == '1' and 2 ^ (8 - i) or 0) end
		return string.char(c)
	end))
end
"""

# folder under the project -> (Luau expression for the parent, default script class)
_SERVICE_MAP = {
    "ServerScriptService": ('game:GetService("ServerScriptService")', "Script"),
    "StarterPlayerScripts": ('game:GetService("StarterPlayer"):FindFirstChild("StarterPlayerScripts")', "LocalScript"),
    "ReplicatedStorage": ('game:GetService("ReplicatedStorage")', "ModuleScript"),
    "StarterGui": ('game:GetService("StarterGui")', "LocalScript"),
    "ServerStorage": ('game:GetService("ServerStorage")', "ModuleScript"),
}


def _classify(folder: str, filename: str) -> tuple[str, str, str] | None:
    """(parent_expr, class_name, script_name) for a .luau file, or None to skip."""
    if not filename.endswith(".luau") and not filename.endswith(".lua"):
        return None
    parent_expr, default_cls = _SERVICE_MAP.get(folder, (None, None))
    if parent_expr is None:
        return None
    lower = filename.lower()
    if lower.endswith(".server.luau") or lower.endswith(".server.lua"):
        cls = "Script"
    elif lower.endswith(".client.luau") or lower.endswith(".client.lua"):
        cls = "LocalScript"
    else:
        cls = default_cls
    # strip .server/.client and the extension for the instance name
    name = filename
    for suffix in (".server.luau", ".client.luau", ".server.lua", ".client.lua", ".luau", ".lua"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return parent_expr, cls, name


def _find_studio_mcp() -> str | None:
    """Locate the newest StudioMCP.exe (the mcp.bat picks the same one)."""
    if platform.system() != "Windows":
        return None
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    candidates = glob.glob(os.path.join(local, "Roblox", "Versions", "*", "StudioMCP.exe"))
    if not candidates:
        return None
    # newest install wins
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


class _StudioClient:
    """Minimal synchronous MCP stdio client for StudioMCP.exe.

    One instance == one server process == one MCP session. Spawn, initialize,
    make one or more tool calls, then close. Cheap enough to do per skill call.
    """

    def __init__(self, exe: str, timeout: float = 45.0):
        self.timeout = timeout
        self._proc = subprocess.Popen(
            [exe],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._id = 0
        self._responses: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(msg, dict) and "id" in msg and msg["id"] is not None:
                with self._lock:
                    self._responses[msg["id"]] = msg

    def _send(self, obj: dict) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(obj) + "\n")
        self._proc.stdin.flush()

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            self._id += 1
            rid = self._id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError("StudioMCP process exited unexpectedly")
            with self._lock:
                if rid in self._responses:
                    return self._responses.pop(rid)
            time.sleep(0.05)
        raise TimeoutError(f"StudioMCP timed out after {self.timeout}s waiting for {method}")

    def initialize(self) -> dict:
        res = self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "wolfpack", "version": "1.0"},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return res

    def list_tools(self) -> list[dict]:
        res = self._rpc("tools/list")
        return res.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self) -> None:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self._proc.kill()


def _text_of(rpc_result: dict) -> dict[str, Any]:
    """Flatten an MCP tools/call response into {ok, text, isError} (or {error})."""
    if "error" in rpc_result:
        return {"ok": False, "error": rpc_result["error"]}
    result = rpc_result.get("result", {})
    blocks = result.get("content", [])
    text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return {"ok": not result.get("isError", False), "text": text, "isError": result.get("isError", False)}


# Named actions -> (tool_name, how to build arguments from kwargs)
class RobloxStudioSkill(Skill):
    """Control a running Roblox Studio via its MCP bridge (StudioMCP.exe)."""

    name = "roblox_studio"
    description = (
        "Drive a running Roblox Studio via its MCP bridge: read the game tree, run "
        "Luau, read the console output, start/stop a playtest, inspect instances, "
        "search scripts. Needs Studio open on this machine with MCP enabled."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "tools", "state", "studios", "set_studio", "tree", "inspect",
                    "run", "console", "play", "stop", "script_read", "script_grep", "call",
                    "push_project", "playtest", "autobuild",
                ],
                "description": (
                    "state=studio mode/datamodels; studios=list connected Studios; tree=game "
                    "hierarchy; inspect=one instance's props; run=execute Luau; console=output log; "
                    "play/stop=playtest; script_read/script_grep=read/search scripts; call=generic tool. "
                    "AUTONOMOUS: push_project=inject a generated game folder's scripts into Studio (no "
                    "Script Sync); playtest=play + read console + stop, flag errors; autobuild=generate "
                    "a wave-survival game + inject + playtest + report, all in one call."
                ),
            },
            "project_dir": {"type": "string", "description": "Generated game folder for push_project (has ServerScriptService/ etc.)."},
            "theme": {"type": "string", "enum": ["scifi", "medieval"], "description": "Theme for autobuild (default medieval)."},
            "project_name": {"type": "string", "description": "Game name for autobuild."},
            "wait_seconds": {"type": "number", "description": "Seconds to run the playtest before reading the console (default 8)."},
            "code": {"type": "string", "description": "Luau source for action=run."},
            "datamodel_type": {"type": "string", "description": "Target datamodel for run (Edit/Server/Client). Auto-detected if omitted."},
            "path": {"type": "string", "description": "Instance path for tree/inspect (e.g. 'game.Workspace')."},
            "keywords": {"type": "string", "description": "Keywords for tree/script_grep filtering."},
            "query": {"type": "string", "description": "Pattern for script_grep."},
            "max_depth": {"type": "integer", "description": "Depth limit for tree."},
            "target_file": {"type": "string", "description": "Script path for script_read."},
            "studio_id": {"type": "string", "description": "Studio id for set_studio."},
            "tool": {"type": "string", "description": "Raw MCP tool name for action=call."},
            "arguments": {"type": "object", "description": "Raw MCP tool arguments for action=call."},
        },
        "required": ["action"],
    }
    permissions = ["process:spawn"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        exe = _find_studio_mcp()
        if not exe:
            return {
                "ok": False,
                "error": "Roblox Studio MCP (StudioMCP.exe) not found on this node — "
                         "run this on the machine where Roblox Studio is installed.",
            }
        try:
            return await asyncio.to_thread(self._run_sync, exe, kwargs)
        except (TimeoutError, RuntimeError) as exc:
            return {"ok": False, "error": str(exc),
                    "hint": "Is Roblox Studio open with a place loaded and MCP enabled?"}

    def _run_sync(self, exe: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        action = kwargs.get("action")
        client = _StudioClient(exe)
        try:
            client.initialize()
            # Every fresh StudioMCP process starts with no active Studio bound; bind
            # one before any command that touches the live game.
            if action not in ("tools",):
                self._ensure_active_studio(client)

            if action == "tools":
                tools = client.list_tools()
                return {"ok": True, "tools": [
                    {"name": t.get("name"), "description": (t.get("description") or "").strip().splitlines()[0:1]}
                    for t in tools
                ]}

            if action == "state":
                return {"ok": True, **_text_of(client.call_tool("get_studio_state"))}

            if action == "studios":
                return {"ok": True, **_text_of(client.call_tool("list_roblox_studios"))}

            if action == "set_studio":
                sid = kwargs.get("studio_id")
                if not sid:
                    return {"ok": False, "error": "set_studio needs studio_id"}
                return {"ok": True, **_text_of(client.call_tool("set_active_studio", {"studio_id": sid}))}

            if action == "tree":
                args: dict[str, Any] = {}
                if kwargs.get("path"):
                    args["path"] = kwargs["path"]
                if kwargs.get("keywords"):
                    args["keywords"] = kwargs["keywords"]
                if kwargs.get("max_depth") is not None:
                    args["max_depth"] = kwargs["max_depth"]
                return {"ok": True, **_text_of(client.call_tool("search_game_tree", args))}

            if action == "inspect":
                path = kwargs.get("path")
                if not path:
                    return {"ok": False, "error": "inspect needs path"}
                return {"ok": True, **_text_of(client.call_tool("inspect_instance", {"path": path}))}

            if action == "run":
                code = kwargs.get("code")
                if not code:
                    return {"ok": False, "error": "run needs code"}
                dm = kwargs.get("datamodel_type") or self._current_datamodel(client)
                return {"ok": True, "datamodel_type": dm,
                        **_text_of(client.call_tool("execute_luau", {"code": code, "datamodel_type": dm}))}

            if action == "console":
                return {"ok": True, **_text_of(client.call_tool("get_console_output"))}

            if action == "play":
                return {"ok": True, **_text_of(client.call_tool("start_stop_play", {"is_start": True}))}

            if action == "stop":
                return {"ok": True, **_text_of(client.call_tool("start_stop_play", {"is_start": False}))}

            if action == "script_read":
                tf = kwargs.get("target_file")
                if not tf:
                    return {"ok": False, "error": "script_read needs target_file"}
                a: dict[str, Any] = {"target_file": tf, "should_read_entire_file": True}
                return {"ok": True, **_text_of(client.call_tool("script_read", a))}

            if action == "script_grep":
                q = kwargs.get("query") or kwargs.get("keywords")
                if not q:
                    return {"ok": False, "error": "script_grep needs query"}
                return {"ok": True, **_text_of(client.call_tool("script_grep", {"query": q}))}

            if action == "call":
                tool = kwargs.get("tool")
                if not tool:
                    return {"ok": False, "error": "call needs tool"}
                return {"ok": True, "tool": tool,
                        **_text_of(client.call_tool(tool, kwargs.get("arguments") or {}))}

            if action == "push_project":
                pdir = kwargs.get("project_dir")
                if not pdir:
                    return {"ok": False, "error": "push_project needs project_dir"}
                return self._push_project(client, Path(pdir).expanduser())

            if action == "playtest":
                return self._playtest(client, float(kwargs.get("wait_seconds") or 8))

            if action == "autobuild":
                return self._autobuild(client, kwargs)

            return {"ok": False, "error": f"Unknown action: {action}"}
        finally:
            client.close()

    def _ensure_active_studio(self, client: _StudioClient) -> str | None:
        """Bind an active Studio and VERIFY the bind took before returning.

        A fresh StudioMCP process starts unbound and discovers connected Studios
        a moment after startup, so this retries: list -> set_active -> confirm via
        get_studio_state, until the state call actually reports a Studio mode.
        """
        for _ in range(6):
            info = _text_of(client.call_tool("list_roblox_studios"))
            try:
                data = json.loads(info.get("text", "") or "{}")
            except Exception:  # noqa: BLE001
                data = {}
            studios = data.get("studios") or []
            if studios:
                chosen = next((s for s in studios if s.get("active")), studios[0])
                sid = chosen.get("id")
                if sid:
                    client.call_tool("set_active_studio", {"studio_id": sid})
                    state = _text_of(client.call_tool("get_studio_state"))
                    if state.get("ok") and "Studio Mode" in state.get("text", ""):
                        return sid
            time.sleep(0.6)
        return None

    def _current_datamodel(self, client: _StudioClient) -> str:
        """Pick the focused datamodel from studio state (falls back to Edit)."""
        try:
            info = _text_of(client.call_tool("get_studio_state")).get("text", "")
            for line in info.splitlines():
                if "Focused DataModel" in line and ":" in line:
                    return line.split(":", 1)[1].strip()
        except Exception:  # noqa: BLE001
            pass
        return "Edit"

    # ---- autonomous: inject a generated game, playtest, verify ----
    def _inject(self, client: _StudioClient, parent_expr: str, cls: str, name: str, source: str) -> str:
        """Create/replace a script under a service with the given source (edit mode)."""
        b64 = base64.b64encode(source.encode("utf-8")).decode("ascii")
        code = _LUAU_B64 + f"""
local src = _wpB64("{b64}")
local parent = {parent_expr}
if not parent then return "ERR|no parent for {name}" end
local existing = parent:FindFirstChild("{name}")
if existing then existing:Destroy() end
local s = Instance.new("{cls}")
s.Name = "{name}"
s.Source = src
s.Parent = parent
return "{name}|{cls}|" .. #s.Source
"""
        res = _text_of(client.call_tool("execute_luau", {"code": code, "datamodel_type": "Edit"}))
        return res.get("text", "") if res.get("ok") else "ERR|" + res.get("text", res.get("error", "?"))

    def _push_project(self, client: _StudioClient, pdir: Path) -> dict[str, Any]:
        if not pdir.is_dir():
            return {"ok": False, "error": f"project_dir not found: {pdir}"}
        # inject shared modules first, then server, then client
        order = ["ReplicatedStorage", "ServerStorage", "ServerScriptService", "StarterGui", "StarterPlayerScripts"]
        injected, skipped = [], []
        for folder in order:
            fdir = pdir / folder
            if not fdir.is_dir():
                continue
            for f in sorted(fdir.iterdir()):
                if not f.is_file():
                    continue
                info = _classify(folder, f.name)
                if info is None:
                    skipped.append(f"{folder}/{f.name}")
                    continue
                parent_expr, cls, name = info
                source = f.read_text(encoding="utf-8")
                injected.append(self._inject(client, parent_expr, cls, name, source))
        errors = [r for r in injected if r.startswith("ERR")]
        return {"ok": not errors, "injected": injected, "skipped": skipped,
                "error": "; ".join(errors) if errors else None}

    @staticmethod
    def _scan_errors(text: str) -> list[str]:
        """Pull likely runtime-error lines out of console output."""
        markers = ("attempt to ", "is not a valid member", "stack traceback", "Stack Begin",
                   "exceeded", "Infinite yield", " nil ", "expected ", "attempt to call")
        hits = []
        for line in (text or "").splitlines():
            low = line.lower()
            if "error" in low or any(m.lower() in low for m in markers):
                hits.append(line.strip())
        return hits[:40]

    def _playtest(self, client: _StudioClient, wait_seconds: float) -> dict[str, Any]:
        start = _text_of(client.call_tool("start_stop_play", {"is_start": True}))
        if not start.get("ok"):
            return {"ok": False, "error": "could not start play: " + start.get("text", "")}
        time.sleep(max(1.0, min(wait_seconds, 60)))
        console = _text_of(client.call_tool("get_console_output")).get("text", "")
        client.call_tool("start_stop_play", {"is_start": False})
        errors = self._scan_errors(console)
        return {"ok": not errors, "errors": errors, "console_tail": console[-2500:],
                "verdict": "clean" if not errors else f"{len(errors)} error line(s)"}

    def _autobuild(self, client: _StudioClient, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Generate a wave-survival game, inject it, and playtest -- all autonomously."""
        import asyncio as _aio

        from jarvis_os.skills.roblox import RobloxSkill

        theme = kwargs.get("theme") or "medieval"
        name = kwargs.get("project_name") or ("MedievalSiege" if theme == "medieval" else "WaveSurvival")
        gen = _aio.run(RobloxSkill().run(action="wave_survival", theme=theme, project_name=name))
        pdir = gen.get("project_dir")
        if not pdir:
            return {"ok": False, "error": "generation failed", "gen": gen}
        pushed = self._push_project(client, Path(pdir))
        if not pushed.get("ok"):
            return {"ok": False, "stage": "push", "project_dir": pdir, **pushed}
        played = self._playtest(client, float(kwargs.get("wait_seconds") or 8))
        return {"ok": played.get("ok"), "theme": theme, "project_dir": pdir,
                "injected": pushed.get("injected"), "playtest": played}
