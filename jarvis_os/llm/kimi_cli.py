"""Kimi Code CLI provider.

Reuses the authenticated Kimi Code CLI session (OAuth tokens in
~/.kimi-code/credentials/) instead of a separate Moonshot API key. The `kimi`
CLI handles its own auth, so no API key is required in the Jarvis OS config.

Config:
  llm:
    provider: kimi_cli
    model: kimi-code/kimi-for-coding   # a model alias from ~/.kimi-code/config.toml
    base_url: /path/to/kimi             # optional: override the CLI path (default: `kimi`)
Env override: KIMI_CLI_PATH.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any

from jarvis_os.config import LLMConfig
from jarvis_os.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class KimiCLIProvider(LLMProvider):
    """Drives the local `kimi -p` CLI as a chat backend."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.cli_path = os.environ.get("KIMI_CLI_PATH") or config.base_url or "kimi"

    @staticmethod
    def _render(messages: list[dict[str, str]]) -> str:
        """Render messages into a single prompt string.

        System messages are prepended as instructions; user/assistant turns are
        rendered as a conversation. The CLI is one-shot per invocation.
        """
        system_parts: list[str] = []
        convo: list[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if not content:
                continue
            if role == "system":
                system_parts.append(content)
            elif role == "assistant":
                convo.append(f"Assistant: {content}")
            else:
                convo.append(f"User: {content}")
        prompt = "\n\n".join(convo).strip()
        if system_parts:
            system = "\n\n".join(system_parts).strip()
            prompt = f"System instructions:\n{system}\n\n{prompt}"
        return prompt

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        if not shutil.which(self.cli_path) and not os.path.isfile(self.cli_path):
            raise RuntimeError(
                f"Kimi CLI not found at '{self.cli_path}'. Install Kimi Code and run "
                f"`kimi login`, or set llm.base_url / KIMI_CLI_PATH."
            )

        cmd = [self.cli_path, "-p", self._render(messages), "--output-format", "stream-json"]
        if self.config.model:
            cmd += ["-m", self.config.model]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"kimi -p failed (exit {proc.returncode}): {stderr.decode('utf-8', 'replace').strip()}"
            )
        return self._parse_stdout(stdout.decode("utf-8", "replace"))

    @staticmethod
    def _parse_stdout(text: str) -> dict[str, str]:
        """Parse the first assistant message from stream-json output."""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("role") == "assistant" and "content" in msg:
                return {"content": str(msg["content"]).strip()}
        # Fallback: return everything if we couldn't parse.
        return {"content": text.strip()}

    async def embed(self, text: str) -> list[float]:
        # The Kimi Code CLI has no embeddings endpoint. Semantic memory should use
        # a local embedder (Ollama via memory.embed_url) or run with semantic: false.
        raise NotImplementedError(
            "kimi_cli has no embeddings; set memory.semantic=false or memory.embed_url "
            "to a local Ollama embedder."
        )
