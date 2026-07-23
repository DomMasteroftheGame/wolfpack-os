"""Main agent runtime."""

import logging
from pathlib import Path
from typing import Any

from jarvis_os.config import Config
from jarvis_os.core.agents.router import AgentRouter
from jarvis_os.core.autonomy import AutonomyEngine
from jarvis_os.core.cluster_worker import ClusterWorker
from jarvis_os.core.inbox_bus import Inbox
from jarvis_os.core.jobqueue import JobQueue
from jarvis_os.core.memory import Memory
from jarvis_os.core.mesh_registry import MeshRegistry
from jarvis_os.core.planner import Planner
from jarvis_os.core.scheduler import Scheduler, ScheduledTask
from jarvis_os.core.share_bus import ShareBus
from jarvis_os.core.shared_memory import MemoryRouter
from jarvis_os.core.user_profile import business_summary, load_user_profile
from jarvis_os.llm.providers import get_provider
from jarvis_os.safety.audit import AuditLog
from jarvis_os.safety.executor import SafeExecutor
from jarvis_os.safety.policy import PolicyEngine
from jarvis_os.skills.builtin import BUILTIN_SKILLS
from jarvis_os.skills.external import ExternalSkillRegistry
from jarvis_os.skills.google import GoogleConnectorSkill
from jarvis_os.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class Runtime:
    """The central agent loop."""

    def __init__(self, config: Config):
        self.config = config
        self.memory = MemoryRouter(Memory(config.memory_db), self._memory_settings)
        self.audit = AuditLog(config.safety.audit_file)
        self.policy = PolicyEngine(config.safety)
        self.executor = SafeExecutor(self.policy)
        self.registry = SkillRegistry()
        for skill in BUILTIN_SKILLS:
            self.registry.register(skill)
        self._configure_skills()
        self.llm = get_provider(config.llm)
        self._wire_web_agent()
        self.planner = Planner(config, self.llm, self.registry.list())
        self.scheduler = Scheduler()
        self.scheduler.on_trigger(self._on_scheduled_goal)
        self.autonomy = AutonomyEngine(self)
        self.router = AgentRouter(self)
        # Lazily loaded operator business summary (first-run wizard profile);
        # None = not loaded yet, "" = no profile on disk. See persona_message().
        self._profile_summary: str | None = None

        # Hub coordination services (always constructed; enabled by config.hub.enabled).
        self.inbox = Inbox(config.inbox.path)
        self.jobqueue = JobQueue()
        self.worker = ClusterWorker(self, self.jobqueue, self._cluster_settings)
        self.sharebus = ShareBus(self, self._share_settings)
        self.mesh: MeshRegistry | None = None
        if config.mesh.enabled or config.hub.enabled:
            self.mesh = MeshRegistry(
                hub_id=config.mesh.hub_id,
                token=config.mesh.token,
                role=config.mesh.role,
                peers=[p.model_dump() for p in config.mesh.peers],
                agent_blacklist=config.mesh.agent_blacklist,
                health_path=config.mesh.health_path,
                timeout=5.0,
            )

        logger.info("Runtime initialized with provider=%s", config.llm.provider)

    def _memory_settings(self) -> dict[str, Any]:
        """Live memory config for the MemoryRouter (reads current config each call)."""
        m = self.config.memory
        return {
            "mode": m.mode,
            "hub_url": m.hub_url,
            "embed_url": m.embed_url or self.config.llm.base_url,
            "embed_model": m.embed_model,
            "semantic": m.semantic,
        }

    async def handle(self, goal: str, on_step=None) -> dict[str, Any]:
        """Handle a single user goal end-to-end."""
        self.memory.add_message("user", goal)
        self.audit.record("goal_received", {"goal": goal})

        context = self._build_context(goal)
        plan = await self.planner.plan(goal, context)
        logger.info("Plan: %s", plan.thoughts)
        self.audit.record("plan_created", {"thoughts": plan.thoughts, "steps": plan.steps})

        results: list[dict[str, Any]] = []
        step_no = 0
        for step in plan.steps:
            step_no += 1
            if on_step:
                # fraction of the plan completed so far (capped below 1 until we summarize)
                try:
                    on_step(min(0.92, (step_no - 1) / max(1, len(plan.steps))))
                except Exception:  # noqa: BLE001
                    pass
            skill_name = step.get("tool")
            args = step.get("args", {})
            skill = self.registry.get(skill_name)
            if skill is None:
                err = f"Unknown skill: {skill_name}"
                logger.error(err)
                results.append({"skill": skill_name, "error": err})
                break

            action = {"skill": skill.name, "args": args}
            allowed, reason = self.policy.check(action)
            self.audit.record("policy_check", {"action": action, "allowed": allowed, "reason": reason})
            if not allowed:
                results.append({"skill": skill.name, "error": f"Blocked by policy: {reason}"})
                if self.config.autonomy.reflection_enabled:
                    retry_step = await self.autonomy.reflect_and_retry(goal, step, reason, context)
                    if retry_step:
                        plan.steps.insert(0, retry_step)
                break

            try:
                result = await self.executor.run(skill, args)
                results.append({"skill": skill.name, "result": result})
                self.audit.record("skill_executed", {"action": action, "result": result})
            except Exception as exc:  # noqa: BLE001
                logger.exception("Skill execution failed")
                error_msg = str(exc)
                results.append({"skill": skill.name, "error": error_msg})
                self.audit.record("skill_failed", {"action": action, "error": error_msg})
                if self.config.autonomy.reflection_enabled:
                    retry_step = await self.autonomy.reflect_and_retry(goal, step, error_msg, context)
                    if retry_step:
                        plan.steps.insert(0, retry_step)
                break

            context = self._build_context(goal)

        summary = await self._summarize(goal, results)
        self.memory.add_message("assistant", summary)
        return {"summary": summary, "results": results, "plan": plan.thoughts}

    async def run_directive(self, directive: str) -> dict[str, Any]:
        """Run a high-level directive autonomously."""
        return await self.autonomy.run_directive(
            directive, max_iterations=self.config.autonomy.max_iterations
        )

    async def run_with_agent(self, goal: str, agent_type: str | None = None, on_step=None) -> dict[str, Any]:
        """Route a goal through the selected agent mode.

        on_step(frac: float) is an optional progress callback (0..1) used to
        drive the live console hunt animation; agents that support it report
        their fractional progress as they advance.
        """
        return await self.router.run(goal, agent_type=agent_type, on_step=on_step)

    def apply_config(self, config: Config) -> None:
        """Hot-apply a new config: rebuild the LLM provider, policy, executor, and planner.

        memory_db changes still require a restart.
        """
        llm = get_provider(config.llm)  # validate before swapping anything
        self.config = config
        self.audit = AuditLog(config.safety.audit_file)
        self.policy = PolicyEngine(config.safety)
        self.executor = SafeExecutor(self.policy)
        self.llm = llm
        self._wire_web_agent()
        self.planner = Planner(config, self.llm, self.registry.list())
        logger.info(
            "Runtime config reloaded: provider=%s model=%s permissive=%s",
            config.llm.provider, config.llm.model, config.safety.permissive,
        )

    def schedule(self, task: ScheduledTask) -> None:
        """Add a recurring or one-shot task."""
        self.scheduler.add(task)

    async def start_scheduler(self) -> None:
        if self.config.scheduler.enabled:
            # Register the recurring pack automations from config (auto-mailer,
            # event radar, auto-register, health, standup, …).
            for t in self.config.scheduler.tasks:
                if t.enabled:
                    self.scheduler.add(ScheduledTask(
                        id=t.id, goal=t.goal, interval_seconds=t.interval_seconds,
                    ))
            await self.scheduler.start()

    async def stop_scheduler(self) -> None:
        await self.scheduler.stop()

    async def _on_scheduled_goal(self, goal: str) -> None:
        logger.info("Running scheduled goal: %s", goal)
        await self.handle(goal)

    # ── Hub services ──────────────────────────────────────────────────────────
    def _cluster_settings(self) -> dict[str, Any]:
        c = self.config.cluster
        return {
            "worker_enabled": c.worker_enabled,
            "queue_url": c.queue_url,
            "max_concurrent": c.max_concurrent,
            "poll_interval": c.poll_interval,
        }

    def _share_settings(self) -> dict[str, Any]:
        s = self.config.share
        return {
            "enabled": s.enabled,
            "path": s.path,
            "node_name": self.config.personality.name,
            "poll_interval": s.poll_interval,
        }

    async def start_hub_services(self) -> None:
        """Start hub coordination loops: mesh, worker, share-bus."""
        if not self.config.hub.enabled:
            return
        logger.info("Starting hub services (hub=%s)", self.config.mesh.hub_id)
        if self.mesh is not None:
            await self.mesh.start_refresh(self.config.mesh.poll_interval)
        await self.worker.start()
        await self.sharebus.start()
        if self.mesh is not None:
            leader = self.mesh.leader()
            logger.info("Mesh leader: %s (this node is %s)", leader,
                        "leader" if self.mesh.is_leader() else "not leader")

    async def stop_hub_services(self) -> None:
        """Stop hub coordination loops."""
        if not self.config.hub.enabled:
            return
        logger.info("Stopping hub services")
        if self.mesh is not None:
            await self.mesh.stop_refresh()
        await self.worker.stop()
        await self.sharebus.stop()

    def _wire_web_agent(self) -> None:
        """Give the web_agent skill the current LLM as its planning brain."""
        wa = self.registry.get("web_agent")
        if wa is not None:
            wa.llm = self.llm
        st = self.registry.get("share_task")
        if st is not None:
            st.settings = lambda: {
                "path": self.config.share.path,
                "node_name": self.config.personality.name,
                "enabled": self.config.share.enabled,
                "poll_interval": self.config.share.poll_interval,
            }

    def _configure_skills(self) -> None:
        """Apply runtime config to skills that need it."""
        if self.config.external_skills_dir:
            external_registry = ExternalSkillRegistry(
                self.registry, self.config.external_skills_dir
            )
            external_skills = external_registry.load()
            if external_skills:
                logger.info(
                    "Loaded %d external skill(s) from %s",
                    len(external_skills),
                    self.config.external_skills_dir,
                )

        google_skill = self.registry.get("google")
        if isinstance(google_skill, GoogleConnectorSkill):
            google_skill.credentials_file = self.config.google_credentials_file
            google_skill.client_secrets_file = self.config.google_client_secrets_file

    def _build_context(self, goal: str) -> list[dict[str, str]]:
        """Build conversation context with recent messages and recalled memory."""
        messages: list[dict[str, str]] = []
        recalled = self.memory.recall(goal, limit=3)
        if recalled:
            recall_text = "\n".join(
                f"[{m['role']}] {m['content']}" for m in recalled
            )
            messages.append({"role": "system", "content": f"Relevant past context:\n{recall_text}"})
        for m in self.memory.recent_messages(limit=10):
            messages.append({"role": m["role"], "content": m["content"]})
        return messages

    def persona_message(self) -> dict[str, str] | None:
        """System message carrying the configured personality plus the operator's
        business profile (written by the first-run wizard), or None if both empty."""
        p = self.config.personality
        parts: list[str] = []
        if p.enabled and p.persona.strip():
            parts.append(p.persona.strip() + " Stay fully in character when replying.")
        if self._profile_summary is None:
            self._profile_summary = business_summary(load_user_profile())
        if self._profile_summary:
            parts.append(self._profile_summary)
        if not parts:
            return None
        return {"role": "system", "content": "\n\n".join(parts)}

    async def _summarize(self, goal: str, results: list[dict[str, Any]]) -> str:
        prompt = f"Goal: {goal}\nResults: {results}\nSummarize what was done in one or two sentences."
        messages = [{"role": "user", "content": prompt}]
        persona = self.persona_message()
        if persona:
            messages.insert(0, persona)
        response = await self.llm.chat(messages)
        return response.get("content", "Done.")

    def shutdown(self) -> None:
        self.memory.close()
