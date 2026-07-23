"""Base skill interface."""

from abc import ABC, abstractmethod
from typing import Any


class Skill(ABC):
    """A capability exposed to the LLM as a tool."""

    name: str = ""
    description: str = ""
    schema: dict[str, Any] = {}
    permissions: list[str] = []

    @abstractmethod
    async def run(self, **kwargs: Any) -> Any:
        """Execute the skill and return a JSON-serializable result."""
