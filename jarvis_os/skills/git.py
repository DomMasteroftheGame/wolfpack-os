"""Git skill for repository operations."""

import asyncio
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import Skill


class GitSkill(Skill):
    """Run common git commands in a repository."""

    name = "git"
    description = "Execute git commands such as status, clone, commit, push, pull, and log."
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "clone", "commit", "push", "pull", "log"],
                "description": "Git action to perform.",
            },
            "repo_dir": {
                "type": "string",
                "description": "Path to the git repository (cwd for most actions).",
            },
            "repo_url": {
                "type": "string",
                "description": "Remote URL for clone.",
            },
            "target_dir": {
                "type": "string",
                "description": "Optional destination directory for clone.",
            },
            "message": {
                "type": "string",
                "description": "Commit message (required for commit).",
            },
            "max_count": {
                "type": "integer",
                "default": 10,
                "description": "Number of log entries to return.",
            },
            "add_all": {
                "type": "boolean",
                "default": False,
                "description": "Stage all changes before committing.",
            },
            "timeout": {
                "type": "integer",
                "default": 60,
                "description": "Timeout in seconds for the git command.",
            },
        },
        "required": ["action"],
    }
    permissions = ["git:execute"]

    async def _run_git(
        self,
        args: list[str],
        cwd: Path | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Run a git subcommand asynchronously."""
        command = ["git", *args]
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "error": "Command timed out",
                "command": " ".join(command),
                "returncode": -1,
            }

        return {
            "command": " ".join(command),
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace").strip(),
            "stderr": stderr.decode("utf-8", errors="replace").strip(),
        }

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        """Execute a git action."""
        action = kwargs["action"]
        repo_dir = kwargs.get("repo_dir")
        cwd = Path(repo_dir).expanduser() if repo_dir else None
        timeout = kwargs.get("timeout", 60)

        if action == "status":
            return await self._run_git(["status", "--porcelain"], cwd=cwd, timeout=timeout)

        if action == "clone":
            repo_url = kwargs.get("repo_url")
            if not repo_url or not isinstance(repo_url, str):
                return {"error": "repo_url is required for clone"}
            args = ["clone", repo_url]
            target_dir = kwargs.get("target_dir")
            if target_dir:
                args.append(target_dir)
            return await self._run_git(args, timeout=timeout)

        if action == "commit":
            message = kwargs.get("message")
            if not message or not isinstance(message, str):
                return {"error": "message is required for commit"}
            if kwargs.get("add_all"):
                add_result = await self._run_git(["add", "-A"], cwd=cwd, timeout=timeout)
                if add_result["returncode"] != 0:
                    return add_result
            return await self._run_git(
                ["commit", "-m", message],
                cwd=cwd,
                timeout=timeout,
            )

        if action == "push":
            return await self._run_git(["push"], cwd=cwd, timeout=timeout)

        if action == "pull":
            return await self._run_git(["pull"], cwd=cwd, timeout=timeout)

        if action == "log":
            max_count = kwargs.get("max_count", 10)
            return await self._run_git(
                ["log", "--oneline", "-n", str(max_count)],
                cwd=cwd,
                timeout=timeout,
            )

        return {"error": f"Unknown action: {action}"}
