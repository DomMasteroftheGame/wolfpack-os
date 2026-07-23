"""Copilot progress store — game progress kept on the user's machine.

Everything the copilot observes/says is appended to data/copilot/progress.jsonl;
data/copilot/latest.json holds the current summary (where the player is, IVP,
last nudge) so later iterations can resume coaching from disk.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STORE_DIR = Path(__file__).resolve().parents[2] / "data" / "copilot"
PROGRESS_LOG = STORE_DIR / "progress.jsonl"
LATEST = STORE_DIR / "latest.json"


def _ensure_dir() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)


def log_event(kind: str, payload: dict[str, Any]) -> None:
    """Append one event (observation | nudge | chat | action) to the jsonl log."""
    _ensure_dir()
    record = {"ts": int(time.time() * 1000), "kind": kind, **payload}
    with PROGRESS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_latest(**fields: Any) -> None:
    """Merge fields into the latest-state summary."""
    _ensure_dir()
    state: dict[str, Any] = {}
    if LATEST.exists():
        try:
            state = json.loads(LATEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    state.update(fields)
    state["updated_at"] = int(time.time() * 1000)
    LATEST.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def read_latest() -> dict[str, Any]:
    if LATEST.exists():
        try:
            return json.loads(LATEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}
