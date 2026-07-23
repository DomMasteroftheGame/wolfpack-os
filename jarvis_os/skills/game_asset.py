"""Game asset generation skill.

Generates prompts for sprites, textures, sounds, and music. If an image or
audio API key is provided, it can create actual files; otherwise it returns
ready-to-use prompts.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_ASSETS_DIR = Path(__file__).parent.parent.parent / "games" / "assets"

_PLACEHOLDER_PATHS = ["/path/to", "/home/user", "/tmp", "/Users/user"]


def _resolve_output_dir(output_dir: str | None, default: Path) -> Path:
    if not output_dir:
        return default
    lowered = output_dir.lower().replace("\\", "/")
    for placeholder in _PLACEHOLDER_PATHS:
        if placeholder in lowered:
            return default
    return Path(output_dir).expanduser()


class GameAssetSkill(Skill):
    """Generate game asset prompts and optionally create asset files."""

    name = "game_asset"
    description = (
        "Generate prompts for game sprites, textures, sound effects, and music. "
        "Creates image files if an OpenAI-compatible image API key is provided."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["generate_prompts", "create_sprite", "create_texture", "sound_prompts"],
                "description": "Asset action.",
            },
            "game_name": {
                "type": "string",
                "description": "Name of the game.",
            },
            "asset_name": {
                "type": "string",
                "description": "Specific asset name, e.g. 'player_ship'.",
            },
            "style": {
                "type": "string",
                "default": "pixel art",
                "description": "Visual style (pixel art, 3D, vector, hand-drawn).",
            },
            "image_api_key": {
                "type": "string",
                "description": "OpenAI-compatible image API key.",
            },
            "image_base_url": {
                "type": "string",
                "default": "https://api.openai.com/v1",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to save generated assets.",
            },
        },
        "required": ["action"],
    }
    permissions = ["image:generate", "file:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "generate_prompts":
            return await self._generate_prompts(kwargs)
        if action == "create_sprite":
            return await self._create_image(kwargs, "sprite")
        if action == "create_texture":
            return await self._create_image(kwargs, "texture")
        if action == "sound_prompts":
            return await self._sound_prompts(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _generate_prompts(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        game = kwargs.get("game_name", "the game")
        style = kwargs.get("style", "pixel art")
        asset = kwargs.get("asset_name", "")

        base = f"{style} game asset for {game}"
        if asset:
            base += f", {asset}"

        prompts = {
            "player_sprite": f"{base}, player character, transparent background, single sprite, centered",
            "enemy_sprite": f"{base}, enemy character, transparent background, menacing but family-friendly",
            "background": f"{base}, seamless scrolling background, no text, atmospheric, 16:9 aspect",
            "icon": f"{base}, app icon, square, high contrast, no text",
            "powerup": f"{base}, collectible power-up item, glowing, transparent background",
        }
        return {"action": "generate_prompts", "game_name": game, "style": style, "prompts": prompts}

    async def _create_image(self, kwargs: dict[str, Any], kind: str) -> dict[str, Any]:
        game = kwargs.get("game_name", "game")
        asset = kwargs.get("asset_name", "asset")
        style = kwargs.get("style", "pixel art")
        api_key = kwargs.get("image_api_key", "")
        base_url = kwargs.get("image_base_url", "https://api.openai.com/v1")
        output_dir = _resolve_output_dir(kwargs.get("output_dir"), DEFAULT_ASSETS_DIR / game.lower().replace(" ", "_"))

        prompt = f"{style} {kind} for {game}: {asset}, game art, centered, suitable for a 2D game"
        if kind == "sprite":
            prompt += ", transparent or solid color background"

        if not api_key:
            return {
                "action": f"create_{kind}",
                "note": "No image API key provided. Use this prompt in an image generator.",
                "prompt": prompt,
            }

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

                output_dir.mkdir(parents=True, exist_ok=True)
                filename = output_dir / f"{asset.lower().replace(' ', '_')}_{kind}.png"
                filename.write_bytes(base64.b64decode(b64))
                return {
                    "action": f"create_{kind}",
                    "file": str(filename),
                    "prompt": prompt,
                }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Asset generation failed: {exc}"}

    async def _sound_prompts(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        game = kwargs.get("game_name", "the game")
        return {
            "action": "sound_prompts",
            "game_name": game,
            "prompts": {
                "jump": f"8-bit jump sound effect for {game}, short, cheerful",
                "shoot": f"8-bit laser shoot sound effect for {game}, short",
                "explosion": f"8-bit explosion sound effect for {game}, medium impact",
                "collect": f"8-bit coin/collect sound effect for {game}, bright",
                "bgm": f"Upbeat chiptune background music loop for {game}, 60 seconds",
            },
            "tools": ["sfxr", "LabChirp", "Bfxr", "SunVox", "LMMS"],
        }
