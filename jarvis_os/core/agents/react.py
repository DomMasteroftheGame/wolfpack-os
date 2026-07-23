"""ReAct agent: Thought -> Action -> Observation loop."""

import json
import logging
import re
from typing import Any

if __name__ == "__main__":  # pragma: no cover
    raise RuntimeError("This module should not be executed directly.")

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Jarvis, a ReAct agent. Solve the user's goal by thinking step-by-step and using tools.

Available tools:
{tools}

Rules:
1. Start by reasoning about the goal. Output exactly one line starting with "Thought: ".
2. Then either use a tool or provide the final answer.
3. To use a tool, output exactly one line starting with "Action: " followed by the tool name and a JSON object of arguments, e.g.:
   Action: shell {"command": "ls -la"}
4. You will receive an "Observation:" with the tool result. Continue with another "Thought:" and "Action:" if needed.
5. When the goal is fully satisfied, output exactly one line starting with "Final Answer:" followed by your answer.
6. Do not output any text outside Thought, Action, Observation, or Final Answer lines.

Begin!"""


class ReActAgent:
    """Runs the ReAct reasoning loop using a Runtime instance."""

    def __init__(self, runtime: Any):
        self.runtime = runtime

    def _tools_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": skill.name,
                    "description": skill.description,
                    "parameters": skill.schema,
                },
            }
            for skill in self.runtime.registry.list()
        ]

    async def run(self, goal: str, max_steps: int = 20, on_step=None) -> dict[str, Any]:
        """Execute the ReAct loop until the goal is answered or max_steps is reached."""
        logger.info("ReAct agent starting for goal: %s", goal)

        # .replace, not .format: the prompt contains literal JSON braces.
        system_content = SYSTEM_PROMPT.replace("{tools}", json.dumps(self._tools_schema(), indent=2))
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": goal},
        ]
        persona = getattr(self.runtime, "persona_message", lambda: None)()
        if persona:
            persona = dict(persona)
            persona["content"] += " Keep the Thought/Action/Final Answer format exactly; express the personality in your Final Answer."
            messages.insert(0, persona)

        steps: list[dict[str, Any]] = []
        observations: list[str] = []

        for step_number in range(1, max_steps + 1):
            if on_step:
                # step count is open-ended (ends on Final Answer), so report an
                # asymptotic fraction: each real step closes ~18% of the gap.
                try:
                    on_step(1 - 0.82 ** step_number)
                except Exception:  # noqa: BLE001
                    pass
            response = await self.runtime.llm.chat(messages)
            content = response.get("content", "")

            thought = self._extract_thought(content)
            action = self._extract_action(content)
            final_answer = self._extract_final_answer(content)

            logger.debug("ReAct step %d thought=%s action=%s final=%s", step_number, thought, action, final_answer)

            if final_answer is not None:
                steps.append({"step": step_number, "thought": thought, "final_answer": final_answer})
                self.runtime.memory.add_message("assistant", final_answer)
                return {
                    "answer": final_answer,
                    "steps": steps,
                    "observations": observations,
                }

            if action is None:
                error_msg = "No valid Action: or Final Answer: found in model response."
                logger.warning("ReAct step %d: %s", step_number, error_msg)
                observations.append(error_msg)
                steps.append({"step": step_number, "thought": thought, "error": error_msg, "raw": content})
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"Observation: {error_msg}"})
                continue

            observation = await self._execute_action(action)
            observations.append(observation)
            steps.append({"step": step_number, "thought": thought, "action": action, "observation": observation})

            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"Observation: {observation}"})

        logger.info("ReAct agent reached max_steps without final answer")
        return {
            "answer": None,
            "steps": steps,
            "observations": observations,
        }

    def _extract_thought(self, content: str) -> str | None:
        match = re.search(r"^Thought:\s*(.+)$", content, re.MULTILINE)
        return match.group(1).strip() if match else None

    def _extract_action(self, content: str) -> dict[str, Any] | None:
        match = re.search(r"^Action:\s*(\S+)\s+(.+)$", content, re.MULTILINE)
        if not match:
            return None
        skill_name = match.group(1).strip()
        args_text = match.group(2).strip()
        try:
            args = json.loads(args_text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse action arguments: %s", args_text)
            return None
        return {"skill": skill_name, "args": args}

    def _extract_final_answer(self, content: str) -> str | None:
        for line in content.splitlines():
            if line.startswith("Final Answer:"):
                return line[len("Final Answer:"):].strip()
        return None

    async def _execute_action(self, action: dict[str, Any]) -> str:
        skill_name = action["skill"]
        args = action.get("args", {})
        skill = self.runtime.registry.get(skill_name)
        if skill is None:
            return f"Error: unknown skill '{skill_name}'"

        policy_action = {"skill": skill.name, "args": args}
        allowed, reason = self.runtime.policy.check(policy_action)
        if not allowed:
            return f"Error: blocked by policy: {reason}"

        try:
            result = await self.runtime.executor.run(skill, args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ReAct skill execution failed")
            return f"Error: {exc}"

        return json.dumps(result, default=str, ensure_ascii=False)
