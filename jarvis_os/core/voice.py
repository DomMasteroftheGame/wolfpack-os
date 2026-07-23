"""Voice output — speak text aloud via Piper neural TTS through ALSA.

Non-blocking: synthesis + playback run in a background thread so the web
response returns immediately. No-op if Piper or the voice model is missing
(so it stays safe on nodes without a speaker / without Piper installed).
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading

logger = logging.getLogger(__name__)

PIPER_DIR = os.environ.get("WOLFPACK_PIPER_DIR", "/opt/jarvis-os/data/piper")
DEFAULT_VOICE_MODEL = "/opt/jarvis-os/data/voices/en_US-lessac-medium.onnx"
ALSA_DEVICE = os.environ.get("WOLFPACK_ALSA_DEVICE", "default")
ENABLED = os.environ.get("WOLFPACK_VOICE", "1") not in ("0", "false", "off", "")

_piper_bin = os.path.join(PIPER_DIR, "piper")


def voice_model() -> str:
    """Resolve the piper voice model path per call so voice changes apply live."""
    return os.environ.get("WOLFPACK_VOICE_MODEL", DEFAULT_VOICE_MODEL)


def available() -> bool:
    return ENABLED and os.path.isfile(_piper_bin) and os.path.isfile(voice_model())


def _run(text: str) -> None:
    wav = ""
    try:
        fd, wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        env = dict(os.environ, LD_LIBRARY_PATH=PIPER_DIR)
        subprocess.run(
            [_piper_bin, "-m", voice_model(), "-f", wav],
            input=text.encode("utf-8"), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90,
        )
        subprocess.run(
            ["aplay", "-q", "-D", ALSA_DEVICE, wav],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("voice.speak failed: %s", exc)
    finally:
        if wav:
            try:
                os.unlink(wav)
            except OSError:
                pass


def _prep(text: str) -> str:
    t = " ".join(text.split())
    if len(t) > 700:  # keep spoken replies reasonable
        head = t[:700]
        t = head.rsplit(".", 1)[0] + "." if "." in head else head
    return t


def speak(text: str, blocking: bool = False) -> None:
    """Speak text aloud. Fire-and-forget by default; blocking waits for playback.
    Safe no-op if voice isn't available."""
    if not text or not available():
        return
    t = _prep(text)
    if blocking:
        _run(t)
    else:
        threading.Thread(target=_run, args=(t,), daemon=True).start()


def speak_blocking(text: str) -> None:
    """Speak and wait until playback finishes (used by the voice listener)."""
    speak(text, blocking=True)
