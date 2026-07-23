"""USB build skill — create bootable Wolfpack migration USBs from the hub.

Delegates to the local GUI API so the skill works the same whether triggered
by voice, chat, or another agent.
"""
from __future__ import annotations

from typing import Any

import httpx

from jarvis_os.skills.base import Skill


class USBBuildSkill(Skill):
    """Build a bootable Wolfpack peer USB for enterprise migration."""

    name = "usb_build"
    description = (
        "Create a bootable USB that installs Ubuntu + Jarvis as a Wolfpack peer. "
        "Lists plugged USB devices, starts a build, and polls its status."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["devices", "build", "status", "jobs"],
                "description": "USB builder action.",
            },
            "target": {
                "type": "string",
                "description": "Block device path, e.g. /dev/sdb (required for build).",
            },
            "persona": {
                "type": "string",
                "default": "ledger",
                "description": "Wolfpack persona for the new peer.",
            },
            "hub_id": {
                "type": "string",
                "description": "Optional mesh hub_id; defaults to hub-<persona>.",
            },
            "dry_run": {
                "type": "boolean",
                "default": False,
                "description": "If true, build ISO only and do not write to USB.",
            },
            "job_id": {
                "type": "string",
                "description": "Job ID returned by build; required for status.",
            },
        },
        "required": ["action"],
    }
    permissions = ["shell:run"]

    def __init__(self, base_url: str = "http://127.0.0.1:8080"):
        self.base_url = base_url.rstrip("/")

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "devices")

        if action == "devices":
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(f"{self.base_url}/api/usb/devices")
                    return r.json()
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        if action == "build":
            target = kwargs.get("target", "")
            if not target:
                return {"ok": False, "error": "target block device required"}
            payload = {
                "target": target,
                "persona": kwargs.get("persona", "ledger"),
                "hub_id": kwargs.get("hub_id"),
                "dry_run": bool(kwargs.get("dry_run", False)),
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(
                        f"{self.base_url}/api/usb/build",
                        json=payload,
                    )
                    return r.json()
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        if action == "status":
            job_id = kwargs.get("job_id", "")
            if not job_id:
                return {"ok": False, "error": "job_id required"}
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(f"{self.base_url}/api/usb/build/status/{job_id}")
                    return r.json()
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        if action == "jobs":
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(f"{self.base_url}/api/usb/build/jobs")
                    return r.json()
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        return {"ok": False, "error": f"unknown action: {action}"}
