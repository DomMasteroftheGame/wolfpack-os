"""Logo design skill.

Generates logo prompts and, if an image-generation API key is available,
creates logo files. Without an API key, it returns ready-to-use prompts for
DALL-E, Midjourney, Stable Diffusion, or Flux.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_LOGOS_DIR = Path(__file__).parent.parent.parent / "assets" / "logos"

_PLACEHOLDER_PATHS = ["/path/to", "/home/user", "/tmp", "/Users/user"]


def _resolve_output_dir(output_dir: str | None, default: Path) -> Path:
    if not output_dir:
        return default
    lowered = output_dir.lower().replace("\\", "/")
    for placeholder in _PLACEHOLDER_PATHS:
        if placeholder in lowered:
            return default
    return Path(output_dir).expanduser()


class LogoDesignSkill(Skill):
    """Generate logo concepts and optional image files for a brand."""

    name = "logo_design"
    description = (
        "Generate logo design prompts and create logo image files using an "
        "image generation API (DALL-E / OpenAI-compatible) if configured."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["generate_prompts", "create_logo"],
                "description": "Logo action to perform.",
            },
            "brand_name": {
                "type": "string",
                "description": "Brand or store name.",
            },
            "niche": {
                "type": "string",
                "description": "Business niche or style (e.g. 'tech accessories', 'cute pet brand').",
            },
            "style": {
                "type": "string",
                "enum": ["modern", "minimalist", "vintage", "playful", "luxury", "tech"],
                "default": "modern",
            },
            "image_api_key": {
                "type": "string",
                "description": "OpenAI-compatible image API key.",
            },
            "image_base_url": {
                "type": "string",
                "description": "OpenAI-compatible image API base URL (default DALL-E).",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to save generated logo files.",
            },
        },
        "required": ["action", "brand_name"],
    }
    permissions = ["image:generate", "file:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "generate_prompts":
            return await self._generate_prompts(kwargs)
        if action == "create_logo":
            return await self._create_logo(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _generate_prompts(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        brand = kwargs.get("brand_name", "")
        niche = kwargs.get("niche", "")
        style = kwargs.get("style", "modern")

        base = f"A {style} logo for '{brand}'"
        if niche:
            base += f", a {niche} brand"

        prompts = {
            "dalle": f"{base}, clean vector-style logo on white background, professional, high contrast, suitable for ecommerce",
            "midjourney": f"{base}, flat vector logo, 2D, minimal, white background, no text except '{brand}' --v 6",
            "stable_diffusion": f"{base}, vector logo, simple shapes, white background, centered, high quality",
            "flux": f"{base}, modern minimalist logo, crisp lines, white background, brand identity",
        }

        return {
            "action": "generate_prompts",
            "brand_name": brand,
            "niche": niche,
            "style": style,
            "prompts": prompts,
        }

    async def _create_logo(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        brand = kwargs.get("brand_name", "")
        api_key = kwargs.get("image_api_key", "")
        base_url = kwargs.get("image_base_url", "https://api.openai.com/v1")
        output_dir = _resolve_output_dir(kwargs.get("output_dir"), DEFAULT_LOGOS_DIR)

        if not api_key:
            prompts = await self._generate_prompts(kwargs)
            return {
                "action": "create_logo",
                "note": "No image API key provided. Use one of these prompts in an image generator.",
                "prompts": prompts["prompts"],
            }

        prompt_data = await self._generate_prompts(kwargs)
        prompt = prompt_data["prompts"]["dalle"]

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/images/generations",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"prompt": prompt, "n": 1, "size": "1024x1024", "response_format": "b64_json"},
                )
                response.raise_for_status()
                data = response.json()
                b64 = data["data"][0]["b64_json"]

                import base64

                output_dir.mkdir(parents=True, exist_ok=True)
                filename = output_dir / f"{brand.lower().replace(' ', '_')}_logo.png"
                filename.write_bytes(base64.b64decode(b64))
                return {
                    "action": "create_logo",
                    "file": str(filename),
                    "prompt": prompt,
                    "note": "Logo generated and saved locally.",
                }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Logo generation failed: {exc}"}
