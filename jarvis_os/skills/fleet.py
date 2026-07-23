"""Fleet skill — monitor and control other Jarvis OS nodes.

Discovers peers over UDP and exposes actions to check health, pull system stats,
read audit logs, send goals, run commands, and restart remote nodes. All remote
endpoints require the configured `delegation_token` (or localhost).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx
import yaml

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "jarvis.yaml"


def _load_fleet_config(path: Path | None = None) -> dict[str, Any]:
    """Read gui_port and delegation_token from the local config file."""
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return {}
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return {}
    network = data.get("network", {})
    return {
        "gui_port": network.get("gui_port", 8080),
        "delegation_token": network.get("delegation_token"),
    }


def _load_full_config(path: Path | None = None) -> dict[str, Any]:
    """Read the entire local config dict for pushing to peers."""
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return {}
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return {}


def _local_base_url(cfg: dict[str, Any] | None = None) -> str:
    c = cfg or _load_fleet_config()
    return f"http://127.0.0.1:{c.get('gui_port', 8080)}"


def _headers(cfg: dict[str, Any] | None = None) -> dict[str, str]:
    c = cfg or _load_fleet_config()
    token = c.get("delegation_token")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _local_peers() -> list[dict[str, Any]]:
    """Ask the local node for discovered peers."""
    cfg = _load_fleet_config()
    url = f"{_local_base_url(cfg)}/api/peers"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=_headers(cfg))
            r.raise_for_status()
            data = r.json()
            return data.get("peers", [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch local peers: %s", exc)
        return []


class FleetSkill(Skill):
    """Monitor and control Jarvis OS nodes across the LAN fleet."""

    name = "fleet"
    description = (
        "Monitor and control other Jarvis OS instances in the fleet: list peers, "
        "health-check nodes, fetch system stats and audit logs, send goals, run "
        "commands, and restart remote nodes."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_peers",
                    "health_check",
                    "system_stats",
                    "remote_audit",
                    "remote_goal",
                    "remote_command",
                    "restart_node",
                    "broadcast_goal",
                    "sync_config",
                    "update_code",
                ],
                "description": "Fleet action.",
            },
            "peer_url": {
                "type": "string",
                "description": "Target node URL, e.g. http://192.168.1.50:8080",
            },
            "goal": {
                "type": "string",
                "description": "Goal to execute on the remote node.",
            },
            "agent": {
                "type": "string",
                "enum": ["simple", "react", "codeact", "autonomous"],
                "default": "simple",
            },
            "command": {
                "type": "string",
                "description": "Shell command to run on the remote node.",
            },
            "timeout": {
                "type": "integer",
                "default": 30,
                "description": "Timeout for remote command execution.",
            },
            "command": {
                "type": "string",
                "description": "Shell command for update_code (default: git pull).",
            },
            "restart_after_update": {
                "type": "boolean",
                "default": False,
                "description": "If true, restart each node after update_code succeeds.",
            },
            "source": {
                "type": "string",
                "default": "\\\\CASHMONEY\\Public\\JarvisOS\\JarvisOS-ready",
                "description": "Code source: git URL, local path, or Windows network share.",
            },
        },
        "required": ["action"],
    }
    permissions = ["network:read", "network:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "list_peers":
            return await self._list_peers()
        if action == "health_check":
            return await self._health_check(kwargs)
        if action == "system_stats":
            return await self._system_stats(kwargs)
        if action == "remote_audit":
            return await self._remote_audit(kwargs)
        if action == "remote_goal":
            return await self._remote_goal(kwargs)
        if action == "remote_command":
            return await self._remote_command(kwargs)
        if action == "restart_node":
            return await self._restart_node(kwargs)
        if action == "broadcast_goal":
            return await self._broadcast_goal(kwargs)
        if action == "sync_config":
            return await self._sync_config(kwargs)
        if action == "update_code":
            return await self._update_code(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _list_peers(self) -> dict[str, Any]:
        peers = await _local_peers()
        return {"peers": peers, "count": len(peers)}

    async def _peer_get(self, kwargs: dict[str, Any], path: str) -> dict[str, Any]:
        peer_url = kwargs.get("peer_url", "")
        if not peer_url:
            return {"error": "peer_url is required"}
        url = f"{peer_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers=_headers())
                r.raise_for_status()
                return r.json()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Request to {url} failed: {exc}"}

    async def _health_check(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return await self._peer_get(kwargs, "/api/fleet/health")

    async def _system_stats(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return await self._peer_get(kwargs, "/api/fleet/system")

    async def _remote_audit(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return await self._peer_get(kwargs, "/api/fleet/audit")

    async def _remote_goal(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        peer_url = kwargs.get("peer_url", "")
        goal = kwargs.get("goal", "")
        agent = kwargs.get("agent", "simple")
        if not peer_url:
            return {"error": "peer_url is required"}
        if not goal:
            return {"error": "goal is required"}
        url = f"{peer_url.rstrip('/')}/api/fleet/goal"
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                r = await client.post(url, headers=_headers(), json={"goal": goal, "agent": agent})
                r.raise_for_status()
                return r.json()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Remote goal failed: {exc}"}

    async def _remote_command(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        peer_url = kwargs.get("peer_url", "")
        command = kwargs.get("command", "")
        timeout = int(kwargs.get("timeout", 30))
        if not peer_url:
            return {"error": "peer_url is required"}
        if not command:
            return {"error": "command is required"}
        url = f"{peer_url.rstrip('/')}/api/fleet/command"
        try:
            async with httpx.AsyncClient(timeout=timeout + 10) as client:
                r = await client.post(url, headers=_headers(), json={"command": command, "timeout": timeout})
                r.raise_for_status()
                return r.json()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Remote command failed: {exc}"}

    async def _restart_node(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        peer_url = kwargs.get("peer_url", "")
        if not peer_url:
            return {"error": "peer_url is required"}
        url = f"{peer_url.rstrip('/')}/api/fleet/restart"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, headers=_headers())
                r.raise_for_status()
                return r.json()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Restart request failed: {exc}"}

    async def _broadcast_goal(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        goal = kwargs.get("goal", "")
        agent = kwargs.get("agent", "simple")
        if not goal:
            return {"error": "goal is required"}
        peers = await _local_peers()
        if not peers:
            return {"error": "No peers discovered"}

        async def send_one(peer: dict[str, Any]) -> dict[str, Any]:
            url = peer.get("url")
            if not url:
                return {"peer": peer.get("ip"), "error": "no url"}
            result = await self._remote_goal({"peer_url": url, "goal": goal, "agent": agent})
            return {"peer": peer.get("ip"), "name": peer.get("name"), "result": result}

        results = await asyncio.gather(*[send_one(p) for p in peers])
        return {"goal": goal, "peers_reached": len(peers), "results": results}

    async def _sync_config(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Push this node's config to every discovered peer."""
        cfg = _load_full_config()
        if not cfg:
            return {"error": "Could not read local config file"}
        # Never push the LLM api_key explicitly unless the user intended to.
        # The remote /api/fleet/config endpoint preserves existing keys when blank.
        peers = await _local_peers()
        if not peers:
            return {"error": "No peers discovered"}

        async def push_one(peer: dict[str, Any]) -> dict[str, Any]:
            url = peer.get("url")
            if not url:
                return {"peer": peer.get("ip"), "error": "no url"}
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.post(
                        f"{url.rstrip('/')}/api/fleet/config",
                        headers=_headers(),
                        json={"updates": cfg},
                    )
                    r.raise_for_status()
                    return {"peer": peer.get("ip"), "name": peer.get("name"), "result": r.json()}
            except Exception as exc:  # noqa: BLE001
                return {"peer": peer.get("ip"), "name": peer.get("name"), "error": str(exc)}

        results = await asyncio.gather(*[push_one(p) for p in peers])
        return {"action": "sync_config", "peers_reached": len(peers), "results": results}

    def _build_update_command(self, source: str) -> str:
        """Generate an update command for a given source type."""
        source = source.strip()
        if not source:
            source = r"\\CASHMONEY\Public\JarvisOS\JarvisOS-ready"

        # Windows UNC share or local Windows path -> robocopy mirror
        if source.startswith(r"\\") or (len(source) > 1 and source[1] == ":"):
            return (
                f'robocopy "{source}" "%CD%" /MIR '
                '/XD .venv .git __pycache__ node_modules '
                '/XF *.pyc'
            )

        # Git URL
        if source.startswith(("http://", "https://", "git@")):
            return f'git pull "{source}" || (git clone "{source}" . && git pull)'

        # Default: treat as path
        return (
            f'robocopy "{source}" "%CD%" /MIR '
            '/XD .venv .git __pycache__ node_modules '
            '/XF *.pyc'
        )

    async def _update_code(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Run a shell command on every peer to update code from a shared source."""
        source = kwargs.get("source", r"\\CASHMONEY\Public\JarvisOS\JarvisOS-ready")
        command = kwargs.get("command", self._build_update_command(source))
        restart_after = kwargs.get("restart_after_update", False)
        timeout = int(kwargs.get("timeout", 120))
        peers = await _local_peers()
        if not peers:
            return {"error": "No peers discovered"}

        async def update_one(peer: dict[str, Any]) -> dict[str, Any]:
            url = peer.get("url")
            if not url:
                return {"peer": peer.get("ip"), "error": "no url"}
            try:
                async with httpx.AsyncClient(timeout=timeout + 10) as client:
                    r = await client.post(
                        f"{url.rstrip('/')}/api/fleet/command",
                        headers=_headers(),
                        json={"command": command, "timeout": timeout},
                    )
                    r.raise_for_status()
                    result = r.json()
                    out = {"peer": peer.get("ip"), "name": peer.get("name"), "result": result}
                    if restart_after and result.get("returncode") == 0:
                        try:
                            await client.post(f"{url.rstrip('/')}/api/fleet/restart", headers=_headers())
                            out["restart"] = "requested"
                        except Exception as exc:  # noqa: BLE001
                            out["restart_error"] = str(exc)
                    return out
            except Exception as exc:  # noqa: BLE001
                return {"peer": peer.get("ip"), "name": peer.get("name"), "error": str(exc)}

        results = await asyncio.gather(*[update_one(p) for p in peers])
        return {"action": "update_code", "command": command, "peers_reached": len(peers), "results": results}
