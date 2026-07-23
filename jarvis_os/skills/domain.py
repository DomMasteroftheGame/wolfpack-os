"""Domain registration skill.

Checks domain availability and prepares purchase/config payloads for popular
registrars. Live purchases require registrar API credentials; dry-run mode shows
exactly what would be done.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from typing import Any

import httpx

from jarvis_os.skills.base import Skill
from jarvis_os.skills.credentials import CredentialsSkill

logger = logging.getLogger(__name__)

# Popular TLDs to consider for a business name.
_POPULAR_TLDS = [".com", ".net", ".co", ".io", ".shop", ".store"]

# Placeholder registrar API endpoints.
_REGISTRARS = {
    "cloudflare": "https://api.cloudflare.com/client/v4/zones",
    "namecheap": "https://api.namecheap.com/xml.response",
    "porkbun": "https://porkbun.com/api/json/v3/domain/create",
}

_REGISTRAR_AUTH_URLS = {
    "cloudflare": "https://dash.cloudflare.com/profile/api-tokens",
    "namecheap": "https://ap.www.namecheap.com/settings/tools/apiaccess/",
    "porkbun": "https://porkbun.com/account/login",
}

_PLACEHOLDER_TOKENS = {
    "", "not_provided", "user_provided", "placeholder", "your_token",
    "your_api_key", "<token>", "<api_key>",
}


def _looks_real(token: str) -> bool:
    if not token or token.strip().lower() in _PLACEHOLDER_TOKENS:
        return False
    return True


async def _resolve_token(registrar: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Return {'api_token': ...} or a needs_auth dict."""
    api_token = kwargs.get("api_token", "")
    if _looks_real(api_token):
        return {"api_token": api_token}

    stored = await CredentialsSkill().run(action="get", provider=registrar)
    if stored and stored.get("found"):
        return {"api_token": stored["value"]}

    instructions = {
        "cloudflare": (
            "1. Log into Cloudflare.\n"
            "2. Go to My Profile > API Tokens > Create Token.\n"
            "3. Use the 'Edit zone DNS' template or create a custom token with "
            "Zone:Edit permissions.\n"
            "4. Paste the token below."
        ),
        "namecheap": (
            "1. Log into Namecheap.\n"
            "2. Go to Profile > Tools > API Access.\n"
            "3. Enable API access and copy the API key.\n"
            "4. Paste the key below."
        ),
        "porkbun": (
            "1. Log into Porkbun.\n"
            "2. Go to Account > API Access.\n"
            "3. Create an API key and copy it.\n"
            "4. Paste the key below."
        ),
    }.get(registrar, f"Log into {registrar} and generate an API token/key.")

    return await CredentialsSkill().run(
        action="request_auth",
        provider=registrar,
        auth_url=_REGISTRAR_AUTH_URLS.get(registrar, ""),
        instructions=instructions,
    )


class DomainSkill(Skill):
    """Check domain availability and generate registration payloads."""

    name = "domain"
    description = (
        "Check domain availability across popular TLDs and prepare registrar "
        "purchase payloads (Cloudflare, Namecheap, Porkbun). Dry-run by default."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["check_availability", "suggest_domains", "prepare_purchase"],
                "description": "Domain action to perform.",
            },
            "name": {
                "type": "string",
                "description": "Business or store name to base domain suggestions on.",
            },
            "domain": {
                "type": "string",
                "description": "Full domain to check, e.g. example.com.",
            },
            "tlds": {
                "type": "array",
                "items": {"type": "string"},
                "description": "TLDs to check. Defaults to popular set.",
            },
            "registrar": {
                "type": "string",
                "enum": ["cloudflare", "namecheap", "porkbun"],
                "default": "cloudflare",
                "description": "Registrar to prepare purchase payload for.",
            },
            "api_token": {
                "type": "string",
                "description": "Registrar API token (for live checks/purchases).",
            },
            "dry_run": {
                "type": "boolean",
                "default": True,
                "description": "If true, return planned API calls without executing.",
            },
        },
        "required": ["action"],
    }
    permissions = ["domain:check", "domain:purchase"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "check_availability":
            return await self._check_availability(kwargs)
        if action == "suggest_domains":
            return await self._suggest_domains(kwargs)
        if action == "prepare_purchase":
            return await self._prepare_purchase(kwargs)
        return {"error": f"Unknown action: {action}"}

    def _clean_name(self, name: str) -> str:
        """Turn a business name into a domain-safe slug."""
        slug = re.sub(r"[^a-zA-Z0-9]+", "", name).lower()
        return slug[:30] or "mybusiness"

    async def _check_availability(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        domain = kwargs.get("domain", "")
        if not domain:
            return {"error": "domain is required for check_availability"}

        # Lightweight heuristic: if the domain resolves, it's taken.
        try:
            socket.gethostbyname(domain)
            available = False
            reason = "DNS resolves; likely registered."
        except socket.gaierror:
            available = True
            reason = "No DNS record found; likely available."

        return {
            "action": "check_availability",
            "domain": domain,
            "available": available,
            "note": reason,
            "live_check": "Use a registrar API (Cloudflare/Namecheap/Porkbun) for authoritative availability.",
        }

    async def _suggest_domains(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("name", "")
        if not name:
            return {"error": "name is required for suggest_domains"}
        tlds = kwargs.get("tlds", _POPULAR_TLDS)
        slug = self._clean_name(name)

        candidates = [f"{slug}{tld}" for tld in tlds]
        # Add a couple of common variants.
        candidates.insert(1, f"get{slug}{tlds[0]}")
        if len(tlds) > 1:
            candidates.insert(2, f"{slug}official{tlds[0]}")

        # Check DNS availability for each.
        results: list[dict[str, Any]] = []
        for domain in candidates:
            try:
                socket.gethostbyname(domain)
                results.append({"domain": domain, "available": False, "reason": "DNS resolves"})
            except socket.gaierror:
                results.append({"domain": domain, "available": True, "reason": "No DNS record"})
            await asyncio.sleep(0.05)

        return {
            "action": "suggest_domains",
            "base_name": name,
            "slug": slug,
            "suggestions": results,
        }

    async def _prepare_purchase(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        domain = kwargs.get("domain", "")
        registrar = kwargs.get("registrar", "cloudflare")
        if not domain:
            return {"error": "domain is required for prepare_purchase"}
        if registrar not in _REGISTRARS:
            return {"error": f"Unsupported registrar: {registrar}"}

        dry_run = kwargs.get("dry_run", True)
        endpoint = _REGISTRARS[registrar]

        if registrar == "cloudflare":
            payload = {
                "name": domain,
                "account": {"id": "<ACCOUNT_ID>"},
                "jump_start": False,
            }
        elif registrar == "namecheap":
            payload = {
                "ApiUser": "<API_USER>",
                "ApiKey": "<API_KEY>",
                "UserName": "<API_USER>",
                "Command": "namecheap.domains.create",
                "DomainName": domain,
                "Years": "1",
            }
        else:  # porkbun
            payload = {
                "name": domain,
                "apikey": "<API_KEY>",
                "secretapikey": "<SECRET_KEY>",
            }

        if dry_run:
            return {
                "action": "prepare_purchase",
                "dry_run": True,
                "registrar": registrar,
                "domain": domain,
                "endpoint": endpoint,
                "method": "POST",
                "payload": payload,
                "note": "Replace placeholders with real credentials and set dry_run=false to execute.",
            }

        creds = await _resolve_token(registrar, kwargs)
        if creds is None or not creds.get("api_token"):
            return creds or {"error": "api_token is required for live purchase"}

        try:
            headers = {"Authorization": f"Bearer {creds['api_token']}"}
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                return {"action": "prepare_purchase", "registrar": registrar, "result": response.json()}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                await CredentialsSkill().run(action="delete", provider=registrar)
                return await _resolve_token(registrar, kwargs)
            return {"error": f"Purchase failed: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Purchase failed: {exc}"}
