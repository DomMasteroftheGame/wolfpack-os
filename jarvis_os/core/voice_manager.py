"""Manage the Alpha hands-free voice listener process and settings.

The manager lives on Runtime so the web GUI can start/stop the listener and
update voice settings (wake word, persona, output) without restarting the hub.
Settings are persisted to .wolfpack-state/voice.json so a restarted listener
picks up where it left off.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_FILE = ".wolfpack-state/voice.json"

DEFAULTS = {
    "enabled": True,
    "output_enabled": True,
    "always_listening": False,
    "persona_id": "ceo",
    "wake_word": "Alpha",
    "model": "vosk",
}


class VoiceManager:
    """Start/stop the voice listener and persist voice settings."""

    def __init__(
        self,
        runtime_dir: Path | str,
        voice_url: str = "http://127.0.0.1:8080/api/voice?say=0",
        defaults: dict[str, Any] | None = None,
    ):
        self.runtime_dir = Path(runtime_dir)
        self.state_path = self.runtime_dir / STATE_FILE
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._defaults = {**DEFAULTS, **(defaults or {})}
        self._state = self._load_state()
        self._proc: subprocess.Popen | None = None
        self._voice_url = voice_url

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return {**self._defaults, **json.load(f)}
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load voice state: %s", exc)
        return dict(self._defaults)

    def _save_state(self) -> None:
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save voice state: %s", exc)

    @property
    def settings(self) -> dict[str, Any]:
        return dict(self._state)

    def update(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Merge new settings and persist them."""
        for key in self._defaults:
            if key in settings:
                self._state[key] = settings[key]
        self._save_state()
        return dict(self._state)

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> dict[str, Any]:
        """Start the voice listener subprocess if it is installed."""
        if self.is_running():
            return {"status": "already_running"}

        listener = Path(__file__).resolve().parent / "voice_listener.py"
        if not listener.exists():
            return {"status": "error", "message": "voice_listener.py not found"}

        env = dict(os.environ)
        env["WOLFPACK_VOICE_URL"] = self._voice_url
        env["WOLFPACK_WAKE"] = (self._state.get("wake_word") or "Alpha").lower()
        env["WOLFPACK_VOICE"] = "1" if self._state.get("output_enabled", True) else "0"

        try:
            self._proc = subprocess.Popen(
                [sys.executable, str(listener)],
                cwd=self.runtime_dir,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("Voice listener started (pid=%s)", self._proc.pid)
            return {"status": "started", "pid": self._proc.pid}
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to start voice listener: %s", exc)
            return {"status": "error", "message": str(exc)}

    def stop(self) -> dict[str, Any]:
        """Stop the voice listener subprocess."""
        if not self.is_running():
            return {"status": "not_running"}
        try:
            self._proc.terminate()  # type: ignore[union-attr]
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()  # type: ignore[union-attr]
            self._proc.wait(timeout=2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error stopping voice listener: %s", exc)
        self._proc = None
        logger.info("Voice listener stopped")
        return {"status": "stopped"}

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()
