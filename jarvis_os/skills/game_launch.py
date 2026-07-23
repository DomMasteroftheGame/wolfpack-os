"""Game launch orchestrator.

Chains market research, concept generation, project scaffold, asset prompts,
and deployment plan into one skill for Roblox, Pygame, Godot, or Unity games.
"""

from __future__ import annotations

import logging
from typing import Any

from jarvis_os.skills.base import Skill
from jarvis_os.skills.deploy import DeploySkill
from jarvis_os.skills.game_asset import GameAssetSkill
from jarvis_os.skills.game_dev import GameDevSkill
from jarvis_os.skills.game_market_research import GameMarketResearchSkill
from jarvis_os.skills.roblox import RobloxSkill
from jarvis_os.skills.social_media import SocialMediaSkill

logger = logging.getLogger(__name__)


class GameLaunchSkill(Skill):
    """Orchestrate a full game development and launch plan."""

    name = "game_launch"
    description = (
        "Use this tool when the user wants to launch a game, create a Roblox game, "
        "make a video game, or start a game project. It researches trending games, "
        "generates a concept, scaffolds the project (Roblox/Pygame/Godot/Unity), "
        "generates asset prompts, and prepares deployment — all in one call."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["launch_game"],
                "description": "Game launch action.",
            },
            "engine": {
                "type": "string",
                "enum": ["roblox", "pygame", "godot", "unity"],
                "default": "roblox",
                "description": "Game engine to use.",
            },
            "genre": {
                "type": "string",
                "description": "Optional genre to research. If omitted, trending games are researched.",
            },
            "project_name": {
                "type": "string",
                "description": "Game project name. If omitted, one is generated.",
            },
        },
        "required": ["action"],
    }
    permissions = ["game:plan", "file:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "launch_game":
            return await self._launch_game(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _launch_game(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        engine = kwargs.get("engine", "roblox")
        genre = kwargs.get("genre", "")
        project_name = kwargs.get("project_name", "")

        # 1. Research trending games.
        research = GameMarketResearchSkill()
        if genre:
            research_result = await research.run(action="research_genre", genre=genre, platform="roblox" if engine == "roblox" else "steam")
            findings = research_result.get("results", [])
            # Fall back to general trending games if genre search yields nothing.
            if not findings:
                research_result = await research.run(action="find_trending_games")
                findings = research_result.get("results", [])
        else:
            research_result = await research.run(action="find_trending_games")
            findings = research_result.get("results", [])

        # 2. Generate game concept.
        if findings:
            concept_result = await research.run(action="generate_game_concept", findings=findings)
            concept = concept_result.get("concept", {})
        else:
            concept = {}

        # Use generated or provided project name.
        if not project_name:
            names = concept.get("game_names_found", [])
            project_name = names[0] if names else f"My{engine.capitalize()}Game"
            # Sanitize.
            project_name = "".join(c for c in project_name if c.isalnum() or c.isspace()).strip() or f"My{engine.capitalize()}Game"
            project_name = project_name.replace(" ", "")

        # 3. Scaffold project.
        if engine == "roblox":
            dev = RobloxSkill()
            project_result = await dev.run(action="create_project", project_name=project_name, game_type=genre or "obby")
        else:
            dev = GameDevSkill()
            project_result = await dev.run(
                action="create_project",
                engine=engine,
                project_name=project_name,
                game_type=genre or concept.get("genre_focus", "arcade"),
            )

        # 4. Asset prompts.
        assets = GameAssetSkill()
        asset_result = await assets.run(action="generate_prompts", game_name=project_name)

        # 5. Deployment plan.
        deploy = DeploySkill()
        if engine == "roblox":
            deploy_result = await deploy.run(action="prepare_itchio", project_dir=project_result.get("project_dir", ""))
        else:
            deploy_result = await deploy.run(action="prepare_itchio", project_dir=project_result.get("project_dir", ""))

        # 6. Social media for the game.
        social = SocialMediaSkill()
        social_result = await social.run(
            action="generate_presence",
            brand_name=project_name,
            niche=concept.get("genre_focus", "indie game"),
        )

        return {
            "action": "launch_game",
            "engine": engine,
            "project_name": project_name,
            "concept": concept,
            "project_dir": project_result.get("project_dir"),
            "files_created": project_result.get("files_created", []),
            "asset_prompts": asset_result.get("prompts", {}),
            "deployment_plan": deploy_result,
            "social_plan": social_result.get("profiles", {}),
            "launch_checklist": [
                "Build core game loop in the chosen engine",
                "Generate sprites/textures/sounds using asset prompts",
                "Playtest and iterate",
                "Create store page (Roblox / itch.io / Steam)",
                "Record trailer / screenshots",
                "Set up social media accounts",
                "Publish and announce",
            ],
        }
