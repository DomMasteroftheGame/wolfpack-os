"""Simple headless CLI interface."""

import asyncio
import logging

from jarvis_os.core.runtime import Runtime

logger = logging.getLogger(__name__)


class HeadlessCLI:
    def __init__(self, runtime: Runtime, default_agent: str = "simple"):
        self.runtime = runtime
        self.default_agent = default_agent

    async def run(self) -> None:
        print("Jarvis OS ready. Type a goal or 'exit'.")
        print(f"Default agent mode: {self.default_agent}")
        while True:
            try:
                goal = await asyncio.to_thread(input, "jarvis> ")
            except EOFError:
                break
            goal = goal.strip()
            if goal.lower() in {"exit", "quit"}:
                break
            if not goal:
                continue
            result = await self.runtime.run_with_agent(goal, agent_type=self.default_agent)
            print(f"\n{result.get('summary') or result.get('answer', 'Done.')}\n")
            for key in ("results", "steps", "observations"):
                if key in result and result[key]:
                    print(f"{key.upper()}:")
                    for item in result[key]:
                        print(f"- {item}")
            print()
        self.runtime.shutdown()
