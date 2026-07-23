"""Base interface for LLM providers."""

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Abstract LLM provider."""

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        """Send messages and return {'content': str, ...}."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return embedding vector for text."""
