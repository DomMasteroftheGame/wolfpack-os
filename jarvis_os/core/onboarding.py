"""Onboarding wizard — get a new pack set up with the accounts their startup needs.

Walks the user through the necessary logins (federal + their state) and social
presence, auto-follows BuildYourWolfpack, and sets the homepage. Each login is the
CDP model: the OS opens the page, the human signs in once, the wizard marks it done
and moves on. Location-aware: the Secretary of State step resolves to the user's state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

HOMEPAGE = "https://www.buildyourwolfpack.com"


@dataclass
class OnboardingStep:
    id: str
    name: str
    url: str
    why: str
    category: str = "gov"          # gov | social | setting
    login_required: bool = True
    action: str | None = None      # e.g. "follow" for socials, "set_homepage"


# Federal / national — every founder, any state.
FEDERAL_STEPS = [
    OnboardingStep("sba", "SBA (Small Business Administration)", "https://www.sba.gov/",
                   "Funding, SBA loans, and certifications (8(a), WOSB, HUBZone)."),
    OnboardingStep("sam", "SAM.gov", "https://sam.gov/",
                   "System for Award Management — required to bid on federal contracts; get a UEI."),
    OnboardingStep("irs_ein", "IRS EIN", "https://www.irs.gov/businesses/small-businesses-self-employed/apply-for-an-employer-identification-number-ein-online",
                   "Federal Employer ID Number for the entity."),
]

# Secretary of State business registration (LLC/entity) by USPS state code.
SECRETARY_OF_STATE = {
    "GA": ("Georgia SoS — eCorp", "https://ecorp.sos.ga.gov/"),
    "CA": ("California SoS — bizfile", "https://bizfileonline.sos.ca.gov/"),
    "TX": ("Texas SoS — SOSDirect", "https://www.sos.state.tx.us/corp/sosda/"),
    "FL": ("Florida — Sunbiz", "https://dos.myflorida.com/sunbiz/"),
    "NY": ("New York DOS", "https://dos.ny.gov/corporations"),
    "DE": ("Delaware Division of Corporations", "https://corp.delaware.gov/"),
    "NC": ("North Carolina SoS", "https://www.sosnc.gov/"),
    "SC": ("South Carolina SoS", "https://sos.sc.gov/"),
    "VA": ("Virginia SCC", "https://cis.scc.virginia.gov/"),
    "WA": ("Washington SoS — CCFS", "https://ccfs.sos.wa.gov/"),
    "IL": ("Illinois SoS", "https://www.ilsos.gov/departments/business_services/home.html"),
    "OH": ("Ohio SoS", "https://www.ohiosos.gov/businesses/"),
    "PA": ("Pennsylvania DOS", "https://www.pa.gov/agencies/dos/programs/business-charities.html"),
    "MI": ("Michigan LARA", "https://www.michigan.gov/lara/bureau-list/cscl"),
    "AZ": ("Arizona Corporation Commission", "https://ecorp.azcc.gov/"),
}


def secretary_of_state_step(state_code: str | None) -> OnboardingStep:
    code = (state_code or "").upper()
    if code in SECRETARY_OF_STATE:
        name, url = SECRETARY_OF_STATE[code]
        return OnboardingStep(f"sos_{code.lower()}", name, url,
                              f"Register your business entity with the {code} Secretary of State.")
    # Unknown/unset state -> a resolver search so the wizard still helps.
    q = f"{code + ' ' if code else ''}secretary of state business registration"
    return OnboardingStep("sos", "Secretary of State (your state)",
                          "https://www.google.com/search?q=" + q.replace(" ", "+"),
                          "Register your business entity with YOUR state's Secretary of State.")


# Default social platforms to log in + auto-follow BuildYourWolfpack on.
# `url` is the platform's BuildYourWolfpack profile (override in config with real handles).
DEFAULT_SOCIALS = [
    OnboardingStep("ig", "Instagram", "https://www.instagram.com/", "Follow @buildyourwolfpack.",
                   category="social", action="follow"),
    OnboardingStep("x", "X (Twitter)", "https://x.com/", "Follow @buildyourwolfpack.",
                   category="social", action="follow"),
    OnboardingStep("li", "LinkedIn", "https://www.linkedin.com/", "Follow BuildYourWolfpack.",
                   category="social", action="follow"),
    OnboardingStep("yt", "YouTube", "https://www.youtube.com/", "Subscribe to BuildYourWolfpack.",
                   category="social", action="follow"),
    OnboardingStep("tt", "TikTok", "https://www.tiktok.com/", "Follow @buildyourwolfpack.",
                   category="social", action="follow"),
    OnboardingStep("fb", "Facebook", "https://www.facebook.com/", "Follow BuildYourWolfpack.",
                   category="social", action="follow"),
]


def set_chrome_homepage(url: str = HOMEPAGE) -> list[str]:
    """Best-effort: set the browser homepage + startup page via Chromium/Chrome managed
    policy. Returns the policy files written. Needs write access to the policy dirs
    (root on Linux); fails soft per-path so it works where it can."""
    policy = {
        "HomepageLocation": url,
        "ShowHomeButton": True,
        "RestoreOnStartup": 4,
        "RestoreOnStartupURLs": [url],
    }
    written: list[str] = []
    for d in ("/etc/chromium/policies/managed", "/etc/opt/chrome/policies/managed",
              "/etc/chromium-browser/policies/managed"):
        try:
            p = Path(d)
            p.mkdir(parents=True, exist_ok=True)
            (p / "wolfpack-homepage.json").write_text(json.dumps(policy, indent=2), encoding="utf-8")
            written.append(str(p / "wolfpack-homepage.json"))
        except OSError:
            continue
    return written


class OnboardingWizard:
    def __init__(self, state_code: str | None = None, socials: list[OnboardingStep] | None = None,
                 homepage: str = HOMEPAGE, state_path: str | Path = ".wolfpack-state/onboarding.json"):
        self.state_code = state_code
        self.socials = socials if socials is not None else DEFAULT_SOCIALS
        self.homepage = homepage
        self.state_path = Path(state_path)

    def steps(self) -> list[OnboardingStep]:
        steps: list[OnboardingStep] = list(FEDERAL_STEPS)
        steps.append(secretary_of_state_step(self.state_code))
        steps.extend(self.socials)
        steps.append(OnboardingStep(
            "homepage", "Default homepage", self.homepage,
            "Set BuildYourWolfpack as the browser homepage.",
            category="setting", login_required=False, action="set_homepage"))
        return steps

    # ── progress persistence ────────────────────────────────────────────────
    def _load(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def mark_done(self, step_id: str) -> None:
        done = self._load()
        done[step_id] = True
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(done, indent=2), encoding="utf-8")

    def is_done(self, step_id: str) -> bool:
        return bool(self._load().get(step_id))

    def remaining(self) -> list[OnboardingStep]:
        return [s for s in self.steps() if not self.is_done(s.id)]

    # ── run loop ────────────────────────────────────────────────────────────
    async def run(self, open_url, notify, follow=None, set_homepage=None, confirm=None) -> None:
        """Walk the remaining steps.

        open_url(url)      -> open a page (agent-browser / kiosk)
        notify(msg)        -> tell the user what to do (Alpha's voice)
        follow(step)       -> auto-follow BuildYourWolfpack on a logged-in social (optional)
        set_homepage(url)  -> persist the browser homepage (optional)
        confirm(step)      -> await the human's "done" before advancing (optional; default auto)
        """
        for step in self.remaining():
            await notify(f"{step.name}: {step.why}")
            if step.action == "set_homepage" and set_homepage:
                await set_homepage(self.homepage)
                self.mark_done(step.id)
                continue
            await open_url(step.url)
            if step.login_required:
                await notify(f"Sign into {step.name} in the window, then say 'done'.")
                if confirm:
                    await confirm(step)
            if step.action == "follow" and follow:
                await follow(step)
            self.mark_done(step.id)
        await notify("Onboarding complete — your pack is set up.")
