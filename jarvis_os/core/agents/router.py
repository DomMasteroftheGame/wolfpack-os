"""Agent router selects and dispatches to the appropriate agent mode."""

import logging
from typing import Any

from jarvis_os.core.agents.codeact import CodeActAgent
from jarvis_os.core.agents.react import ReActAgent

if __name__ == "__main__":  # pragma: no cover
    raise RuntimeError("This module should not be executed directly.")

logger = logging.getLogger(__name__)

ROUTER_PROMPT = """You are Jarvis, an agent router. Given a user goal, pick the best execution mode.

Available modes:
- simple: direct plan-and-execute using available tools (default, good for straightforward tasks).
- react: step-by-step reasoning with explicit Thought/Action/Observation loops (good for multi-step reasoning).
- codeact: generate and execute Python code that calls tools (good for data processing, automation, or tasks needing code).
- autonomous: high-level self-directed loop that generates sub-goals (good for open-ended or long-horizon directives).

Reply with exactly one word from the list above. Do not explain."""


class AgentRouter:
    """Routes a goal to the selected agent mode."""

    def __init__(self, runtime: Any):
        self.runtime = runtime

    async def run(self, goal: str, agent_type: str | None = None, on_step=None) -> dict[str, Any]:
        """Route the goal to the appropriate agent and return its result."""
        if agent_type is None:
            agent_type = await self._select_agent(goal)
            logger.info("Router selected agent: %s", agent_type)

        agent_type = agent_type.lower().strip()
        if agent_type == "simple":
            return await self.runtime.handle(goal, on_step=on_step)
        if agent_type == "react":
            return await ReActAgent(self.runtime).run(goal, on_step=on_step)
        if agent_type == "codeact":
            return await CodeActAgent(self.runtime).run(goal, on_step=on_step)
        if agent_type == "autonomous":
            return await self.runtime.run_directive(goal)

        raise ValueError(f"Unknown agent type: {agent_type}")

    async def _select_agent(self, goal: str) -> str:
        messages = [
            {"role": "system", "content": ROUTER_PROMPT},
            {"role": "user", "content": f"Goal: {goal}\nMode:"},
        ]
        response = await self.runtime.llm.chat(messages)
        content = response.get("content", "").strip().lower()

        valid = {"simple", "react", "codeact", "autonomous"}
        for choice in valid:
            if choice in content:
                return choice

        logger.warning("Router could not parse response '%s', defaulting to simple", content)
        return "simple"
