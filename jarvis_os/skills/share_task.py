"""share_task skill — hand a job to another fleet node through the shared drive.

Firewall-proof delegation: instead of an HTTP call (which node firewalls block),
this drops a task file into the target node's inbox on the NAS share. That node's
share-bus picks it up, runs it, and writes the result back to the share.

    action=submit  target=<NodeName> goal=<task>   -> queue a job for that node
    action=result  task_id=<id>                     -> read the result (or 'pending')
    action=nodes                                    -> list nodes that can receive jobs
"""

from __future__ import annotations

from typing import Any

from jarvis_os.skills.base import Skill


class ShareTaskSkill(Skill):
    name = "share_task"
    description = (
        "Delegate a task to another Jarvis fleet node through the shared drive "
        "(works even when firewalls block direct HTTP). Submit a job to a node, "
        "check its result, or list which nodes can receive jobs."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["submit", "result", "nodes"], "default": "submit"},
            "target": {"type": "string", "description": "Target node name (e.g. Maui, Omen)."},
            "goal": {"type": "string", "description": "The task to run on the target node."},
            "agent": {"type": "string", "default": "simple"},
            "task_id": {"type": "string", "description": "Task id returned by submit (for action=result)."},
        },
    }
    permissions = ["fleet:delegate"]

    def __init__(self) -> None:
        # Wired by Runtime._configure_skills: () -> {path, node_name, ...}
        self.settings = None

    def _bus(self):
        from jarvis_os.core.share_bus import ShareBus
        return ShareBus(None, self.settings)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        if self.settings is None or not (self.settings() or {}).get("path"):
            return {"error": "Share not configured on this node (set share.path)."}
        action = kwargs.get("action", "submit")
        bus = self._bus()
        if action == "submit":
            target = kwargs.get("target")
            goal = kwargs.get("goal")
            if not target or not goal:
                return {"error": "submit needs 'target' and 'goal'."}
            return bus.submit(target, goal, kwargs.get("agent", "simple"))
        if action == "result":
            tid = kwargs.get("task_id")
            if not tid:
                return {"error": "result needs 'task_id'."}
            r = bus.result(tid)
            return r if r is not None else {"status": "pending", "task_id": tid}
        if action == "nodes":
            return {"nodes": bus.nodes()}
        return {"error": f"unknown action: {action}"}
