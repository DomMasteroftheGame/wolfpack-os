"""Policy engine decides whether an action is allowed."""

import fnmatch
import logging
from pathlib import Path

from jarvis_os.config import SafetyConfig

logger = logging.getLogger(__name__)


class PolicyEngine:
    """Check actions against a deny-by-default safety policy."""

    def __init__(self, config: SafetyConfig):
        self.config = config
        self.allowed_paths = [Path(p).expanduser() for p in config.allowed_paths]
        if config.permissive:
            logger.warning("SAFETY: permissive mode is enabled. All policy checks are bypassed.")

    def check(self, action: dict) -> tuple[bool, str]:
        if self.config.permissive:
            return True, "permissive mode: policy bypassed"
        skill = action.get("skill")
        args = action.get("args", {})

        if skill == "shell":
            command = args.get("command", "")
            return self._check_shell(command)

        if skill == "file":
            path = Path(args.get("path", "")).expanduser()
            action_type = args.get("action", "")
            return self._check_file(path, action_type)

        if skill == "system":
            return True, "system info allowed"

        # Non-guarded skills (browser, git, deploy, shopify, google, business_*, …):
        # allowed when listed in allowed_skills ("*" = any registered skill). This
        # keeps deny-by-default meaningful while letting the pack actually operate.
        allowed_skills = getattr(self.config, "allowed_skills", ["*"])
        if "*" in allowed_skills or skill in allowed_skills:
            return True, f"skill '{skill}' allowed by policy allowlist"

        return False, f"Skill '{skill}' is not in the policy allowlist"

    def _check_shell(self, command: str) -> tuple[bool, str]:
        lowered = command.lower()
        if not self.config.allow_sudo and ("sudo" in lowered or "su -" in lowered):
            return False, "sudo/root commands are disabled by policy"
        for blocked in self.config.blocked_commands:
            if blocked.lower() in lowered:
                return False, f"Blocked command pattern: {blocked}"
        if not self.config.allow_network:
            network_tools = ["curl", "wget", "nc", "netcat", "ssh", "scp", "ftp"]
            if any(tool in lowered.split() for tool in network_tools):
                return False, "Network commands are disabled by policy"
        return True, "shell command allowed"

    def _check_file(self, path: Path, action: str) -> tuple[bool, str]:
        resolved = path.resolve()
        if action == "write":
            if resolved.is_dir():
                return False, "Cannot write to a directory path"
            parent = resolved.parent
        else:
            parent = resolved if resolved.is_dir() else resolved.parent

        for allowed in self.allowed_paths:
            try:
                parent.relative_to(allowed.resolve())
                return True, f"path allowed under {allowed}"
            except ValueError:
                continue
        return False, f"Path '{path}' is outside allowed directories"
