"""Code skill for reading, writing, searching, and listing source files."""

import asyncio
import shutil
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import Skill


class CodeSkill(Skill):
    """Read, write, search, and list code files."""

    name = "code"
    description = "Read files, write files, search file contents, and list directory trees."
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "write", "search", "list_tree"],
                "description": "Code action to perform.",
            },
            "path": {
                "type": "string",
                "description": "File or directory path.",
            },
            "content": {
                "type": "string",
                "description": "Content to write when action is 'write'.",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to return (1-based, inclusive).",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to return (1-based, inclusive).",
            },
            "query": {
                "type": "string",
                "description": "Search string when action is 'search'.",
            },
            "case_sensitive": {
                "type": "boolean",
                "default": True,
                "description": "Whether search is case-sensitive.",
            },
            "max_depth": {
                "type": "integer",
                "default": 3,
                "description": "Maximum recursion depth for list_tree.",
            },
        },
        "required": ["action"],
    }
    permissions = ["code:read", "code:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        """Execute a code action."""
        action = kwargs["action"]
        if action == "read":
            return await self._read(kwargs)
        if action == "write":
            return await self._write(kwargs)
        if action == "search":
            return await self._search(kwargs)
        if action == "list_tree":
            return await self._list_tree(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _read(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(kwargs.get("path"))
        if not path.is_file():
            return {"error": f"File not found: {path}"}

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

        lines = content.splitlines()
        start_line = kwargs.get("start_line")
        end_line = kwargs.get("end_line")

        if start_line is not None or end_line is not None:
            start = (start_line or 1) - 1
            end = end_line if end_line is not None else len(lines)
            start = max(0, start)
            end = min(len(lines), end)
            selected = lines[start:end]
            return {
                "path": str(path),
                "start_line": start + 1,
                "end_line": end,
                "content": "\n".join(selected),
            }

        return {"path": str(path), "content": content}

    async def _write(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(kwargs.get("path"))
        content = kwargs.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {"status": "written", "path": str(path)}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    async def _search(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        query = kwargs.get("query")
        if not query or not isinstance(query, str):
            return {"error": "query is required for search and must be a non-empty string"}

        path = self._resolve_path(kwargs.get("path", "."))
        case_sensitive = kwargs.get("case_sensitive", True)

        if shutil.which("rg"):
            return await self._search_ripgrep(path, query, case_sensitive)
        return self._search_python(path, query, case_sensitive)

    async def _search_ripgrep(
        self,
        path: Path,
        query: str,
        case_sensitive: bool,
    ) -> dict[str, Any]:
        args = ["rg", "--line-number", "--no-heading"]
        if not case_sensitive:
            args.append("--ignore-case")
        args.extend(["--", query, str(path)])

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return {"error": "ripgrep search timed out"}

        matches = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            # Format: file:line:content
            first_colon = line.find(":")
            if first_colon == -1:
                continue
            file_part = line[:first_colon]
            rest = line[first_colon + 1 :]
            second_colon = rest.find(":")
            if second_colon == -1:
                continue
            try:
                line_no = int(rest[:second_colon])
            except ValueError:
                continue
            content = rest[second_colon + 1 :]
            matches.append(
                {
                    "file": file_part,
                    "line": line_no,
                    "content": content,
                }
            )

        return {"matches": matches, "tool": "ripgrep"}

    def _search_python(
        self,
        path: Path,
        query: str,
        case_sensitive: bool,
    ) -> dict[str, Any]:
        search_term = query if case_sensitive else query.lower()
        matches = []
        try:
            files = list(path.rglob("*"))
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

        for file_path in files:
            if not file_path.is_file():
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue

            compare_text = text if case_sensitive else text.lower()
            if search_term not in compare_text:
                continue

            for line_no, line in enumerate(text.splitlines(), start=1):
                compare_line = line if case_sensitive else line.lower()
                if search_term in compare_line:
                    matches.append(
                        {
                            "file": str(file_path),
                            "line": line_no,
                            "content": line,
                        }
                    )
            if len(matches) >= 100:
                break

        return {"matches": matches, "tool": "python"}

    async def _list_tree(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(kwargs.get("path", "."))
        max_depth = kwargs.get("max_depth", 3)
        entries = []

        def walk(current: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except Exception:  # noqa: BLE001
                return
            for child in children:
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "type": "dir" if child.is_dir() else "file",
                        "depth": depth,
                    }
                )
                if child.is_dir():
                    walk(child, depth + 1)

        walk(path, 1)
        return {"path": str(path), "max_depth": max_depth, "entries": entries}

    def _resolve_path(self, path: Any) -> Path:
        """Resolve a path string into a Path object, expanding '~'."""
        return Path(path).expanduser() if path else Path(".")
