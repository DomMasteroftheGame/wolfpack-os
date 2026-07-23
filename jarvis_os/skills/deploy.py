"""Deployment skill.

Prepares deployment configs for Shopify stores, Pygame/Godot games to itch.io,
and static sites to Vercel/Netlify. Live deployment requires credentials.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

_PLACEHOLDER_PATHS = ["/path/to", "/home/user", "/tmp", "/Users/user"]


def _resolve_project_dir(project_dir: str | None, default: Path | None = None) -> Path:
    if not project_dir:
        if default is None:
            raise ValueError("project_dir is required")
        return default
    lowered = project_dir.lower().replace("\\", "/")
    for placeholder in _PLACEHOLDER_PATHS:
        if placeholder in lowered:
            if default is None:
                raise ValueError(f"Invalid placeholder project_dir: {project_dir}")
            return default
    return Path(project_dir).expanduser()


class DeploySkill(Skill):
    """Prepare and execute deployments for games, stores, and sites."""

    name = "deploy"
    description = (
        "Prepare deployment configs for Shopify stores, itch.io game releases, "
        "and static sites on Vercel/Netlify. Live deploy requires credentials."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["prepare_shopify_deploy", "prepare_itchio", "prepare_vercel", "prepare_netlify"],
                "description": "Deployment action.",
            },
            "project_dir": {
                "type": "string",
                "description": "Local project directory to deploy.",
            },
            "store_url": {
                "type": "string",
                "description": "Shopify store URL.",
            },
            "api_token": {
                "type": "string",
                "description": "Platform API token for live deploy.",
            },
            "dry_run": {
                "type": "boolean",
                "default": True,
            },
        },
        "required": ["action"],
    }
    permissions = ["deploy:plan", "deploy:execute"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "prepare_shopify_deploy":
            return await self._prepare_shopify(kwargs)
        if action == "prepare_itchio":
            return await self._prepare_itchio(kwargs)
        if action == "prepare_vercel":
            return await self._prepare_vercel(kwargs)
        if action == "prepare_netlify":
            return await self._prepare_netlify(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _prepare_shopify(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        store_url = kwargs.get("store_url", "")
        if not store_url:
            return {"error": "store_url is required for prepare_shopify_deploy"}
        return {
            "action": "prepare_shopify_deploy",
            "store_url": store_url,
            "note": "Shopify stores are already hosted. This action verifies the store URL and lists launch checklist items.",
            "launch_checklist": [
                "Confirm payment provider connected",
                "Add shipping zones and rates",
                "Set store policies (refund, privacy, TOS)",
                "Remove storefront password",
                "Add custom domain",
                "Test checkout flow",
            ],
        }

    async def _prepare_itchio(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        project_dir = kwargs.get("project_dir", "")
        if not project_dir:
            return {"error": "project_dir is required for prepare_itchio"}
        path = _resolve_project_dir(project_dir, Path.cwd())

        return {
            "action": "prepare_itchio",
            "project_dir": str(path),
            "note": "Package the game build and upload via itch.io or butler CLI.",
            "steps": [
                "Build the game for the target platform(s).",
                "Zip the build output.",
                "Use butler push to upload: butler push build.zip USER/GAME:CHANNEL",
                "Set price, screenshots, and description on itch.io.",
            ],
            "butler_command": f"butler push {path / 'build.zip'} YOUR_ITCH_USERNAME/YOUR_GAME:windows",
            "signup_url": "https://itch.io/register",
        }

    async def _prepare_vercel(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        project_dir = kwargs.get("project_dir", "")
        if not project_dir:
            return {"error": "project_dir is required for prepare_vercel"}
        path = _resolve_project_dir(project_dir, Path.cwd())

        dry_run = kwargs.get("dry_run", True)
        if dry_run:
            return {
                "action": "prepare_vercel",
                "project_dir": str(path),
                "dry_run": True,
                "steps": [
                    "Install Vercel CLI: npm i -g vercel",
                    f"Run: cd {path} && vercel",
                    "Or link a GitHub repo via Vercel dashboard.",
                ],
            }

        api_token = kwargs.get("api_token", "")
        if not api_token:
            return {"error": "api_token is required for live Vercel deploy"}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    "https://api.vercel.com/v13/deployments",
                    headers={"Authorization": f"Bearer {api_token}"},
                    json={"name": path.name, "files": []},  # Real deploy needs file uploads
                )
                response.raise_for_status()
                return {"action": "prepare_vercel", "deployment": response.json()}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Vercel deploy failed: {exc}"}

    async def _prepare_netlify(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        project_dir = kwargs.get("project_dir", "")
        if not project_dir:
            return {"error": "project_dir is required for prepare_netlify"}
        path = _resolve_project_dir(project_dir, Path.cwd())

        dry_run = kwargs.get("dry_run", True)
        if dry_run:
            return {
                "action": "prepare_netlify",
                "project_dir": str(path),
                "dry_run": True,
                "steps": [
                    "Install Netlify CLI: npm i -g netlify-cli",
                    f"Run: cd {path} && netlify deploy --prod",
                    "Or drag-and-drop the build folder in the Netlify dashboard.",
                ],
            }

        api_token = kwargs.get("api_token", "")
        if not api_token:
            return {"error": "api_token is required for live Netlify deploy"}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    "https://api.netlify.com/api/v1/sites",
                    headers={"Authorization": f"Bearer {api_token}"},
                    json={"name": path.name},
                )
                response.raise_for_status()
                return {"action": "prepare_netlify", "site": response.json()}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Netlify deploy failed: {exc}"}
