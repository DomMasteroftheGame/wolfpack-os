"""Scheduler for recurring and deferred agent goals."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    id: str
    goal: str
    run_at: datetime | None = None
    interval_seconds: int | None = None
    last_run: datetime | None = None
    enabled: bool = True


class Scheduler:
    """Simple in-memory scheduler for agent tasks."""

    def __init__(self):
        self.tasks: dict[str, ScheduledTask] = {}
        self._callbacks: list[Callable[[str], Awaitable[None]]] = []
        self._task: asyncio.Task | None = None

    def on_trigger(self, callback: Callable[[str], Awaitable[None]]) -> None:
        self._callbacks.append(callback)

    def add(self, task: ScheduledTask) -> None:
        self.tasks[task.id] = task
        logger.info("Scheduled task %s: %s", task.id, task.goal)

    def remove(self, task_id: str) -> bool:
        if task_id in self.tasks:
            del self.tasks[task_id]
            return True
        return False

    def list_tasks(self) -> list[ScheduledTask]:
        return list(self.tasks.values())

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            now = datetime.now()
            for task in list(self.tasks.values()):
                if not task.enabled:
                    continue
                due = False
                if task.run_at and now >= task.run_at:
                    due = True
                    task.run_at = None  # one-shot consumed
                if task.interval_seconds:
                    if task.last_run is None or (now - task.last_run).total_seconds() >= task.interval_seconds:
                        due = True
                if due:
                    task.last_run = now
                    await self._fire(task)
            await asyncio.sleep(1)

    async def _fire(self, task: ScheduledTask) -> None:
        logger.info("Firing scheduled task %s: %s", task.id, task.goal)
        for callback in self._callbacks:
            try:
                await callback(task.goal)
            except Exception:  # noqa: BLE001
                logger.exception("Scheduler callback failed for task %s", task.id)
