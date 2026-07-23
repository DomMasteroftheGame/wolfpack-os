"""External skill registry that loads agentskills.io compatible skills."""

from pathlib import Path

from jarvis_os.skills.agentskills import AgentSkill, load_skills_from_directory
from jarvis_os.skills.base import Skill
from jarvis_os.skills.registry import SkillRegistry


class ExternalSkillRegistry:
    """Wraps a SkillRegistry and loads external agentskills into it."""

    def __init__(self, registry: SkillRegistry, external_skills_dir: str | None = None):
        self.registry = registry
        self.external_skills_dir = external_skills_dir

    def load(self) -> list[AgentSkill]:
        """Load external skills from the configured directory and register them."""
        if not self.external_skills_dir:
            return []

        skills = load_skills_from_directory(Path(self.external_skills_dir))
        for skill in skills:
            self.registry.register(skill)
        return skills

    def get(self, name: str) -> Skill | None:
        return self.registry.get(name)

    def list(self) -> list[Skill]:
        return self.registry.list()
