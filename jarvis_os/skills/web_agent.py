"""Web Agent skill — autonomous browser automation.

Drives a real Chromium browser (via Playwright) to accomplish a natural-language
task: navigate, read the page, fill forms, pick dropdowns, upload files, click
buttons, sign up, submit. Handles content inside iframes and custom (non-native)
dropdowns.

Ported and generalized from the user's JobHunterAI Playwright engine — the same
element-tagging + snapshot + execute core that already solved the hard gotchas
(React submit-hangs, custom comboboxes, upload-first, iframe ATS forms).

THE BRAIN: this skill uses the runtime's configured LLM to decide each action.
It needs a capable model (Claude-class) to be reliable — the local 7B will
struggle with real forms. Set the LLM provider to `anthropic` for production use.

ACCESSIBILITY: built for the disabled-veteran assistant mission — a person
describes a task, the agent does the clicking/typing. When it hits a CAPTCHA or
anything needing a human, it stops and returns a `need_human` handoff instead of
trying to defeat it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import Skill

logger = logging.getLogger(__name__)

# JS that tags every visible interactive element and returns structured info.
# (Ported verbatim from JobHunterAI — proven across many real ATS forms.)
_TAG_JS = r"""
() => {
  const out = [];
  let idx = 0;
  const vis = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const labelFor = el => {
    const al = el.getAttribute('aria-label'); if (al) return al.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(' ').map(id => (document.getElementById(id)||{}).innerText || '').join(' ').trim(); if (t) return t; }
    if (el.id) { try { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l && l.innerText.trim()) return l.innerText.trim(); } catch(e){} }
    const wl = el.closest('label'); if (wl && wl.innerText.trim()) return wl.innerText.trim();
    if (el.placeholder) return el.placeholder.trim();
    let p = el.previousElementSibling;
    for (let i=0; p && i<3; i++, p=p.previousElementSibling) { const t=(p.innerText||'').trim(); if (t && t.length<140) return t; }
    const par = el.parentElement;
    if (par) { let pp = par.previousElementSibling; for (let i=0; pp && i<3; i++, pp=pp.previousElementSibling){ const t=(pp.innerText||'').trim(); if (t && t.length<140) return t; } }
    return '';
  };
  const SEL = 'input, textarea, select, button, a[href], [role=combobox], [role=checkbox], [role=radio], [role=button], [role=link], [contenteditable=true]';
  document.querySelectorAll(SEL).forEach(el => {
    if (el.type === 'hidden') return;
    const isFile = el.tagName === 'INPUT' && el.type === 'file';
    if (!isFile && !vis(el)) return;
    idx++;
    const ref = 'L' + idx;
    el.setAttribute('data-ab-ref', ref);
    let role = el.tagName.toLowerCase();
    const ariaRole = el.getAttribute('role');
    if (ariaRole) role = ariaRole;
    if (role === 'input') role = el.type || 'text';
    const info = { ref, role, label: (labelFor(el)||'').slice(0,140), value: (el.value||'').slice(0,80),
                   name: el.name || '', checked: !!el.checked, disabled: !!el.disabled,
                   isFile: isFile, text: (el.innerText||'').trim().slice(0,60) };
    if (el.tagName === 'SELECT') info.options = Array.from(el.options).map(o => (o.text||'').trim()).filter(Boolean).slice(0,50);
    out.push(info);
  });
  return out;
}
"""

MAX_STEPS_DEFAULT = 18

SYSTEM_PROMPT = """You are a web automation agent controlling a real browser to accomplish a task for a user (who may be disabled and cannot do it themselves).

You are given the TASK, the current URL, the visible interactive elements (each with a [ref=...]), and the history of what you've done.

Decide the next step. Respond with ONLY a JSON object, no prose:
{
  "thought": "brief reasoning",
  "actions": [ {"action": "...", "ref": "fXLY", "value": "...", "reason": "..."} ],
  "status": "continue" | "done" | "need_human",
  "message": "result if done, or what the human must do if need_human"
}

Action kinds: navigate (value=URL), fill (value=text), type (value=text, slow), select (value=option text), check, uncheck, click, upload (value=file path).

Rules:
- Use the exact [ref=...] of the element you act on.
- Fill one logical group per step, then re-observe.
- status "done" when the task is fully accomplished; put the outcome in "message".
- status "need_human" ONLY for CAPTCHAs, 2FA, payment, or a genuine judgment call a human must make — never to avoid work. Explain clearly in "message".
- Never invent data. If required info is missing, set status "need_human" and ask for it.
"""


class WebAgentSkill(Skill):
    name = "web_agent"
    description = (
        "Autonomously drive a web browser to accomplish a task: navigate, read pages, "
        "fill forms, choose dropdowns, upload files, click, sign up, submit. Handles "
        "iframes and custom dropdowns. Use for web tasks the user cannot do themselves."
    )
    schema = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Natural-language goal, e.g. 'Sign up at themoviedb.org and get an API key'."},
            "start_url": {"type": "string", "description": "URL to open first."},
            "max_steps": {"type": "integer", "default": MAX_STEPS_DEFAULT},
            "headed": {"type": "boolean", "default": True, "description": "Show the browser window (recommended so a human can help with CAPTCHAs)."},
        },
        "required": ["task"],
    }
    permissions = ["web:automate"]

    def __init__(self) -> None:
        # Wired by Runtime._configure_skills:
        self.llm = None            # the planning brain (runtime LLM provider)
        self.data_dir = str(Path.home() / ".jarvis" / "browser_data")

    def is_available(self) -> tuple[bool, str]:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False, "Playwright not installed. Run: pip install playwright && playwright install chromium"
        if self.llm is None:
            return False, "No planning LLM wired into web_agent."
        return True, "ready"

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        task = kwargs.get("task", "")
        start_url = kwargs.get("start_url")
        max_steps = int(kwargs.get("max_steps", MAX_STEPS_DEFAULT))
        headed = bool(kwargs.get("headed", True))

        ready, msg = self.is_available()
        if not ready:
            return {"success": False, "status": "unavailable", "message": msg}

        from playwright.async_api import async_playwright

        history: list[str] = []
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                self.data_dir, headless=not headed,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                if start_url:
                    await page.goto(start_url, wait_until="domcontentloaded", timeout=45000)

                for step in range(1, max_steps + 1):
                    snapshot, ref_map = await self._snapshot(page)
                    plan = await self._plan(task, page.url, snapshot, history)
                    if plan is None:
                        history.append(f"step {step}: planner returned no valid JSON")
                        continue
                    status = plan.get("status", "continue")
                    if status == "done":
                        return {"success": True, "status": "done", "message": plan.get("message", "Task complete."), "steps": step, "url": page.url}
                    if status == "need_human":
                        return {"success": False, "status": "need_human", "message": plan.get("message", "Human help needed."), "steps": step, "url": page.url}
                    did = await self._execute(plan.get("actions", []), ref_map, page)
                    history.append(f"step {step}: {plan.get('thought','')} -> {[a.get('action') for a in plan.get('actions', [])]}")
                    if did:
                        await page.wait_for_timeout(1200)
                return {"success": False, "status": "max_steps", "message": f"Reached {max_steps} steps without finishing.", "url": page.url}
            finally:
                await context.close()

    # ---- planning (the brain) ----
    async def _plan(self, task, url, snapshot, history) -> dict | None:
        user = (
            f"TASK: {task}\n\nCURRENT URL: {url}\n\n"
            f"PAGE ELEMENTS:\n{snapshot or '(none)'}\n\n"
            f"HISTORY:\n" + ("\n".join(history[-8:]) or "(nothing yet)")
        )
        try:
            resp = await self.llm.chat([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ])
            content = resp.get("content", "")
        except Exception as exc:  # noqa: BLE001
            logger.error("web_agent planner LLM failed: %s", exc)
            return None
        return _extract_json(content)

    # ---- page reading (ported) ----
    async def _snapshot(self, page) -> tuple[str, dict]:
        lines, ref_map = [], {}
        for fi, frame in enumerate(page.frames):
            try:
                items = await frame.evaluate(_TAG_JS)
            except Exception:
                continue
            if not items:
                continue
            if fi > 0:
                lines.append(f"--- frame {fi} ({(frame.url or '')[:60]}) ---")
            for it in items:
                gref = f"f{fi}{it['ref']}"
                ref_map[gref] = (frame, it["ref"])
                label = it.get("label") or it.get("text") or ""
                extra = ""
                if it.get("value"):
                    extra += f' value="{it["value"]}"'
                if it.get("checked"):
                    extra += " [checked]"
                if it.get("disabled"):
                    extra += " [disabled]"
                if it.get("isFile"):
                    extra += " [file-input]"
                if it.get("options"):
                    extra += " options=" + str(it["options"])
                lines.append(f'- {it["role"]} "{label}" [ref={gref}]{extra}')
        text = "\n".join(lines)
        if len(text) > 24000:
            text = text[:24000] + "\n... [truncated]"
        return text, ref_map

    def _loc(self, ref_map, ref):
        if ref not in ref_map:
            return None
        frame, local = ref_map[ref]
        return frame.locator(f'[data-ab-ref="{local}"]')

    # ---- action execution (ported + generalized) ----
    async def _execute(self, actions, ref_map, page) -> bool:
        did = False
        for a in actions:
            kind = (a.get("action") or "").lower()
            ref = a.get("ref", "")
            val = a.get("value", "")
            if kind == "navigate":
                if val:
                    try:
                        await page.goto(str(val), wait_until="domcontentloaded", timeout=45000)
                        did = True
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("web_agent navigate failed: %s", exc)
                continue
            loc = self._loc(ref_map, ref)
            if loc is None:
                continue
            try:
                if kind == "fill":
                    await loc.fill("")
                    await loc.fill(str(val))
                    did = True
                elif kind == "type":
                    await loc.click()
                    await loc.type(str(val), delay=25)
                    did = True
                elif kind == "select":
                    if await self._select_any(loc, str(val)):
                        did = True
                elif kind == "check":
                    await loc.check(); did = True
                elif kind == "uncheck":
                    await loc.uncheck(); did = True
                elif kind == "click":
                    await loc.click(); did = True
                    await loc.page.wait_for_timeout(800)
                elif kind == "upload":
                    if val and Path(val).exists():
                        await loc.set_input_files(val); did = True
            except Exception as exc:  # noqa: BLE001
                logger.debug("web_agent %s %s failed: %s", kind, ref, exc)
                continue
        return did

    async def _select_any(self, loc, value: str) -> bool:
        try:
            tag = await loc.evaluate("e => e.tagName")
            if tag == "SELECT":
                try:
                    await loc.select_option(label=value); return True
                except Exception:
                    await loc.select_option(value=value); return True
        except Exception:
            pass
        try:
            await loc.click()
            await loc.page.wait_for_timeout(400)
        except Exception:
            return False
        page = loc.page
        for frame in (page.frames if page else []):
            for sel in (f'[role=option]:has-text("{value}")', f'li:has-text("{value}")', f'div[role=option]:has-text("{value}")'):
                try:
                    opt = frame.locator(sel).first
                    if await opt.count() and await opt.is_visible():
                        await opt.click(); return True
                except Exception:
                    continue
        return False


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of an LLM response."""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
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
                    return None
    return None
