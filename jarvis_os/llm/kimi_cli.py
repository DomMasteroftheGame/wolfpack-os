"""Kimi Code CLI provider — the user's own Kimi Code subscription, no API key.

Mirrors claude_cli: shells out to the local `kimi` CLI in non-interactive
prompt mode (`kimi -p`) instead of hitting a metered API. The CLI carries its
own auth from the user's Kimi Code login.

Config:
  llm:
    provider: kimi_cli
    model: null                  # the kimi CLI uses its own configured model
    base_url: /path/to/kimi      # optional CLI path override (default: `kimi`)
Env override: KIMI_CLI_PATH.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Any

from jarvis_os.config import LLMConfig
from jarvis_os.llm.base import LLMProvider
from jarvis_os.llm.claude_cli import ClaudeCLIProvider

logger = logging.getLogger(__name__)


class KimiCLIProvider(LLMProvider):
    """Drives `kimi -p` (Kimi Code subscription) as a chat backend."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.cli_path = os.environ.get("KIMI_CLI_PATH") or config.base_url or "kimi"

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        if not shutil.which(self.cli_path) and not os.path.isfile(self.cli_path):
            raise RuntimeError(
                f"Kimi CLI not found at '{self.cli_path}'. Install Kimi Code and sign in, "
                f"or set llm.base_url / KIMI_CLI_PATH."
            )

        system, prompt = ClaudeCLIProvider._split(messages)
        full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt
        cmd = [self.cli_path, "-p", full_prompt]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"kimi -p failed (exit {proc.returncode}): {stderr.decode('utf-8', 'replace').strip()}"
            )
        return {"content": stdout.decode("utf-8", "replace").strip()}

    async def embed(self, text: str) -> list[float]:
        # The CLI has no embeddings endpoint. Use a local embedder (Ollama) or
        # run with memory.semantic: false.
        raise NotImplementedError(
            "kimi_cli has no embeddings; set memory.semantic=false or memory.embed_url "
            "to a local Ollama embedder."
        )
