"""Hub-spoke mesh registry — the Wolfpack topology over Tailscale.

Ports the hub's model (src/lib/peers/peer-registry.ts + election): hubs run over a
Tailscale flat net, each addressable by a stable id + URL; every hub probes its
peers, the lowest reachable hub-id is the leader (fires scheduled work + owns state),
and cross-hub calls carry a shared `x-wolfpack-token`. Roles: `hub` (full),
`wedge` (partial hub), `dedicated-peer` (one agent's home box).

v1 = registry + token auth + HTTP probing + lowest-id election + load-aware peer
pick. Virtual-peer regeneration + per-file state replication are v2 (the hub does
these; noted where they'd hook in).

Reference machine->IP map (from the live pack; real values live in config/wolfpack.yaml):
  cpu1            100.77.165.3   hub-1 :3000 / hub-2 :3001 (ledger wedge)
  desktop-jcdlq72 100.74.90.84   hub-3 :3000 / hub-4 :3001
  cav8ebg         100.81.234.111 Ranger events box (dedicated-peer)
  cav8ebg-1       100.92.32.69   Tracker analytics box (dedicated-peer)
  macbook-pro     100.66.4.113   hub-mac :3000 (Sentinel home, prod)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

ROLES = ("hub", "wedge", "dedicated-peer")
HUB_ROLES = ("hub", "wedge")  # roles eligible to be leader


@dataclass
class Peer:
    id: str                       # stable id, e.g. "hub-1", "hub-mac"
    url: str                      # base URL, e.g. "http://100.66.4.113:3000"
    role: str = "hub"             # hub | wedge | dedicated-peer
    agent_id: str | None = None   # dedicated-peer home agent (e.g. "events")
    healthy: bool = False
    last_seen: float = 0.0
    pending_orders: int = 0
    error: str | None = None


class MeshRegistry:
    def __init__(
        self,
        *,
        hub_id: str,
        token: str | None = None,
        role: str = "hub",
        peers: list | None = None,
        agent_blacklist: list[str] | None = None,
        health_path: str = "/api/whoami",
        timeout: float = 5.0,
    ):
        self.hub_id = hub_id
        self.token = token
        self.role = role
        self.agent_blacklist = set(agent_blacklist or [])
        self.health_path = health_path
        self.timeout = timeout
        self.peers: dict[str, Peer] = {}
        for p in peers or []:
            self.add_peer(p if isinstance(p, Peer) else Peer(**p))
        self._refresh_task: asyncio.Task | None = None
        self._running = False

    # ── registry ──────────────────────────────────────────────────────────────
    def add_peer(self, peer: Peer) -> None:
        self.peers[peer.id] = peer

    def auth_headers(self) -> dict[str, str]:
        # Same shared secret the whole mesh uses; unset => trust mode (Tailscale perimeter).
        return {"x-wolfpack-token": self.token} if self.token else {}

    # ── health probing ────────────────────────────────────────────────────────
    async def probe(self, peer: Peer, client: httpx.AsyncClient, now=time.time) -> bool:
        try:
            r = await client.get(peer.url.rstrip("/") + self.health_path, headers=self.auth_headers())
            peer.healthy = r.status_code == 200
            peer.error = None if peer.healthy else f"http {r.status_code}"
            if peer.healthy:
                peer.last_seen = now()
        except Exception as exc:  # noqa: BLE001 — an unreachable peer is a normal state
            peer.healthy = False
            peer.error = str(exc)
        return peer.healthy

    async def refresh(self, client: httpx.AsyncClient | None = None) -> dict[str, Peer]:
        owns = client is None
        client = client or httpx.AsyncClient(timeout=self.timeout)
        try:
            await asyncio.gather(*(self.probe(p, client) for p in self.peers.values()))
        finally:
            if owns:
                await client.aclose()
        return self.peers

    async def _refresh_loop(self, interval: float) -> None:
        while self._running:
            try:
                await self.refresh()
            except Exception as exc:  # noqa: BLE001
                logger.debug("mesh refresh failed: %s", exc)
            await asyncio.sleep(interval)

    async def start_refresh(self, interval: float = 10.0) -> None:
        if self._running:
            return
        self._running = True
        self._refresh_task = asyncio.get_running_loop().create_task(self._refresh_loop(interval))

    async def stop_refresh(self) -> None:
        self._running = False
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None

    # ── leader election (lowest reachable hub-id wins) ─────────────────────────
    def reachable_hub_ids(self) -> list[str]:
        ids = {self.hub_id} | {
            p.id for p in self.peers.values() if p.role in HUB_ROLES and p.healthy
        }
        return sorted(ids)

    def leader(self) -> str:
        hubs = self.reachable_hub_ids()
        return hubs[0] if hubs else self.hub_id

    def is_leader(self) -> bool:
        return self.leader() == self.hub_id

    # ── load-aware routing ─────────────────────────────────────────────────────
    def pick_peer_for(self, agent_id: str) -> Peer | None:
        """Fewest-pending healthy peer that can serve `agent_id`, honoring the
        per-hub agent blacklist (e.g. Windows hubs blacklist `tech` -> route to mac)."""
        if agent_id in self.agent_blacklist:
            return None
        candidates = [
            p for p in self.peers.values()
            if p.healthy and (p.agent_id in (None, agent_id))
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.pending_orders)
