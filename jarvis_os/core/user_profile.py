"""Operator/business profile written by the first-run onboarding wizard.

The GUI wizard (interfaces/gui/static/onboarding.html) collects who the operator
is and what their business does, then persists it as ``user_profile.yaml`` in the
config directory. The file's presence doubles as the first-run flag: while it is
missing the GUI serves the wizard instead of the dashboard.

The config directory defaults to ``./config`` and is overridable with the
``WOLFPACK_CONFIG_DIR`` env var so tests and tooling never touch a live pack
config.

Consumed by ``Runtime.persona_message()`` (core/runtime.py), which folds
``business_summary()`` into the agent system prompt so every wolf answers in
the context of the operator's business.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROFILE_FILENAME = "user_profile.yaml"


def default_config_dir() -> Path:
    """Config directory; ``WOLFPACK_CONFIG_DIR`` wins, else ./config."""
    return Path(os.environ.get("WOLFPACK_CONFIG_DIR", "config"))


def load_user_profile(config_dir: str | Path | None = None) -> dict[str, Any] | None:
    """Load the operator profile, or None when the wizard has not been completed."""
    directory = Path(config_dir) if config_dir is not None else default_config_dir()
    path = directory / PROFILE_FILENAME
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def business_summary(profile: dict[str, Any] | None) -> str:
    """Render the profile as a short system-prompt paragraph ('' when absent)."""
    if not profile:
        return ""
    operator = profile.get("operator") or {}
    business = profile.get("business") or {}
    lines: list[str] = []
    name = str(operator.get("name") or "").strip()
    if name:
        tz = str(operator.get("timezone") or "").strip()
        lines.append(f"The operator is {name}" + (f" (timezone {tz})" if tz else "") + ".")
    sells = str(business.get("sells") or "").strip()
    if sells:
        lines.append(f"Their business sells: {sells}.")
    customer = str(business.get("customer") or "").strip()
    if customer:
        lines.append(f"Target customer: {customer}.")
    prices = str(business.get("prices") or "").strip()
    if prices:
        lines.append(f"Prices/offers: {prices}.")
    goal = str(business.get("goal") or "").strip()
    if goal:
        lines.append(f"Their current #1 goal: {goal}.")
    if not lines:
        return ""
    return "Operator business profile (keep answers relevant to it):\n" + "\n".join(lines)
