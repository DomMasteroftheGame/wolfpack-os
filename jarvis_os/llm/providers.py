"""Concrete LLM providers."""

import json
import logging
from typing import Any

import httpx

from jarvis_os.config import API_KEY_ENV_VARS, LLMConfig
from jarvis_os.llm.base import LLMProvider
from jarvis_os.llm.claude_cli import ClaudeCLIProvider
from jarvis_os.llm.kimi_cli import KimiCLIProvider

logger = logging.getLogger(__name__)

# Providers that carry their own auth and need no api_key in config.
KEYLESS_PROVIDERS = {"ollama", "claude_cli", "kimi_cli"}


class KimiProvider(LLMProvider):
    """Moonshot Kimi API provider."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.base_url = config.base_url or "https://api.moonshot.cn/v1"
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": "Bearer " + (config.api_key or "")},
            timeout=120.0,
        )

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            **kwargs,
        }
        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return {"content": data["choices"][0]["message"]["content"]}

    async def embed(self, text: str) -> list[float]:
        response = await self.client.post(
            "/embeddings",
            json={"model": "text-embedding", "input": text},
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]


class AnthropicProvider(LLMProvider):
    """Anthropic Claude / Fable API provider."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.base_url = config.base_url or "https://api.anthropic.com/v1"
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "x-api-key": config.api_key or "",
                "anthropic-version": "2023-06-01",
            },
            timeout=120.0,
        )

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        system = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system += m["content"] + "\n"
                continue
            chat_messages.append({"role": m["role"], "content": m["content"]})
        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": chat_messages,
            **kwargs,
        }
        if system:
            payload["system"] = system.strip()
        try:
            response = await self.client.post("/messages", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Anthropic API error: %s", response.text)
            raise exc
        data = response.json()
        blocks = data.get("content") or []
        parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        if not parts:
            parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("text")]
        return {"content": "".join(parts)}

    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError("Anthropic embeddings not implemented in this scaffold.")


class OpenAICompatibleProvider(LLMProvider):
    """Generic OpenAI-compatible endpoint."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.base_url = config.base_url or "https://api.openai.com/v1"
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": "Bearer " + (config.api_key or "")},
            timeout=120.0,
        )

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            **kwargs,
        }
        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return {"content": data["choices"][0]["message"]["content"]}

    async def embed(self, text: str) -> list[float]:
        response = await self.client.post(
            "/embeddings",
            json={"model": "text-embedding-3-small", "input": text},
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]


class OllamaProvider(LLMProvider):
    """Ollama local model provider."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.base_url = config.base_url or "http://localhost:11434"
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.config.temperature},
            **kwargs,
        }
        response = await self.client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        return {"content": data["message"]["content"]}

    async def embed(self, text: str) -> list[float]:
        response = await self.client.post(
            "/api/embeddings",
            json={"model": self.config.model, "prompt": text},
        )
        response.raise_for_status()
        data = response.json()
        return data["embedding"]


PROVIDERS = {
    "kimi": KimiProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAICompatibleProvider,
    "ollama": OllamaProvider,
    # Wolfpack defaults: authenticated local CLIs (subscription / OAuth).
    "claude_cli": ClaudeCLIProvider,
    "kimi_cli": KimiCLIProvider,
}


def get_provider(config: LLMConfig) -> LLMProvider:
    if config.provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {config.provider}. Choose from {list(PROVIDERS)}")
    if config.provider not in KEYLESS_PROVIDERS and not config.api_key:
        env_vars = ", ".join(API_KEY_ENV_VARS.get(config.provider, []))
        raise ValueError(
            f"No API key for provider '{config.provider}'. Set llm.api_key in the config file or one of: {env_vars}"
        )
    return PROVIDERS[config.provider](config)
