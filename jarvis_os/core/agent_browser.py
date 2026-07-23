"""agent-browser wrapper — the pack's browser primitive.

Shells the `agent-browser` CLI (accessibility-tree, semantic @refs) instead of
Playwright/CSS. Iron rules (from the pack skill): CDP-connect to an ALREADY-logged-in
browser (never a fresh automation login), re-snapshot after every change, and close
gracefully (never force-kill the profile — it logs out sessions).

Install once per machine:
    npm i -g agent-browser
    agent-browser install            # Chrome for Testing
Human logs into the target site once in a CDP browser on port 9222, then:
    agent-browser connect 9222
"""
from __future__ import annotations

import asyncio
import shutil
from typing import Any


class AgentBrowser:
    def __init__(self, cli: str = "agent-browser", cdp_port: int = 9222, timeout: float = 90.0):
        self.cli = cli
        self.cdp_port = cdp_port
        self.timeout = timeout

    def available(self) -> bool:
        return shutil.which(self.cli) is not None

    async def _run(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            self.cli, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"agent-browser {' '.join(args)} timed out")
        if proc.returncode != 0:
            raise RuntimeError(f"agent-browser {' '.join(args)} failed: {err.decode('utf-8', 'replace').strip()}")
        return out.decode("utf-8", "replace")

    async def connect(self) -> str:
        """Attach to the already-logged-in CDP session."""
        return await self._run("connect", str(self.cdp_port))

    async def open(self, url: str) -> str:
        return await self._run("open", url)

    async def snapshot(self) -> str:
        """Interactive-only, compact snapshot -> @eN refs (~200-400 tokens)."""
        return await self._run("snapshot", "-i", "-c")

    async def eval_js(self, expression: str) -> str:
        """Run JavaScript in the page and return its stdout (agent-browser `eval`)."""
        return await self._run("eval", expression)

    async def act(self, action: dict) -> Any:
        """Perform a copilot action: {kind: click|type|navigate, target: @ref/url, value}."""
        kind = (action or {}).get("kind")
        target = (action or {}).get("target", "")
        value = (action or {}).get("value", "")
        if kind == "click":
            return await self._run("click", target)
        if kind == "type":
            return await self._run("fill", target, value)
        if kind == "navigate":
            return await self._run("open", target or value)
        return ""

    async def close(self) -> str:
        """Graceful close — NEVER force-kill (that logs out the session)."""
        return await self._run("close")
