"""Planner turns goals into step-by-step tool use via an LLM."""

import json
import logging
from typing import Any

from jarvis_os.config import Config
from jarvis_os.llm.base import LLMProvider
from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are Jarvis, an autonomous Linux system assistant.
You have access to tools. When given a goal, plan the smallest set of safe steps needed.
Always prefer reading before writing. Never guess file contents.
Respond with a JSON object:
{
  "thoughts": "brief reasoning",
  "steps": [
    {"tool": "skill_name", "args": {"key": "value"}}
  ]
}
If no tool is needed, set steps to []."""


class Plan:
    def __init__(self, thoughts: str, steps: list[dict[str, Any]]):
        self.thoughts = thoughts
        self.steps = steps


class Planner:
    def __init__(self, config: Config, llm: LLMProvider, skills: list[Skill]):
        self.config = config
        self.llm = llm
        self.skills = skills

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
            for skill in self.skills
        ]

    async def plan(self, goal: str, context: list[dict[str, Any]]) -> Plan:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": f"Available tools: {json.dumps(self._tools_schema())}"},
            *context,
            {"role": "user", "content": goal},
        ]
        response = await self.llm.chat(messages)
        content = response.get("content", "")
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Planner returned non-JSON: %s", content)
            data = {"thoughts": content, "steps": []}
        return Plan(thoughts=data.get("thoughts", ""), steps=data.get("steps", []))
