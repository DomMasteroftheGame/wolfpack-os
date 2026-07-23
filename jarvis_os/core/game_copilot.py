"""Game copilot — keeps the BuildYourWolfpack game going for the player.

The game is a hash-routed SPA at
  https://buildyourwolfpack.com/pages/game#/select-startup
The player picks a startup at `select-startup`, then builds it. The copilot rides
along: it reads the current screen (an accessibility-tree snapshot), works out where
the player is and what's next, and helps them keep moving — a suggestion to surface
(via Alpha's voice) and, when useful, a concrete UI action to take.

This module is the copilot BRAIN — game-agnostic, LLM-driven, testable offline. The
perception (snapshot) and action (click/type) are injected callables so the same loop
works whether it drives agent-browser (pack standard, CDP to a logged-in session) or
a test double. It never assumes specific screens — it reasons over whatever the game
shows.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from jarvis_os.core.game_knowledge import prompt_block as game_knowledge_block

CHAT_SYSTEM_PROMPT = (
    "You are Dom — co-founder, the Myspace Tom of Wolfpack: 'I connect visionaries to "
    "reality.' You are the player's personal coach inside the BuildYourWolfpack startup "
    "game. Answer their questions in character: warm, direct, a little hungry. Always "
    "anchor to their ACTUAL game state (the screen/state brief you're given) and the "
    "40-step mission map — name their current step and the next one. If they ask what "
    "to do, give ONE concrete move, not a menu. Keep answers short (2-5 sentences) "
    "unless they ask for a deep dive."
)


SYSTEM_PROMPT = (
    "You are the AI co-pilot inside the BuildYourWolfpack startup game — the 24/7 mentor "
    "that scales 1:1 guidance to every student pack. Your ONE job is to KEEP THE GAME "
    "GOING at EVERY stage — from picking a startup, through building it, running "
    "scenarios, pivots, and launch. Read the current screen (an accessibility-tree "
    "snapshot), see where the player is, and give the single best next step so they "
    "never stall. You ride along the WHOLE journey, not just the start.\n\n"
    "You help students build a real startup, closing four gaps:\n"
    "  1. PURPOSE↔MARKET: tie what they love (Ikigai) to real demand — reference live "
    "signals (SAM.gov, BLS, job markets) so purpose meets the market in data, not theory.\n"
    "  2. MENTORSHIP AT SCALE: co-write hypotheses, customer-interview scripts, and pivot "
    "calls — patient, concrete, always available.\n"
    "  3. GO-TO-MARKET: push them toward outreach, a landing page, an early-adopter list, "
    "and message tests so first revenue is achievable, not aspirational.\n"
    "  4. Surface relevant alumni/expertise when a step calls for it.\n\n"
    "Be concise, encouraging, and specific. Advise; don't take over creative choices.\n\n"
    "Respond with ONLY a JSON object:\n"
    '  {"observation": "<one line: what screen/state this is>",\n'
    '   "message": "<what to say to the player to keep them moving>",\n'
    '   "action": {"kind": "click|type|navigate|none", "target": "<@ref from the snapshot>", "value": "<if type>"} }\n'
    "Use action.kind 'none' when the player should decide — then your message guides."
)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM reply (tolerant of prose/fences)."""
    start = text.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


class GameCopilot:
    def __init__(self, provider, persona_prompt: str | None = None):
        # provider: an LLMProvider (claude_cli in prod, kimi in testing).
        self.provider = provider
        self.persona_prompt = persona_prompt  # optional: Alpha's voice on the messages

    async def next_move(self, snapshot_text: str) -> dict:
        """Given the current screen snapshot, decide the next copilot move."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": game_knowledge_block()},
        ]
        if self.persona_prompt:
            messages.append({"role": "system", "content": self.persona_prompt})
        messages.append({"role": "user", "content": f"Current game screen:\n{snapshot_text}"})
        resp = await self.provider.chat(messages)
        move = _extract_json(resp.get("content", "")) or {}
        move.setdefault("observation", "")
        move.setdefault("message", "")
        move.setdefault("action", {"kind": "none"})
        return move

    async def chat(self, user_text: str, state_brief: str,
                   history: list[dict[str, str]] | None = None) -> str:
        """Answer a player message, in character, anchored to live game state.

        state_brief: compact text of the current screen/structured state.
        history: prior [{"role": "user"|"assistant", "content": ...}] for continuity.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "system", "content": game_knowledge_block()},
        ]
        if self.persona_prompt:
            messages.append({"role": "system", "content": self.persona_prompt})
        for msg in (history or [])[-10:]:
            messages.append(msg)
        messages.append({
            "role": "user",
            "content": f"[Player's current game state]\n{state_brief}\n\n[Player says]\n{user_text}",
        })
        resp = None
        try:
            resp = await self.provider.chat(messages)
        except Exception as e:
            print(f"[copilot] chat brain error: {e}")
            return "(Dom static — my brain hiccuped. Ask me again in a few seconds.)"
        return resp.get("content", "").strip()

    async def run(
        self,
        perceive: Callable[[], Awaitable[str]],
        notify: Callable[[str], Awaitable[Any]],
        act: Callable[[dict], Awaitable[Any]] | None = None,
        should_continue: Callable[[], bool] = lambda: True,
        interval: float = 0.0,
        max_steps: int = 100000,
    ) -> None:
        """Copilot loop: snapshot -> (on change) decide -> tell the player (+ act).

        Reacts to screen CHANGES rather than polling the LLM every tick, so it advises
        once per new state instead of repeating itself.

        perceive() -> screen snapshot text (wire to agent-browser `snapshot -i -c`)
        notify(msg) -> surface the suggestion (wire to Alpha's voice / UI)
        act(action) -> perform a UI action (wire to agent-browser); None = advise-only
        """
        import asyncio
        last_snapshot = None
        steps = 0
        errors = 0
        while should_continue() and steps < max_steps:
            steps += 1
            snapshot = await perceive()
            if snapshot and snapshot != last_snapshot:
                last_snapshot = snapshot
                try:
                    move = await self.next_move(snapshot)
                    errors = 0
                except Exception as e:
                    # A brain hiccup (model loading, server restart) must not kill
                    # the copilot — log, back off, keep watching.
                    errors += 1
                    print(f"[copilot] brain error ({errors}): {e}")
                    if errors == 3:
                        await notify("(Dom static — my brain hiccuped. Still watching; I'll chime back in.)")
                    await asyncio.sleep(max(interval, 5.0) * errors)
                    continue
                if move.get("message"):
                    await notify(move["message"])
                action = move.get("action") or {}
                if act and action.get("kind") and action["kind"] != "none":
                    await act(action)
                    last_snapshot = None  # our action changed the screen -> re-read next tick
            if interval:
                await asyncio.sleep(interval)
