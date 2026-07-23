"""Package manager skill for Linux systems."""

import asyncio
import shutil
from typing import Any

from jarvis_os.skills.base import Skill


class PackageSkill(Skill):
    """Install, update, upgrade, and list packages using the system package manager."""

    name = "package"
    description = (
        "Manage system packages using apt, dnf, pacman, or brew."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["install", "update", "upgrade", "list_installed"],
                "description": "Package action to perform.",
            },
            "packages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Package names for install or upgrade.",
            },
            "timeout": {
                "type": "integer",
                "default": 120,
                "description": "Timeout in seconds for the package command.",
            },
        },
        "required": ["action"],
    }
    permissions = ["package:manage"]

    # Ordered by preference.
    MANAGERS = ["apt", "dnf", "pacman", "brew"]

    def _detect_manager(self) -> str | None:
        """Return the first available supported package manager."""
        for manager in self.MANAGERS:
            if shutil.which(manager):
                return manager
        return None

    def _build_command(self, manager: str, action: str, packages: list[str]) -> list[str]:
        """Build the package manager command as a list of arguments."""
        if manager == "apt":
            if action == "install":
                return ["apt-get", "install", "-y", *packages]
            if action == "update":
                return ["apt-get", "update"]
            if action == "upgrade":
                return ["apt-get", "upgrade", "-y", *packages]
            if action == "list_installed":
                return ["dpkg", "-l"]
        elif manager == "dnf":
            if action == "install":
                return ["dnf", "install", "-y", *packages]
            if action == "update":
                return ["dnf", "check-update"]
            if action == "upgrade":
                return ["dnf", "upgrade", "-y", *packages]
            if action == "list_installed":
                return ["dnf", "list", "installed"]
        elif manager == "pacman":
            if action == "install":
                return ["pacman", "-S", "--noconfirm", *packages]
            if action == "update":
                return ["pacman", "-Sy"]
            if action == "upgrade":
                return ["pacman", "-Su", "--noconfirm", *packages]
            if action == "list_installed":
                return ["pacman", "-Q"]
        elif manager == "brew":
            if action == "install":
                return ["brew", "install", *packages]
            if action == "update":
                return ["brew", "update"]
            if action == "upgrade":
                return ["brew", "upgrade", *packages]
            if action == "list_installed":
                return ["brew", "list"]
        raise ValueError(f"Unsupported action '{action}' for manager '{manager}'")

    def _validate_packages(self, packages: Any) -> list[str]:
        """Validate that package names are non-empty strings."""
        if isinstance(packages, str):
            packages = [packages]
        if not isinstance(packages, list) or not packages:
            raise ValueError("packages must be a non-empty string or list of strings")
        cleaned: list[str] = []
        for pkg in packages:
            if not isinstance(pkg, str) or not pkg.strip():
                raise ValueError("package names must be non-empty strings")
            cleaned.append(pkg.strip())
        return cleaned

    async def _run_command(
        self,
        command: list[str],
        timeout: int,
    ) -> dict[str, Any]:
        """Run a command asynchronously and return the result."""
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
        """Execute a package manager action."""
        action = kwargs["action"]
        manager = self._detect_manager()
        if manager is None:
            return {"error": "No supported package manager found (apt, dnf, pacman, brew)."}

        packages: list[str] = []
        if action == "install":
            try:
                packages = self._validate_packages(kwargs.get("packages", []))
            except ValueError as exc:
                return {"error": str(exc)}
        elif action == "upgrade":
            provided = kwargs.get("packages", [])
            if provided:
                try:
                    packages = self._validate_packages(provided)
                except ValueError as exc:
                    return {"error": str(exc)}

        try:
            command = self._build_command(manager, action, packages)
        except ValueError as exc:
            return {"error": str(exc)}

        timeout = kwargs.get("timeout", 120)
        result = await self._run_command(command, timeout)
        result["manager"] = manager
        result["action"] = action
        return result
