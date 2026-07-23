"""Run the game copilot LIVE against a logged-in browser.

    # 1. human logs into the game once in a CDP browser (see scripts/start-chrome-cdp.sh)
    # 2. run the copilot:
    python -m jarvis_os.core.copilot_runner --config config/jarvis.yaml

v1: the copilot is a LOCAL coach — it rides the logged-in game session over CDP,
nudges on screen changes, and chats back through an in-page "DOM COPILOT" bubble
(served by a localhost service). Progress is stored on this machine under
data/copilot/. Advise-only by default; --enable-actions lets it click/type.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from jarvis_os.core import copilot_store

SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 8787
OVERLAY_JS = Path(__file__).with_name("copilot_overlay.js")

# JS evaluated in the page: compact structured game state as a JSON string.
STATE_JS = """(function(){
  try {
    var u = JSON.parse(localStorage.getItem('wolfpack_user') || 'null');
    return JSON.stringify({
      route: location.hash || '(none)',
      onboardingStep: u && u.onboardingStep,
      name: u && u.name,
      startup: u && u.alphaPitch && u.alphaPitch.headline,
      product: u && u.selected_product_id,
      card: u && u.selected_card_id,
      ivp: u && u.ivp
    });
  } catch(e) { return JSON.stringify({error: String(e)}); }
})()"""


class CopilotService:
    """Tiny FastAPI service: nudge feed + chat + overlay assets + state debug."""

    def __init__(self, copilot, get_state_brief):
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, HTMLResponse

        self.copilot = copilot
        self.get_state_brief = get_state_brief
        self.nudges: list[dict] = []
        self.chat_history: list[dict[str, str]] = []

        app = FastAPI(title="dom-copilot", docs_url=None, redoc_url=None)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.get("/nudges")
        async def nudges(since: float = 0):
            return {"nudges": [n for n in self.nudges if n["ts"] > since]}

        @app.post("/chat")
        async def chat(payload: dict):
            text = (payload.get("text") or "").strip()
            if not text:
                return {"reply": "Say something first, wolf."}
            brief = await self.get_state_brief()
            reply = await self.copilot.chat(text, brief, self.chat_history)
            self.chat_history.append({"role": "user", "content": text})
            self.chat_history.append({"role": "assistant", "content": reply})
            self.chat_history = self.chat_history[-10:]
            copilot_store.log_event("chat", {"user": text, "dom": reply})
            return {"reply": reply}

        @app.get("/state")
        async def state():
            return {"latest": copilot_store.read_latest(), "brief": await self.get_state_brief()}

        @app.get("/overlay.js")
        async def overlay_js():
            return FileResponse(OVERLAY_JS, media_type="application/javascript")

        @app.get("/", response_class=HTMLResponse)
        async def standalone():
            # Fallback panel when injection isn't possible.
            return HTMLResponse(
                "<!doctype html><html><head><title>Dom Copilot</title>"
                "<style>body{background:#0a0a0c;margin:0}</style></head>"
                "<body><script src=\"/overlay.js\"></script></body></html>"
            )

        self.app = app

    def push_nudge(self, text: str) -> None:
        self.nudges.append({"ts": int(time.time() * 1000), "text": text})
        self.nudges = self.nudges[-50:]

    async def serve(self):
        import uvicorn
        config = uvicorn.Config(self.app, host=SERVICE_HOST, port=SERVICE_PORT, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()


AGENT_BROWSER_INSTALL_MSG = (
    "The game copilot needs the agent-browser CLI.\n"
    "Install it with npm (may require sudo on Linux):\n"
    "  npm i -g agent-browser\n"
    "  agent-browser install\n"
    "Then launch a logged-in CDP browser:\n"
    "  bash scripts/start-chrome-cdp.sh"
)


async def run_game_copilot(config, provider, notify=None, interval: float = 4.0,
                           should_continue=None, enable_actions: bool = False):
    from jarvis_os.core.game_copilot import GameCopilot
    from jarvis_os.core.agent_browser import AgentBrowser

    app = config.embedded_app
    if not app.enabled:
        raise RuntimeError(
            "embedded_app is disabled in config. Set embedded_app.enabled=true "
            "and embedded_app.cdp_url to the CDP port of your logged-in browser."
        )

    port = 9222
    if app.cdp_url:
        try:
            port = urlparse(app.cdp_url).port or 9222
        except ValueError:
            pass

    browser = AgentBrowser(cdp_port=port)
    if not browser.available():
        raise RuntimeError(AGENT_BROWSER_INSTALL_MSG)

    await browser.connect()          # attach to the already-logged-in session
    await browser.open(app.url)       # /pages/game#/select-startup

    persona_prompt = config.personality.persona if config.personality.enabled else None
    copilot = GameCopilot(provider, persona_prompt=persona_prompt)
    name = getattr(config.personality, "name", "Alpha")

    last_structured: dict = {}
    last_snapshot = ""

    async def read_structured() -> dict:
        out = ""
        try:
            out = (await browser.eval_js(STATE_JS)).strip()
            val = json.loads(out)          # may be a JSON-encoded string or an object
            if isinstance(val, str):
                val = json.loads(val)      # double-decode
            return val if isinstance(val, dict) else {"raw": out[:200]}
        except Exception as e:
            return {"error": str(e)}

    async def state_brief() -> str:
        parts = []
        if last_structured:
            parts.append(f"Structured state: {json.dumps(last_structured, ensure_ascii=False)}")
        if last_snapshot:
            parts.append(f"Screen snapshot:\n{last_snapshot}")
        return "\n\n".join(parts) or "(no game state read yet)"

    service = CopilotService(copilot, state_brief)

    async def perceive() -> str:
        nonlocal last_structured, last_snapshot
        snapshot = await browser.snapshot()
        structured = await read_structured()
        last_snapshot = snapshot
        last_structured = structured

        # (Re)inject the overlay bubble if the page lost it (reloads).
        try:
            injected = (await browser.eval_js("window.__domCopilot ? 1 : 0")).strip()
            if injected != "1":
                await browser.eval_js(OVERLAY_JS.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[{name} copilot] overlay injection note: {e}")

        if structured and structured != {"error": ""} and "error" not in structured:
            copilot_store.update_latest(**structured)
        copilot_store.log_event("observation", {"structured": structured})
        return await state_brief()

    async def _notify(msg: str) -> None:
        print(f"[{name} copilot] {msg}")
        service.push_nudge(msg)
        copilot_store.log_event("nudge", {"text": msg})
        copilot_store.update_latest(last_nudge=msg)

    if notify is None:
        notify = _notify
    act = browser.act if enable_actions else None

    print(f"{name} copilot live on {app.url} (CDP :{port}). "
          f"Service on http://{SERVICE_HOST}:{SERVICE_PORT} "
          f"({'actions ON' if enable_actions else 'advise-only'}). Ctrl-C to stop.")
    try:
        await asyncio.gather(
            service.serve(),
            copilot.run(
                perceive=perceive,
                notify=notify,
                act=act,
                interval=interval,
                should_continue=should_continue or (lambda: True),
            ),
        )
    finally:
        await browser.close()  # graceful — never force-kill the profile


if __name__ == "__main__":
    import argparse

    from jarvis_os.config import load_config
    from jarvis_os.llm.providers import get_provider

    ap = argparse.ArgumentParser(description="Run the BuildYourWolfpack game copilot")
    ap.add_argument("--config", default="config/jarvis.yaml")
    ap.add_argument("--interval", type=float, default=4.0, help="seconds between screen checks")
    ap.add_argument("--enable-actions", action="store_true",
                    help="let the copilot click/type (default: advise-only)")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    try:
        asyncio.run(run_game_copilot(cfg, get_provider(cfg.llm),
                                     interval=args.interval,
                                     enable_actions=args.enable_actions))
    except RuntimeError as exc:
        print(f"\n[Copilot] {exc}\n", file=sys.stderr)
        raise SystemExit(1)
