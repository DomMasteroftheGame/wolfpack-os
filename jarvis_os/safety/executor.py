"""Safe skill executor."""

from jarvis_os.safety.policy import PolicyEngine
from jarvis_os.skills.base import Skill


class SafeExecutor:
    def __init__(self, policy: PolicyEngine):
        self.policy = policy

    async def run(self, skill: Skill, args: dict) -> dict:
        action = {"skill": skill.name, "args": args}
        allowed, reason = self.policy.check(action)
        if not allowed:
            return {"error": f"Policy denied: {reason}"}
        return await skill.run(**args)
