"""Loader for agentskills.io compatible instruction skills."""

import logging
from pathlib import Path
from typing import Any

import yaml

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)


class AgentSkill(Skill):
    """An instruction-based skill loaded from an agentskills.io compatible SKILL.md."""

    metadata: dict[str, Any] = {}
    instructions: str = ""

    def __init__(
        self,
        name: str,
        description: str,
        instructions: str,
        metadata: dict[str, Any] | None = None,
    ):
        self.name = name
        self.description = description
        self.instructions = instructions
        self.metadata = metadata or {}
        self.schema = {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task or prompt to apply this skill to.",
                },
                "prompt": {
                    "type": "string",
                    "description": "Alias for task. The task or prompt to apply this skill to.",
                },
            },
        }
        self.permissions: list[str] = []

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        """Return the skill instructions plus the provided task for planner context."""
        task = kwargs.get("task") or kwargs.get("prompt") or ""
        return {
            "skill": self.name,
            "instructions": self.instructions,
            "task": task,
        }


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Returns a tuple of (frontmatter_dict, body).
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter_text = parts[1].strip()
    body = parts[2].strip()

    if not frontmatter_text:
        return {}, body

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse skill frontmatter: %s", exc)
        frontmatter = {}

    return frontmatter, body


def load_agent_skill(path: Path) -> AgentSkill:
    """Load an AgentSkill from a SKILL.md file."""
    content = path.read_text(encoding="utf-8")
    frontmatter, body = _parse_frontmatter(content)

    name = frontmatter.get("name", path.parent.name)
    description = frontmatter.get("description", "")
    metadata = {
        key: value
        for key, value in frontmatter.items()
        if key not in ("name", "description")
    }

    return AgentSkill(
        name=name,
        description=description,
        instructions=body,
        metadata=metadata,
    )


def load_skills_from_directory(directory: Path) -> list[AgentSkill]:
    """Load all agentskills-compatible skills from a directory tree."""
    skills: list[AgentSkill] = []
    if not directory.exists():
        logger.warning("External skills directory does not exist: %s", directory)
        return skills

    for skill_file in directory.rglob("SKILL.md"):
        try:
            skills.append(load_agent_skill(skill_file))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load skill from %s: %s", skill_file, exc)

    return skills
