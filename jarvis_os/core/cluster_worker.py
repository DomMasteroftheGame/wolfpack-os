"""Work-stealing worker loop.

Runs on every participating node. Whenever the node has spare capacity it claims
the next job from the queue hub (or the local queue if this node is the hub),
executes it, and reports the result back. The loop reads config live, so it can
be enabled/disabled without a restart.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)
_HOST = socket.gethostname()


class ClusterWorker:
    def __init__(self, runtime: Any, local_queue: Any, settings: Callable[[], dict[str, Any]]):
        """settings() -> {worker_enabled, queue_url, max_concurrent, poll_interval}."""
        self.runtime = runtime
        self.local_queue = local_queue
        self._settings = settings
        self._running = False
        self._active = 0
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.get_running_loop().create_task(self._loop())
        logger.info("Cluster worker loop started (idle until worker_enabled).")

    async def _loop(self) -> None:
        while self._running:
            cfg = self._settings()
            if not cfg.get("worker_enabled"):
                await asyncio.sleep(1.0)
                continue
            if self._active >= cfg.get("max_concurrent", 2):
                await asyncio.sleep(0.4)
                continue
            job = await self._claim(cfg)
            if job is None:
                await asyncio.sleep(cfg.get("poll_interval", 2.0))
                continue
            self._active += 1
            asyncio.get_running_loop().create_task(self._run_job(job, cfg))

    async def _claim(self, cfg: dict[str, Any]) -> dict[str, Any] | None:
        qurl = cfg.get("queue_url")
        if not qurl:  # this node is the hub — claim locally
            return self.local_queue.claim(_HOST)
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(f"{qurl.rstrip('/')}/api/jobs/claim", json={"worker": _HOST})
                if r.status_code == 200:
                    return r.json().get("job")
        except Exception as exc:  # noqa: BLE001
            logger.debug("claim failed: %s", exc)
        return None

    async def _run_job(self, job: dict[str, Any], cfg: dict[str, Any]) -> None:
        try:
            res = await self.runtime.run_with_agent(job["goal"], agent_type=job.get("agent", "simple"))
            await self._complete(cfg, job["id"], res, None)
        except Exception as exc:  # noqa: BLE001
            await self._complete(cfg, job["id"], None, str(exc))
        finally:
            self._active -= 1

    async def _complete(self, cfg: dict[str, Any], jid: str, result: Any, error: str | None) -> None:
        qurl = cfg.get("queue_url")
        if not qurl:
            self.local_queue.complete(jid, _HOST, result, error)
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{qurl.rstrip('/')}/api/jobs/complete",
                    json={"job_id": jid, "worker": _HOST, "result": result, "error": error},
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("complete post failed: %s", exc)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
