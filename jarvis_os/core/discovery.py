"""LAN peer discovery for Jarvis OS.

Each running instance periodically broadcasts a small UDP beacon describing
itself (host, GUI port, LLM provider/model, and live CPU/RAM load) and listens
for beacons from other instances. This lets a fleet of Jarvis machines see one
another and delegate work to the best-suited peer.

The beacon is a single JSON datagram tagged with a magic string so we ignore
unrelated UDP traffic. Discovery is best-effort: it never raises into the host
application and silently no-ops if the network blocks broadcast.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
import uuid

logger = logging.getLogger(__name__)

DISCOVERY_PORT = 47600            # UDP port beacons are sent to / listened on
MAGIC = "JARVIS_OS_DISCOVERY_1"   # tag so we only parse our own beacons
ANNOUNCE_INTERVAL = 5.0           # seconds between beacons
PEER_TTL = 20.0                   # a peer is "live" if seen within this window

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def _primary_lan_ip() -> str:
    """Best-effort local LAN IP (the address other machines would reach us on)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packets sent; just picks the outbound iface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _load_snapshot() -> dict:
    if psutil is None:
        return {}
    try:
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count": psutil.cpu_count(),
            "mem_percent": psutil.virtual_memory().percent,
            "mem_total": psutil.virtual_memory().total,
        }
    except Exception:  # noqa: BLE001
        return {}


class _BeaconProtocol(asyncio.DatagramProtocol):
    def __init__(self, discovery: "PeerDiscovery"):
        self.discovery = discovery

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            msg = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if msg.get("magic") != MAGIC:
            return
        if msg.get("instance_id") == self.discovery.instance_id:
            return  # ignore our own broadcast
        self.discovery._record_peer(msg, addr[0])

    def error_received(self, exc) -> None:  # pragma: no cover
        logger.debug("discovery datagram error: %s", exc)


class PeerDiscovery:
    """Announces this instance and tracks other Jarvis instances on the LAN."""

    def __init__(self, info_provider):
        """info_provider() returns a dict describing this instance
        (name, gui_host, gui_port, provider, model)."""
        self.info_provider = info_provider
        self.instance_id = uuid.uuid4().hex[:12]
        self.lan_ip = _primary_lan_ip()
        self._peers: dict[str, dict] = {}
        self._transport = None
        self._announce_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", DISCOVERY_PORT))
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _BeaconProtocol(self), sock=sock
            )
        except OSError as exc:
            logger.warning("Peer discovery disabled (cannot bind UDP %d): %s", DISCOVERY_PORT, exc)
            return
        self._running = True
        self._announce_task = loop.create_task(self._announce_loop())
        logger.info("Peer discovery active as %s on %s (udp %d)", self.instance_id, self.lan_ip, DISCOVERY_PORT)

    async def _announce_loop(self) -> None:
        while self._running:
            self._broadcast()
            await asyncio.sleep(ANNOUNCE_INTERVAL)

    def _broadcast(self) -> None:
        if self._transport is None:
            return
        try:
            info = self.info_provider() or {}
        except Exception:  # noqa: BLE001
            info = {}
        beacon = {
            "magic": MAGIC,
            "instance_id": self.instance_id,
            "name": info.get("name", "Jarvis"),
            "lan_ip": self.lan_ip,
            "gui_port": info.get("gui_port"),
            "provider": info.get("provider"),
            "model": info.get("model"),
            "load": _load_snapshot(),
            "ts": time.time(),
        }
        try:
            self._transport.sendto(json.dumps(beacon).encode("utf-8"), ("255.255.255.255", DISCOVERY_PORT))
        except OSError as exc:  # pragma: no cover
            logger.debug("beacon send failed: %s", exc)

    def _record_peer(self, msg: dict, src_ip: str) -> None:
        peer_id = msg.get("instance_id")
        if not peer_id:
            return
        self._peers[peer_id] = {
            "instance_id": peer_id,
            "name": msg.get("name", "Jarvis"),
            "ip": msg.get("lan_ip") or src_ip,
            "gui_port": msg.get("gui_port"),
            "provider": msg.get("provider"),
            "model": msg.get("model"),
            "load": msg.get("load", {}),
            "last_seen": time.time(),
        }

    def peers(self) -> list[dict]:
        """Live peers seen within PEER_TTL, freshest first."""
        now = time.time()
        live = [
            {**p, "age": round(now - p["last_seen"], 1),
             "url": f"http://{p['ip']}:{p['gui_port']}" if p.get("gui_port") else None}
            for p in self._peers.values()
            if now - p["last_seen"] <= PEER_TTL
        ]
        live.sort(key=lambda p: p["last_seen"], reverse=True)
        return live

    def best_peer(self) -> dict | None:
        """The live peer with the most free headroom (lowest CPU load)."""
        candidates = [p for p in self.peers() if p.get("url")]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.get("load", {}).get("cpu_percent", 100.0))

    async def stop(self) -> None:
        self._running = False
        if self._announce_task:
            self._announce_task.cancel()
            try:
                await self._announce_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._transport:
            self._transport.close()
            self._transport = None
