"""CodeAct agent: LLM generates Python code blocks that invoke runtime skills."""

import asyncio
import io
import json
import logging
import re
import sys
from contextlib import redirect_stdout, redirect_stderr
from typing import Any

if __name__ == "__main__":  # pragma: no cover
    raise RuntimeError("This module should not be executed directly.")

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Jarvis, a CodeAct agent. Solve the user's goal by writing Python code.

You have two helper functions available in the execution environment:
- run_skill(name, **kwargs): call a runtime skill by name with keyword arguments.
- shell(command): run a shell command and return a dict with stdout, stderr, and returncode.

Available skills:
{skills}

Rules:
1. Respond with one or more Python code blocks wrapped in ```python ... ```.
2. The code will be executed in order. Use print() to show intermediate results.
3. Do NOT use __import__, open, eval, exec, compile, or subprocess directly.
4. When the goal is satisfied, end your response with a plain-text summary starting with "Final Answer:".
5. If you only need a shell command, you may use shell(...).

Begin!"""


class CodeActAgent:
    """Runs the CodeAct loop using a Runtime instance."""

    def __init__(self, runtime: Any):
        self.runtime = runtime

    def _skills_info(self) -> list[dict[str, Any]]:
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "schema": skill.schema,
            }
            for skill in self.runtime.registry.list()
        ]

    async def run(self, goal: str, max_steps: int = 20, on_step=None) -> dict[str, Any]:
        """Execute generated Python code blocks until the goal is answered."""
        logger.info("CodeAct agent starting for goal: %s", goal)

        system_content = SYSTEM_PROMPT.format(skills=json.dumps(self._skills_info(), indent=2))
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": goal},
        ]
        persona = getattr(self.runtime, "persona_message", lambda: None)()
        if persona:
            persona = dict(persona)
            persona["content"] += " Keep your code blocks strictly functional; express the personality in your Final Answer text."
            messages.insert(0, persona)

        steps: list[dict[str, Any]] = []
        observations: list[str] = []
        captured_stdout: list[str] = []

        for step_number in range(1, max_steps + 1):
            if on_step:
                # open-ended loop; report an asymptotic fraction per real step.
                try:
                    on_step(1 - 0.82 ** step_number)
                except Exception:  # noqa: BLE001
                    pass
            response = await self.runtime.llm.chat(messages)
            content = response.get("content", "")

            final_answer = self._extract_final_answer(content)
            code_blocks = self._extract_python_code(content)

            logger.debug(
                "CodeAct step %d blocks=%d final=%s",
                step_number,
                len(code_blocks),
                final_answer is not None,
            )

            step_record: dict[str, Any] = {"step": step_number, "code_blocks": code_blocks}
            if not code_blocks:
                if final_answer is not None:
                    step_record["final_answer"] = final_answer
                    steps.append(step_record)
                    self.runtime.memory.add_message("assistant", final_answer)
                    return {
                        "answer": final_answer,
                        "steps": steps,
                        "observations": observations,
                        "stdout": "\n".join(captured_stdout),
                    }
                error_msg = "No Python code blocks found in model response."
                logger.warning("CodeAct step %d: %s", step_number, error_msg)
                observations.append(error_msg)
                step_record["error"] = error_msg
                steps.append(step_record)
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"Observation: {error_msg}"})
                continue

            stdout, stderr, result = await self._execute_code(code_blocks)
            if stdout:
                captured_stdout.append(stdout)
            observation_parts = []
            if stdout:
                observation_parts.append(f"stdout:\n{stdout}")
            if stderr:
                observation_parts.append(f"stderr:\n{stderr}")
            if result is not None:
                observation_parts.append(f"last expression result: {result}")
            observation = "\n\n".join(observation_parts) or "No output."
            observations.append(observation)
            step_record["observation"] = observation
            steps.append(step_record)

            if final_answer is not None:
                self.runtime.memory.add_message("assistant", final_answer)
                return {
                    "answer": final_answer,
                    "steps": steps,
                    "observations": observations,
                    "stdout": "\n".join(captured_stdout),
                }

            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"Observation:\n{observation}"})

        logger.info("CodeAct agent reached max_steps without final answer")
        return {
            "answer": None,
            "steps": steps,
            "observations": observations,
            "stdout": "\n".join(captured_stdout),
        }

    def _extract_python_code(self, content: str) -> list[str]:
        """Extract Python code blocks from markdown."""
        pattern = re.compile(r"```python\n(.*?)\n```", re.DOTALL)
        return [block.strip() for block in pattern.findall(content)]

    def _extract_final_answer(self, content: str) -> str | None:
        for line in content.splitlines():
            if line.startswith("Final Answer:"):
                return line[len("Final Answer:"):].strip()
        return None

    async def _execute_code(self, code_blocks: list[str]) -> tuple[str, str, Any]:
        """Execute code blocks in a restricted namespace and capture output."""
        namespace = self._build_namespace()
        buffer_stdout = io.StringIO()
        buffer_stderr = io.StringIO()
        last_result: Any = None

        with redirect_stdout(buffer_stdout), redirect_stderr(buffer_stderr):
            for code in code_blocks:
                try:
                    compiled = compile(code, "<codeact>", "exec")
                    exec(compiled, namespace)  # noqa: S102
                except Exception as exc:  # noqa: BLE001
                    logger.exception("CodeAct code execution failed")
                    buffer_stderr.write(f"Exception: {exc}\n")

        stdout = buffer_stdout.getvalue()
        stderr = buffer_stderr.getvalue()

        # Attempt to retrieve the last expression result if `_` convention was used.
        if "_" in namespace and namespace["_"] is not None:
            last_result = namespace["_"]

        return stdout, stderr, last_result

    def _build_namespace(self) -> dict[str, Any]:
        """Build a restricted namespace with safe helpers."""
        namespace: dict[str, Any] = {
            "__builtins__": dict(__builtins__),
        }

        # Block dangerous builtins/functions.
        blocked = {"__import__", "open", "eval", "exec", "compile", "subprocess"}
        for name in blocked:
            namespace[name] = None
            namespace["__builtins__"].pop(name, None)

        namespace["run_skill"] = self._run_skill_helper
        namespace["shell"] = self._shell_helper
        namespace["print"] = print
        return namespace

    def _run_skill_helper(self, name: str, **kwargs: Any) -> Any:
        """Synchronous helper that runs an async skill via the runtime executor."""
        skill = self.runtime.registry.get(name)
        if skill is None:
            raise ValueError(f"Unknown skill: {name}")

        policy_action = {"skill": skill.name, "args": kwargs}
        allowed, reason = self.runtime.policy.check(policy_action)
        if not allowed:
            raise RuntimeError(f"Blocked by policy: {reason}")

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.runtime.executor.run(skill, kwargs))
        finally:
            loop.close()

    def _shell_helper(self, command: str) -> dict[str, Any]:
        """Synchronous shell helper using the shell skill."""
        return self._run_skill_helper("shell", command=command)
