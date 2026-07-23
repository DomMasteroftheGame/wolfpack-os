"""Built-in skills for Linux system interaction."""

import asyncio
import json
import logging
import platform
import shutil
from pathlib import Path
from typing import Any

from jarvis_os.skills.ai_analyst import AIAnalystSkill
from jarvis_os.skills.ai_automation import AIAutomationSkill
from jarvis_os.skills.ai_chatbot import AIChatbotSkill
from jarvis_os.skills.ai_content import AIContentSkill
from jarvis_os.skills.ai_run_business import AIRunBusinessSkill
from jarvis_os.skills.ai_saas import AISaaSSkill
from jarvis_os.skills.base import Skill
from jarvis_os.skills.browser import BrowserSkill
from jarvis_os.skills.credentials import CredentialsSkill
from jarvis_os.skills.business_formation import BusinessFormationSkill
from jarvis_os.skills.business_launch import BusinessLaunchSkill
from jarvis_os.skills.code import CodeSkill
from jarvis_os.skills.deploy import DeploySkill
from jarvis_os.skills.domain import DomainSkill
from jarvis_os.skills.dropship_research import DropshipResearchSkill
from jarvis_os.skills.email_setup import EmailSetupSkill
from jarvis_os.skills.fleet import FleetSkill
from jarvis_os.skills.game_asset import GameAssetSkill
from jarvis_os.skills.game_dev import GameDevSkill
from jarvis_os.skills.game_launch import GameLaunchSkill
from jarvis_os.skills.game_market_research import GameMarketResearchSkill
from jarvis_os.skills.git import GitSkill
from jarvis_os.skills.logo_design import LogoDesignSkill
from jarvis_os.skills.roblox import RobloxSkill
from jarvis_os.skills.roblox_studio import RobloxStudioSkill
from jarvis_os.skills.social_media import SocialMediaSkill
from jarvis_os.skills.stripe import StripeSkill
from jarvis_os.skills.google import GoogleConnectorSkill
from jarvis_os.skills.package import PackageSkill
from jarvis_os.skills.shopify import ShopifySkill

logger = logging.getLogger(__name__)


class ShellSkill(Skill):
    name = "shell"
    description = "Run a shell command and return stdout, stderr, and return code."
    schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run."},
            "timeout": {"type": "integer", "default": 30, "description": "Timeout in seconds."},
        },
        "required": ["command"],
    }
    permissions = ["shell:run"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        command = kwargs["command"]
        timeout = kwargs.get("timeout", 30)
        logger.info("Running shell command: %s", command)
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"error": "Command timed out", "returncode": -1}
        return {
            "stdout": stdout.decode("utf-8", errors="replace").strip(),
            "stderr": stderr.decode("utf-8", errors="replace").strip(),
            "returncode": proc.returncode,
        }


class FileSkill(Skill):
    name = "file"
    description = "Read, write, list, or check existence of files and directories."
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "write", "list", "exists"],
            },
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["action", "path"],
    }
    permissions = ["file:read", "file:write"]

    async def run(self, **kwargs: Any) -> Any:
        action = kwargs["action"]
        path = Path(kwargs["path"]).expanduser()
        if action == "read":
            if not path.exists():
                return {"error": "File not found"}
            return {"content": path.read_text(encoding="utf-8", errors="replace")}
        if action == "write":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(kwargs.get("content", ""), encoding="utf-8")
            return {"status": "written", "path": str(path)}
        if action == "list":
            items = []
            for item in path.iterdir():
                items.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                })
            return {"items": items}
        if action == "exists":
            return {"exists": path.exists(), "type": "dir" if path.is_dir() else "file"}
        return {"error": f"Unknown action: {action}"}


class SystemSkill(Skill):
    name = "system"
    description = "Get system information and manage processes."
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["info", "disk", "processes"],
            },
        },
        "required": ["action"],
    }
    permissions = ["system:info"]

    async def run(self, **kwargs: Any) -> Any:
        action = kwargs["action"]
        if action == "info":
            return {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "python": platform.python_version(),
            }
        if action == "disk":
            df = shutil.disk_usage("/")
            return {
                "total": df.total,
                "used": df.used,
                "free": df.free,
            }
        if action == "processes":
            skill = ShellSkill()
            return await skill.run(command="ps aux --no-headers | head -n 20")
        return {"error": f"Unknown action: {action}"}


from jarvis_os.skills.web_agent import WebAgentSkill
from jarvis_os.skills.share_task import ShareTaskSkill
from jarvis_os.skills.appliance_build import ApplianceBuildSkill
from jarvis_os.skills.usb_build import USBBuildSkill

BUILTIN_SKILLS: list[Skill] = [
    ShellSkill(),
    FileSkill(),
    SystemSkill(),
    BrowserSkill(),
    PackageSkill(),
    GitSkill(),
    CodeSkill(),
    GoogleConnectorSkill(),
    WebAgentSkill(),
    DropshipResearchSkill(),
    ShopifySkill(),
    DomainSkill(),
    GameDevSkill(),
    StripeSkill(),
    BusinessFormationSkill(),
    LogoDesignSkill(),
    EmailSetupSkill(),
    SocialMediaSkill(),
    GameAssetSkill(),
    DeploySkill(),
    GameMarketResearchSkill(),
    RobloxSkill(),
    RobloxStudioSkill(),
    BusinessLaunchSkill(),
    GameLaunchSkill(),
    CredentialsSkill(),
    FleetSkill(),
    AIContentSkill(),
    AISaaSSkill(),
    AIAutomationSkill(),
    AIChatbotSkill(),
    AIAnalystSkill(),
    AIRunBusinessSkill(),
    ShareTaskSkill(),
    ApplianceBuildSkill(),
    USBBuildSkill(),
]
