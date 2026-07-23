"""Netboot autoinstall API for Wolfpack enterprise deployment.

Serves nocloud-net user-data per MAC and keeps a registry of which machine
should become which persona/hub.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = REPO_ROOT / "appliance" / "autoinstall" / "user-data-netboot"
REGISTRY_PATH = REPO_ROOT / "data" / "netboot-registry.json"

router = APIRouter(tags=["netboot"])


def _normalize_mac(mac: str) -> str:
    """Lower-case, colon-separated MAC."""
    return re.sub(r"[^0-9a-fA-F]", "", mac).lower()


def _formatted_mac(mac: str) -> str:
    """Return MAC in aa:bb:cc:dd:ee:ff form."""
    plain = _normalize_mac(mac)
    return ":".join(plain[i : i + 2] for i in range(0, 12, 2))


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_registry(reg: dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)


def _get_entry(mac: str) -> dict[str, Any]:
    reg = _load_registry()
    key = _normalize_mac(mac)
    if key in reg and isinstance(reg[key], dict):
        return dict(reg[key])
    default = reg.get("__default__", {})
    return {
        "persona": default.get("persona", "ledger"),
        "hub_id": default.get("hub_id", "hub-ledger"),
        "wifi_ssid": default.get("wifi_ssid", "google"),
        "wifi_psk": default.get("wifi_psk", "kingking1007"),
    }


def _render_user_data(mac: str, request: Request) -> str:
    if not TEMPLATE_PATH.exists():
        raise HTTPException(status_code=500, detail="Netboot user-data template missing")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    entry = _get_entry(mac)
    base_url = str(request.base_url).rstrip("/")
    return (
        template.replace("{{MAC}}", _formatted_mac(mac))
        .replace("{{PERSONA}}", entry.get("persona", "ledger"))
        .replace("{{HUB_ID}}", entry.get("hub_id", "hub-ledger"))
        .replace("{{WIFI_SSID}}", entry.get("wifi_ssid", "google"))
        .replace("{{WIFI_PSK}}", entry.get("wifi_psk", "kingking1007"))
        .replace("{{NETBOOT_URL}}", base_url)
    )


class RegistryEntry(BaseModel):
    mac: str
    persona: str = "ledger"
    hub_id: str | None = None
    wifi_ssid: str = "google"
    wifi_psk: str = "kingking1007"
    status: str = "pending"
    ip: str | None = None


@router.get("/autoinstall/{mac}")
async def autoinstall_user_data(mac: str, request: Request):
    """Return the cloud-init user-data for a given MAC."""
    return Response(content=_render_user_data(mac, request), media_type="text/plain")


@router.get("/autoinstall/{mac}/user-data")
async def autoinstall_user_data_explicit(mac: str, request: Request):
    """Explicit user-data path for nocloud-net."""
    return Response(content=_render_user_data(mac, request), media_type="text/plain")


@router.get("/autoinstall/{mac}/meta-data")
async def autoinstall_meta_data(mac: str):
    """Return empty meta-data for nocloud-net."""
    return Response(content="", media_type="text/plain")


@router.get("/api/netboot/status")
async def netboot_status():
    """Basic status of the netboot registry."""
    reg = _load_registry()
    entries = {k: v for k, v in reg.items() if not k.startswith("__")}
    return {
        "enabled": TEMPLATE_PATH.exists(),
        "template": str(TEMPLATE_PATH),
        "registry": str(REGISTRY_PATH),
        "registered_machines": len(entries),
        "pending": sum(1 for e in entries.values() if e.get("status") == "pending"),
    }


@router.get("/api/netboot/registry")
async def list_registry():
    """List all registered netboot targets."""
    return _load_registry()


@router.post("/api/netboot/registry")
async def register_machine(entry: RegistryEntry):
    """Register or update a MAC -> persona mapping."""
    reg = _load_registry()
    key = _normalize_mac(entry.mac)
    hub_id = entry.hub_id or f"hub-{entry.persona}"
    reg[key] = {
        "mac": _formatted_mac(entry.mac),
        "persona": entry.persona,
        "hub_id": hub_id,
        "wifi_ssid": entry.wifi_ssid,
        "wifi_psk": entry.wifi_psk,
        "status": entry.status,
        "ip": entry.ip,
    }
    _save_registry(reg)
    return {"ok": True, "mac": _formatted_mac(entry.mac), "hub_id": hub_id}


@router.get("/api/netboot/boot/{mac}")
async def boot_info(mac: str, request: Request):
    """Return boot URL and assigned persona for a MAC."""
    entry = _get_entry(mac)
    base_url = str(request.base_url).rstrip("/")
    return {
        "mac": _formatted_mac(mac),
        "autoinstall_url": f"{base_url}/autoinstall/{_normalize_mac(mac)}",
        **entry,
    }
