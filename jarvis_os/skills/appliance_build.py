"""Appliance build skill stub."""

from typing import Any

from jarvis_os.skills.base import Skill


class ApplianceBuildSkill(Skill):
    name = "appliance_build"
    description = "Build a bootable Jarvis appliance ISO (Linux only, requires root)."
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["build_iso"],
                "description": "Action to perform.",
            }
        },
        "required": ["action"],
    }
    permissions = ["shell:run"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "not_implemented",
            "message": "Appliance build skill is a placeholder. Run appliance/build-iso.sh manually on a Linux box with root.",
        }
