"""Share task-bus — fleet coordination through the shared drive.

Node firewalls block direct HTTP delegation, but every node can reach the NAS
share. So tasks flow through files on the share instead of the network:

    <share>/fleet/inbox/<NodeName>/<taskid>.json   -> a job addressed to that node
    <share>/fleet/results/<taskid>.json            <- the result, written by the runner

Each node polls only its OWN inbox (keyed by its personality name), so there is
no cross-node claim race. Firewalls become irrelevant — the share is the bus.
"""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import platform
import time
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_AUTODETECT_CACHE: list[str | None] = []


def _autodetect_share() -> str | None:
    """Find the mounted JarvisOS share automatically (so nodes need no path config)."""
    if _AUTODETECT_CACHE:
        return _AUTODETECT_CACHE[0]
    cands: list[str] = []
    if platform.system() == "Windows":
        cands = [r"\\CASHMONEY\Public\JarvisOS", r"\\cashmoney.local\Public\JarvisOS"]
    else:
        cands = ["/mnt/jarvis-share"]
        for pat in ("/media/*/JarvisOS", "/media/*", "/mnt/*", "/srv/*",
                    "/run/user/*/gvfs/*", os.path.expanduser("~/jarvis-share")):
            cands.extend(glob.glob(pat))
    found = None
    for c in cands:
        try:
            p = Path(c)
            if (p / "JarvisOS-ready").exists() or (p / "fleet").exists():
                found = c
                break
        except Exception:  # noqa: BLE001
            continue
    _AUTODETECT_CACHE.append(found)
    if found:
        logger.info("Share task-bus auto-detected share at %s", found)
    return found


class ShareBus:
    def __init__(self, runtime: Any, settings: Callable[[], dict[str, Any]]):
        """settings() -> {enabled, path, node_name, poll_interval}."""
        self.runtime = runtime
        self._settings = settings
        self._running = False
        self._task: asyncio.Task | None = None

    # ---- paths ----
    def _root(self, cfg) -> Path | None:
        path = cfg.get("path") or _autodetect_share()
        if not path:
            return None
        return Path(path) / "fleet"

    def _inbox(self, cfg, node: str) -> Path:
        return self._root(cfg) / "inbox" / node

    def _results(self, cfg) -> Path:
        return self._root(cfg) / "results"

    # ---- lifecycle ----
    async def start(self) -> None:
        self._running = True
        self._task = asyncio.get_running_loop().create_task(self._loop())
        logger.info("Share task-bus loop started (idle until share.enabled).")

    async def _loop(self) -> None:
        while self._running:
            cfg = self._settings()
            if not cfg.get("enabled") or self._root(cfg) is None:
                await asyncio.sleep(5.0)  # idle until enabled + a share is reachable
                continue
            try:
                await self._drain(cfg)
            except Exception as exc:  # noqa: BLE001
                logger.debug("share-bus drain error: %s", exc)
            await asyncio.sleep(cfg.get("poll_interval", 3.0))

    async def _drain(self, cfg) -> None:
        node = cfg["node_name"]
        inbox = self._inbox(cfg, node)
        inbox.mkdir(parents=True, exist_ok=True)
        self._results(cfg).mkdir(parents=True, exist_ok=True)
        for taskfile in sorted(inbox.glob("*.json")):
            # claim by rename so a re-poll won't run it twice
            claimed = taskfile.with_suffix(".running")
            try:
                taskfile.rename(claimed)
            except OSError:
                continue  # someone/thing already grabbed it
            try:
                task = json.loads(claimed.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                claimed.unlink(missing_ok=True)
                continue
            asyncio.get_running_loop().create_task(self._run(cfg, task, claimed))

    async def _run(self, cfg, task, claimed: Path) -> None:
        tid = task.get("id", "?")
        started = time.time()
        result: dict[str, Any] = {"id": tid, "node": cfg["node_name"], "goal": task.get("goal", "")}
        try:
            res = await self.runtime.run_with_agent(task.get("goal", ""), agent_type=task.get("agent", "simple"))
            result["ok"] = True
            result["summary"] = res.get("summary") or res.get("answer") or ""
            result["result"] = res
        except Exception as exc:  # noqa: BLE001
            result["ok"] = False
            result["error"] = str(exc)
        result["seconds"] = round(time.time() - started, 1)
        try:
            (self._results(cfg) / f"{tid}.json").write_text(json.dumps(result, default=str), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.debug("share-bus result write failed: %s", exc)
        claimed.unlink(missing_ok=True)

    # ---- API used by the web layer ----
    def submit(self, target_node: str, goal: str, agent: str = "simple") -> dict[str, Any]:
        cfg = self._settings()
        if self._root(cfg) is None:
            return {"ok": False, "error": "no JarvisOS share reachable on this node"}
        tid = "t-" + uuid.uuid4().hex[:10]
        box = self._inbox(cfg, target_node)
        box.mkdir(parents=True, exist_ok=True)
        payload = {"id": tid, "goal": goal, "agent": agent, "target": target_node, "submitted": time.time()}
        # write to a temp name then rename in, so a poller never reads a half-written file
        tmp = box / f".{tid}.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.rename(box / f"{tid}.json")
        return {"ok": True, "id": tid, "target": target_node}

    def result(self, tid: str) -> dict[str, Any] | None:
        cfg = self._settings()
        if self._root(cfg) is None:
            return None
        f = self._results(cfg) / f"{tid}.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
        return None

    def nodes(self) -> list[str]:
        """Node inboxes present on the share (who can receive share tasks)."""
        cfg = self._settings()
        root = self._root(cfg)
        if not root:
            return []
        idir = root / "inbox"
        if not idir.exists():
            return []
        return sorted(p.name for p in idir.iterdir() if p.is_dir())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
