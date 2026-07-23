"""Claude Code CLI provider — the Wolfpack's non-negotiable LLM path.

The pack runs on the **Claude Code subscription, NOT a metered per-token API**
(the `WOLFPACK_USE_CLI=1` rule in the hub). This provider shells out to the local
`claude --print` CLI instead of hitting api.anthropic.com, so every agent turn is
billed to the subscription. No API key is required — the CLI carries its own auth
from `claude login`.

Config:
  llm:
    provider: claude_cli
    model: claude-opus-4-6        # or a sonnet/haiku alias; passed to --model
    base_url: /path/to/claude     # optional: override the CLI path (default: `claude`)
Env override: CLAUDE_CLI_PATH.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Any

from jarvis_os.config import LLMConfig
from jarvis_os.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class ClaudeCLIProvider(LLMProvider):
    """Drives `claude --print` (Claude Code subscription) as a chat backend."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.cli_path = os.environ.get("CLAUDE_CLI_PATH") or config.base_url or "claude"

    @staticmethod
    def _split(messages: list[dict[str, str]]) -> tuple[str, str]:
        """Return (system_prompt, prompt). System messages are concatenated into the
        system prompt; the remaining turns are rendered into a single prompt that ends
        on the latest user message (the CLI is one-shot per invocation)."""
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
            else:  # user / tool / anything else -> user turn
                convo.append(f"User: {content}")
        return "\n\n".join(system_parts).strip(), "\n\n".join(convo).strip()

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        if not shutil.which(self.cli_path) and not os.path.isfile(self.cli_path):
            raise RuntimeError(
                f"Claude CLI not found at '{self.cli_path}'. Install Claude Code and run "
                f"`claude login`, or set llm.base_url / CLAUDE_CLI_PATH."
            )

        system, prompt = self._split(messages)
        cmd = [self.cli_path, "--print"]
        if self.config.model:
            cmd += ["--model", self.config.model]
        if system:
            cmd += ["--append-system-prompt", system]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(prompt.encode("utf-8"))
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude --print failed (exit {proc.returncode}): {stderr.decode('utf-8', 'replace').strip()}"
            )
        return {"content": stdout.decode("utf-8", "replace").strip()}

    async def embed(self, text: str) -> list[float]:
        # The subscription CLI has no embeddings endpoint. Semantic memory should use
        # a local embedder (Ollama via memory.embed_url) or run with semantic: false.
        raise NotImplementedError(
            "claude_cli has no embeddings; set memory.semantic=false or memory.embed_url "
            "to a local Ollama embedder."
        )
