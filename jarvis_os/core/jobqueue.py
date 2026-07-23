"""In-memory work-stealing job queue.

Lives on the queue hub. Any node with spare capacity claims the next pending
job atomically, runs it, and reports completion. Adding a node simply means one
more claimer draining the queue — throughput rises the instant it joins.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class JobQueue:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._pending: deque[str] = deque()
        self._lock = threading.Lock()
        self._seq = 0

    def submit(self, goal: str, agent: str = "simple", meta: dict | None = None) -> str:
        with self._lock:
            self._seq += 1
            jid = f"job-{self._seq}"
            self._jobs[jid] = {
                "id": jid, "goal": goal, "agent": agent, "state": "pending",
                "worker": None, "submitted_at": time.time(),
                "started_at": None, "finished_at": None,
                "result_summary": None, "error": None, "meta": meta or {},
            }
            self._pending.append(jid)
            return jid

    def claim(self, worker: str) -> dict[str, Any] | None:
        """Atomically hand the next pending job to a worker."""
        with self._lock:
            while self._pending:
                jid = self._pending.popleft()
                job = self._jobs.get(jid)
                if job and job["state"] == "pending":
                    job["state"] = "running"
                    job["worker"] = worker
                    job["started_at"] = time.time()
                    return {"id": jid, "goal": job["goal"], "agent": job["agent"]}
            return None

    def complete(self, jid: str, worker: str, result: Any = None, error: str | None = None) -> bool:
        with self._lock:
            job = self._jobs.get(jid)
            if not job:
                return False
            job["state"] = "failed" if error else "done"
            job["error"] = error
            job["finished_at"] = time.time()
            if isinstance(result, dict):
                job["result_summary"] = result.get("summary") or result.get("answer") or ""
            elif result is not None:
                job["result_summary"] = str(result)[:500]
            return True

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j["submitted_at"], reverse=True)[:limit]
            out = []
            for j in jobs:
                took = None
                if j["started_at"] and j["finished_at"]:
                    took = round(j["finished_at"] - j["started_at"], 1)
                out.append({
                    "id": j["id"], "goal": j["goal"], "state": j["state"],
                    "worker": j["worker"], "took": took,
                    "result_summary": j["result_summary"], "error": j["error"],
                })
            return out

    def stats(self) -> dict[str, int]:
        with self._lock:
            s = {"pending": 0, "running": 0, "done": 0, "failed": 0}
            for j in self._jobs.values():
                s[j["state"]] = s.get(j["state"], 0) + 1
            s["total"] = len(self._jobs)
            return s
