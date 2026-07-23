"""Autonomy engine for long-horizon, self-prompting agent behavior."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jarvis_os.core.runtime import Runtime

logger = logging.getLogger(__name__)


REFLECTION_PROMPT = """You are an autonomous agent reviewing a failed step.
Original goal: {goal}
Failed step: {step}
Error: {error}
Recent context: {context}

Suggest a corrected next step as JSON:
{{"reflection": "what went wrong", "retry_step": {{"tool": "skill_name", "args": {{...}}}}}}
If the failure is unrecoverable, set retry_step to null."""


class AutonomyEngine:
    """Runs the agent in autonomous mode with reflection and retry."""

    def __init__(self, runtime: Runtime):
        self.runtime = runtime
        self.config = runtime.config

    async def run_directive(self, directive: str, max_iterations: int = 50) -> dict[str, Any]:
        """Execute a high-level directive autonomously, generating sub-goals as needed."""
        logger.info("Autonomous directive: %s", directive)
        self.runtime.memory.add_message("user", f"[autonomous directive] {directive}")

        iteration = 0
        completed: list[dict[str, Any]] = []
        current_goal = directive

        while iteration < max_iterations:
            iteration += 1
            result = await self.runtime.handle(current_goal)
            completed.append({"goal": current_goal, "result": result})

            # Ask the LLM whether the directive is complete or what the next sub-goal is
            next_goal = await self._decide_next_step(directive, completed)
            if next_goal is None:
                logger.info("Directive complete after %d iterations", iteration)
                break
            current_goal = next_goal

        summary = await self._summarize_directive(directive, completed)
        return {"directive": directive, "iterations": iteration, "summary": summary, "completed": completed}

    async def _decide_next_step(self, directive: str, completed: list[dict[str, Any]]) -> str | None:
        context = json.dumps(
            [{"goal": c["goal"], "summary": c["result"].get("summary", "")} for c in completed[-5:]],
            indent=2,
        )
        prompt = (
            f"Directive: {directive}\n"
            f"Completed steps:\n{context}\n\n"
            "Are we done? If yes, reply exactly 'DONE'. "
            "If not, reply with the next concise sub-goal the agent should pursue."
        )
        response = await self.runtime.llm.chat([{"role": "user", "content": prompt}])
        content = response.get("content", "").strip()
        if content.upper().startswith("DONE"):
            return None
        return content

    async def _summarize_directive(self, directive: str, completed: list[dict[str, Any]]) -> str:
        context = json.dumps(
            [{"goal": c["goal"], "summary": c["result"].get("summary", "")} for c in completed],
            indent=2,
        )
        prompt = (
            f"Original directive: {directive}\n"
            f"Steps completed:\n{context}\n\n"
            "Summarize the overall outcome in one or two sentences."
        )
        messages = [{"role": "user", "content": prompt}]
        persona = getattr(self.runtime, "persona_message", lambda: None)()
        if persona:
            messages.insert(0, persona)
        response = await self.runtime.llm.chat(messages)
        return response.get("content", "Directive finished.")

    async def reflect_and_retry(
        self,
        goal: str,
        step: dict[str, Any],
        error: str,
        context: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Ask the LLM for a corrected step after a failure."""
        prompt = REFLECTION_PROMPT.format(
            goal=goal,
            step=json.dumps(step),
            error=error,
            context=json.dumps(context[-5:], indent=2),
        )
        response = await self.runtime.llm.chat([{"role": "user", "content": prompt}])
        content = response.get("content", "")
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Reflection returned non-JSON: %s", content)
            return None
        return data.get("retry_step")
