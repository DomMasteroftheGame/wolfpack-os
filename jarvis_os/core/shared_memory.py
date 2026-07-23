"""Fleet-shared, semantic memory router.

Wraps the local SQLite Memory with the same interface, but routes reads/writes
according to config.memory:

- mode "local"  → everything stays on this machine.
- mode "shared" + hub_url set → this instance is a CLIENT: it pushes new memories
  to the hub and recalls from it (so the whole fleet shares one memory), while
  keeping a local copy for resilience.
- mode "shared" + no hub_url → this instance IS the hub: it operates on its own
  local store, which is the shared brain other instances talk to.

Semantic recall ranks memories by embedding similarity (meaning), computed via an
Ollama embeddings endpoint. Every path degrades gracefully — a memory failure
never breaks a goal.
"""

from __future__ import annotations

import logging
import socket
from typing import Any, Callable

import httpx

_HOSTNAME = socket.gethostname()

from jarvis_os.core.memory import Memory

logger = logging.getLogger(__name__)


class MemoryRouter:
    """Local Memory + optional fleet hub, with semantic recall."""

    def __init__(self, local: Memory, settings: Callable[[], dict[str, Any]]):
        """settings() returns a live dict:
        {mode, hub_url, embed_url, embed_model, semantic}."""
        self.local = local
        self._settings = settings

    # ---- config helpers ---------------------------------------------------
    def _cfg(self) -> dict[str, Any]:
        return self._settings() or {}

    def _is_client(self, cfg: dict[str, Any]) -> bool:
        return cfg.get("mode") == "shared" and bool(cfg.get("hub_url"))

    def _embed(self, text: str, cfg: dict[str, Any]) -> list[float] | None:
        """Compute an embedding via the configured Ollama endpoint (sync, best-effort)."""
        if not cfg.get("semantic", True):
            return None
        base = (cfg.get("embed_url") or "").rstrip("/")
        if not base:
            return None
        try:
            resp = httpx.post(
                f"{base}/api/embeddings",
                json={"model": cfg.get("embed_model", "nomic-embed-text"), "prompt": text},
                timeout=15.0,
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding")
            return vec if vec else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("embedding failed: %s", exc)
            return None

    # ---- Memory-compatible interface -------------------------------------
    def add_message(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        cfg = self._cfg()
        if self._is_client(cfg):
            # Keep a local copy for resilience, then push to the hub (hub embeds).
            try:
                self.local.add_message(role, content, metadata)
            except Exception as exc:  # noqa: BLE001
                logger.debug("local cache write failed: %s", exc)
            hub = cfg["hub_url"].rstrip("/")
            try:
                httpx.post(
                    f"{hub}/api/memory/add",
                    json={"role": role, "content": content, "metadata": metadata or {}, "source": _HOSTNAME},
                    timeout=8.0,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("hub push failed (%s); kept local copy", exc)
            return
        # Hub or local-only: store here, with an embedding when semantic is on.
        emb = self._embed(content, cfg)
        self.local.add_message(role, content, metadata, embedding=emb)

    def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        cfg = self._cfg()
        if self._is_client(cfg):
            hub = cfg["hub_url"].rstrip("/")
            try:
                resp = httpx.post(
                    f"{hub}/api/memory/recall",
                    json={"query": query, "limit": limit},
                    timeout=15.0,
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                logger.debug("hub recall failed (%s); falling back to local", exc)
                return self._local_recall(query, limit, cfg)
        return self._local_recall(query, limit, cfg)

    def _local_recall(self, query: str, limit: int, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        if cfg.get("semantic", True):
            qv = self._embed(query, cfg)
            if qv:
                hits = self.local.semantic_search(qv, limit)
                if hits:
                    return hits
        # Fall back to keyword full-text search.
        return self.local.recall(query, limit)

    def recent_messages(self, limit: int = 20) -> list[dict[str, Any]]:
        # Working memory (recent turns) stays local per-machine.
        return self.local.recent_messages(limit)

    def set_fact(self, key: str, value: str) -> None:
        self.local.set_fact(key, value)

    def get_fact(self, key: str) -> str | None:
        return self.local.get_fact(key)

    def stats(self) -> dict[str, int]:
        return self.local.stats()

    def close(self) -> None:
        self.local.close()
