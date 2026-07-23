"""AI automation skill.

Designs automation workflows for AI-run businesses. Outputs n8n/Make/Zapier
compatible JSON or Python scripts that connect apps and trigger actions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

DEFAULT_AUTOMATION_DIR = Path(__file__).parent.parent.parent / "ai_businesses" / "automations"

_PLACEHOLDER_PATHS = ["/path/to", "/home/user", "/tmp", "/Users/user"]


def _resolve_output_dir(output_dir: str | None, default: Path) -> Path:
    if not output_dir:
        return default
    lowered = output_dir.lower().replace("\\", "/")
    for placeholder in _PLACEHOLDER_PATHS:
        if placeholder in lowered:
            return default
    return Path(output_dir).expanduser()


class AIAutomationSkill(Skill):
    """Design and generate automation workflows for AI-run businesses."""

    name = "ai_automation"
    description = (
        "Create automation workflows for AI-run businesses: lead capture, order "
        "processing, content publishing, customer follow-up, and data syncing. "
        "Outputs n8n/Make/Zapier JSON or Python scripts."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["design_workflow", "generate_n8n", "generate_python_script"],
                "description": "Automation action.",
            },
            "workflow_name": {
                "type": "string",
                "description": "Name of the workflow.",
            },
            "trigger": {
                "type": "string",
                "description": "What starts the workflow (e.g. 'new Shopify order').",
            },
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of actions the workflow should perform.",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to save workflow files.",
            },
        },
        "required": ["action"],
    }
    permissions = ["file:write"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        if action == "design_workflow":
            return await self._design_workflow(kwargs)
        if action == "generate_n8n":
            return await self._generate_n8n(kwargs)
        if action == "generate_python_script":
            return await self._generate_python_script(kwargs)
        return {"error": f"Unknown action: {action}"}

    async def _design_workflow(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        workflow_name = kwargs.get("workflow_name", "New Workflow")
        trigger = kwargs.get("trigger", "manual")
        steps = kwargs.get("steps", [])

        return {
            "action": "design_workflow",
            "workflow_name": workflow_name,
            "trigger": trigger,
            "steps": steps or [
                "Trigger: receive event",
                "Filter: validate input",
                "Action: process data",
                "Action: send notification",
                "Action: log result",
            ],
            "recommended_tools": ["n8n", "Make (Integromat)", "Zapier", "Activepieces"],
            "estimated_time_saved_per_run": "5-15 minutes",
        }

    async def _generate_n8n(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        workflow_name = kwargs.get("workflow_name", "AI Business Workflow")
        trigger = kwargs.get("trigger", "webhook")
        steps = kwargs.get("steps", [])

        nodes = [
            {
                "id": "trigger",
                "type": "n8n-nodes-base.webhook",
                "position": [250, 300],
                "parameters": {"path": "new-event", "responseMode": "responseNode"},
            },
            {
                "id": "openai",
                "type": "n8n-nodes-base.openAi",
                "position": [450, 300],
                "parameters": {"resource": "chat", "options": {}},
            },
            {
                "id": "slack",
                "type": "n8n-nodes-base.slack",
                "position": [650, 300],
                "parameters": {"channel": "#alerts", "text": "Workflow completed"},
            },
        ]

        workflow = {
            "name": workflow_name,
            "nodes": nodes,
            "connections": {
                "trigger": {"main": [[{"node": "openai", "type": "main", "index": 0}]]},
                "openai": {"main": [[{"node": "slack", "type": "main", "index": 0}]]},
            },
            "settings": {"executionOrder": "v1"},
        }

        output_dir = _resolve_output_dir(kwargs.get("output_dir"), DEFAULT_AUTOMATION_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = output_dir / f"{workflow_name.lower().replace(' ', '_')}.json"
        filename.write_text(json.dumps(workflow, indent=2), encoding="utf-8")

        return {
            "action": "generate_n8n",
            "file": str(filename),
            "workflow": workflow,
            "next_step": "Import the JSON into n8n and configure credentials.",
        }

    async def _generate_python_script(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        workflow_name = kwargs.get("workflow_name", "ai_workflow")
        trigger = kwargs.get("trigger", "every 15 minutes")
        steps = kwargs.get("steps", [])

        output_dir = _resolve_output_dir(kwargs.get("output_dir"), DEFAULT_AUTOMATION_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = output_dir / f"{workflow_name.lower().replace(' ', '_')}.py"

        script = f"""\"\"\"{workflow_name}

Trigger: {trigger}
Steps: {steps or ['monitor', 'process', 'act']}

Run with a scheduler (cron/systemd/Task Scheduler) or as a background service.
\"\"\"

import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_trigger() -> bool:
    \"\"\"Return True when the workflow should run.\"\"\"
    # TODO: implement trigger check
    return True


def process() -> dict:
    \"\"\"Main workflow logic.\"\"\"
    # TODO: implement steps
    return {{"status": "ok"}}


def notify(result: dict) -> None:
    \"\"\"Send notification about the result.\"\"\"
    logger.info("Workflow result: %s", result)


def main() -> None:
    while True:
        if check_trigger():
            result = process()
            notify(result)
        time.sleep(60)


if __name__ == "__main__":
    main()
"""
        filename.write_text(script, encoding="utf-8")

        return {
            "action": "generate_python_script",
            "file": str(filename),
            "next_step": "Fill in the TODOs and run the script on a scheduler.",
        }
