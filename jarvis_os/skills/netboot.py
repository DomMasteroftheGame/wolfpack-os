"""Netboot skill — register and manage Wolfpack network-boot deployments.

Allows the pack to register a target MAC, assign a persona/hub-id, and query
the netboot hub status. The actual PXE/iPXE service lives in
jarvis_os/interfaces/gui/netboot_router.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from jarvis_os.skills.base import Skill

DEFAULT_REGISTRY = Path("/opt/jarvis-os/data/netboot-registry.json")


class NetbootSkill(Skill):
    """Manage network-boot deployments for Wolfpack peers."""

    name = "netboot"
    description = (
        "Register target machines for PXE/network boot, assign personas/hub-ids, "
        "and check the netboot hub status."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["register", "list", "status", "boot_url"],
                "description": "Netboot action.",
            },
            "mac": {"type": "string", "description": "Target MAC address."},
            "persona": {
                "type": "string",
                "description": "Wolfpack persona (ceo, tech, ledger, etc.)",
            },
            "hub_id": {
                "type": "string",
                "description": "Optional mesh hub_id; defaults to hub-<persona>.",
            },
            "wifi_ssid": {"type": "string", "description": "WiFi SSID for the peer."},
            "wifi_psk": {"type": "string", "description": "WiFi password for the peer."},
            "ip": {"type": "string", "description": "Known IP of the target."},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.registry_path = DEFAULT_REGISTRY

    def _load_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {}
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _normalize_mac(self, mac: str) -> str:
        return "".join(c for c in mac if c.isalnum()).lower()

    def _format_mac(self, mac: str) -> str:
        plain = self._normalize_mac(mac)
        return ":".join(plain[i : i + 2] for i in range(0, 12, 2))

    def run(self, action: str, **kwargs: Any) -> dict[str, Any]:
        if action == "register":
            mac = kwargs.get("mac", "")
            if not mac:
                return {"ok": False, "error": "mac required"}
            persona = kwargs.get("persona", "ledger")
            hub_id = kwargs.get("hub_id") or f"hub-{persona}"
            reg = self._load_registry()
            key = self._normalize_mac(mac)
            reg[key] = {
                "mac": self._format_mac(mac),
                "persona": persona,
                "hub_id": hub_id,
                "wifi_ssid": kwargs.get("wifi_ssid", "google"),
                "wifi_psk": kwargs.get("wifi_psk", "kingking1007"),
                "status": kwargs.get("status", "pending"),
                "ip": kwargs.get("ip"),
            }
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump(reg, f, indent=2)
            return {"ok": True, "mac": reg[key]["mac"], "hub_id": hub_id}

        if action == "list":
            return {
                "machines": {
                    k: v for k, v in self._load_registry().items() if not k.startswith("__")
                }
            }

        if action == "status":
            try:
                with httpx.Client(timeout=5.0) as client:
                    r = client.get("http://127.0.0.1:8080/api/netboot/status")
                    return r.json()
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        if action == "boot_url":
            mac = kwargs.get("mac", "")
            if not mac:
                return {"ok": False, "error": "mac required"}
            try:
                with httpx.Client(timeout=5.0) as client:
                    r = client.get(f"http://127.0.0.1:8080/api/netboot/boot/{mac}")
                    return r.json()
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        return {"ok": False, "error": f"unknown action: {action}"}
