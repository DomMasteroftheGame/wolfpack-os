"""Secure credential vault skill.

Stores provider API tokens/keys in an encrypted local file. On Windows the
encryption key is itself protected by DPAPI, so the vault is tied to the user
account. Other platforms fall back to a Fernet key stored in the data directory.

This skill is the bridge that lets commerce skills ask the user to log in when
credentials are missing: they return a `needs_auth` handoff, the GUI collects
the token, and the token is stored here for future live calls.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"
KEY_FILE = "vault_key.enc"
CREDS_FILE = "credentials.enc"


def _data_dir() -> Path:
    path = DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------- Windows DPAPI helpers ----------

class _DATA_BLOB:
    """Minimal ctypes wrapper for CryptProtectData/CryptUnprotectData."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._DATA_BLOB = type(
            "DATA_BLOB",
            (ctypes.Structure,),
            {
                "_fields_": [
                    ("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
                ]
            },
        )

    def protect(self, data: bytes) -> bytes:
        import ctypes

        blob_in = self._DATA_BLOB()
        blob_in.cbData = len(data)
        blob_in.pbData = ctypes.cast(data, ctypes.POINTER(ctypes.c_ubyte))
        blob_out = self._DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            raise OSError("CryptProtectData failed")
        return bytes(blob_out.pbData[: blob_out.cbData])

    def unprotect(self, data: bytes) -> bytes:
        import ctypes

        blob_in = self._DATA_BLOB()
        blob_in.cbData = len(data)
        blob_in.pbData = ctypes.cast(data, ctypes.POINTER(ctypes.c_ubyte))
        blob_out = self._DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            raise OSError("CryptUnprotectData failed")
        return bytes(blob_out.pbData[: blob_out.cbData])


def _dpapi_available() -> bool:
    return os.name == "nt"


def _load_or_create_key(data_dir: Path) -> bytes:
    """Return the raw Fernet key bytes, creating and protecting it if needed."""
    key_path = data_dir / KEY_FILE
    if key_path.exists():
        encrypted = key_path.read_bytes()
        if _dpapi_available():
            try:
                return _DATA_BLOB().unprotect(encrypted)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to unprotect vault key with DPAPI: %s", exc)
                raise
        return encrypted

    key = Fernet.generate_key()
    if _dpapi_available():
        encrypted = _DATA_BLOB().protect(key)
    else:
        encrypted = key
    key_path.write_bytes(encrypted)
    return key


def _fernet(data_dir: Path) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_load_or_create_key(data_dir)[:32]))


def _load_creds(data_dir: Path) -> dict[str, str]:
    creds_path = data_dir / CREDS_FILE
    if not creds_path.exists():
        return {}
    try:
        f = _fernet(data_dir)
        decrypted = f.decrypt(creds_path.read_bytes()).decode("utf-8")
        return json.loads(decrypted)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to decrypt credentials vault: %s", exc)
        return {}


def _save_creds(data_dir: Path, creds: dict[str, str]) -> None:
    creds_path = data_dir / CREDS_FILE
    f = _fernet(data_dir)
    encrypted = f.encrypt(json.dumps(creds).encode("utf-8"))
    creds_path.write_bytes(encrypted)


# ---------- skill ----------

class CredentialsSkill(Skill):
    """Securely store and retrieve API tokens/keys for live service integrations."""

    name = "credentials"
    description = (
        "Secure credential vault: get, set, and request authentication tokens "
        "for Shopify, Stripe, domain registrars, and other live APIs."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "set", "has", "delete", "request_auth"],
                "description": "Credential action.",
            },
            "provider": {
                "type": "string",
                "description": "Provider name, e.g. shopify, stripe, cloudflare, namecheap, porkbun.",
            },
            "value": {
                "type": "string",
                "description": "Token/key to store (only for set).",
            },
            "auth_url": {
                "type": "string",
                "description": "URL the user should open to log in (only for request_auth).",
            },
            "instructions": {
                "type": "string",
                "description": "Human instructions for obtaining the token (only for request_auth).",
            },
            "extra_fields": {
                "type": "array",
                "description": "Additional fields to collect during auth (only for request_auth). Each item is {name, label, provider?}.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "label": {"type": "string"},
                        "provider": {"type": "string"},
                    },
                    "required": ["name", "label"],
                },
            },
        },
        "required": ["action", "provider"],
    }
    permissions = ["file:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        provider = kwargs.get("provider", "")
        if not provider:
            return {"error": "provider is required"}

        data_dir = _data_dir()

        if action == "get":
            creds = _load_creds(data_dir)
            value = creds.get(provider)
            if value is None:
                return {
                    "provider": provider,
                    "found": False,
                    "note": "No credential stored. Use request_auth to ask the user to log in.",
                }
            return {"provider": provider, "found": True, "value": value}

        if action == "set":
            values = kwargs.get("values")
            if isinstance(values, dict) and values:
                creds = _load_creds(data_dir)
                for key, val in values.items():
                    if val:
                        creds[key] = val
                _save_creds(data_dir, creds)
                logger.info("Stored credentials for providers: %s", list(values.keys()))
                return {"providers": list(values.keys()), "stored": True}
            value = kwargs.get("value", "")
            if not value:
                return {"error": "value or values is required for set"}
            creds = _load_creds(data_dir)
            creds[provider] = value
            _save_creds(data_dir, creds)
            logger.info("Stored credential for provider: %s", provider)
            return {"provider": provider, "stored": True}

        if action == "has":
            creds = _load_creds(data_dir)
            return {"provider": provider, "has": provider in creds}

        if action == "delete":
            creds = _load_creds(data_dir)
            removed = creds.pop(provider, None)
            _save_creds(data_dir, creds)
            return {"provider": provider, "deleted": removed is not None}

        if action == "request_auth":
            return {
                "needs_auth": True,
                "provider": provider,
                "auth_url": kwargs.get("auth_url", ""),
                "instructions": kwargs.get(
                    "instructions",
                    f"Log into {provider} and generate an API token/key for Jarvis.",
                ),
                "extra_fields": kwargs.get("extra_fields", []),
                "next_step": "Paste the token in the auth prompt and click Continue.",
            }

        return {"error": f"Unknown action: {action}"}
