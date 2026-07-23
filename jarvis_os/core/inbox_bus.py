"""Inbox / event bus — the inter-wolf messaging spine.

Ports the hub's `/api/sentinel/inbox` contract (and the Node module of the same
design) into the OS: one canonical envelope, a durable append-only JSONL log, a
shared-secret (`x-wolfpack-token`) gate on writes, and targeted+broadcast reads.
Every subsystem (health alerts, deploy status, delegation) posts through here.

Envelope: {ts, from, to, event, level, text, meta}  (from/to as JSON keys —
`from` is a Python keyword, so envelopes are plain dicts, matching the wire format).
`text` or `meta` is required.
"""
from __future__ import annotations

import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path

EVENTS = ["push", "deploy", "deploy-failed", "blocker", "message", "task", "task-result"]
LEVELS = ["info", "warn", "error"]
MAX_TEXT = 4000

_DELEGATE_RE = re.compile(r"\[DELEGATE:([a-zA-Z0-9_-]+)\]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(body: dict, now: str | None = None) -> dict:
    """Coerce an arbitrary body into a well-formed envelope."""
    return {
        "ts": now or _now_iso(),
        "from": str(body.get("from", "unknown")),      # e.g. "ceo@hub-1"
        "to": str(body["to"]) if body.get("to") else None,   # target peer, or None = broadcast
        "event": str(body.get("event", "message")),
        "level": str(body.get("level", "info")),
        "text": str(body.get("text", ""))[:MAX_TEXT],
        "meta": body.get("meta"),
    }


def validate(msg: dict) -> str | None:
    if not msg.get("text") and not msg.get("meta"):
        return "text or meta required"
    return None


def authorized(provided: str | None, token: str | None) -> bool:
    """Constant-time token check. No token configured => trust mode (Tailscale perimeter)."""
    if not token:
        return True
    return hmac.compare_digest(str(provided or "").strip(), token)


def parse_delegations(text: str | None) -> list[str]:
    """Pull [DELEGATE:agentId] tags out of an agent's reply (the pack's routing hook)."""
    return _DELEGATE_RE.findall(text or "")


class Inbox:
    def __init__(self, path: str | Path, now=None):
        self.path = Path(path)
        self._now = now  # optional callable () -> iso str (testing)

    def _ts(self) -> str:
        return self._now() if self._now else _now_iso()

    def post(self, body: dict) -> dict:
        msg = normalize(body, self._ts())
        err = validate(msg)
        if err:
            return {"ok": False, "error": err}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg) + "\n")
        return {"ok": True, "stored": msg}

    def list(self, limit: int = 50, to: str | None = None) -> dict:
        """List messages. With `to`, returns that peer's targeted messages plus
        broadcasts (to is None) — how a wolf sees everything addressed to it."""
        msgs: list[dict] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    msgs.append(json.loads(line))
                except json.JSONDecodeError:
                    msgs.append({"raw": line})
        except FileNotFoundError:
            return {"ok": True, "count": 0, "messages": []}
        if to:
            msgs = [m for m in msgs if m.get("to") == to or m.get("to") is None]
        msgs = msgs[-max(0, min(limit, 500)):]
        return {"ok": True, "count": len(msgs), "messages": msgs}


def create_inbox_router(inbox: Inbox, token: str | None = None):
    """FastAPI router matching the mesh contract — mount into the GUI app:
        app.include_router(create_inbox_router(inbox, token))
    POST /api/inbox (x-wolfpack-token) -> {ok,stored}; GET /api/inbox?limit=&to= -> {ok,count,messages}
    """
    from typing import Any

    from fastapi import APIRouter, Body, Header
    from fastapi.responses import JSONResponse

    router = APIRouter()

    @router.post("/api/inbox")
    async def send(
        body: dict[str, Any] = Body(default_factory=dict),
        x_wolfpack_token: str | None = Header(default=None),
    ):
        if not authorized(x_wolfpack_token, token):
            return JSONResponse({"ok": False, "error": "missing or invalid x-wolfpack-token"}, status_code=401)
        result = inbox.post(body)
        return JSONResponse(result, status_code=200 if result["ok"] else 400)

    @router.get("/api/inbox")
    async def poll(limit: int = 50, to: str | None = None):
        return inbox.list(limit=limit, to=to)

    return router
