#!/usr/bin/env python
"""WolfPack hands-free voice listener.

Vosk (cheap, always-on) detects the wake word "alpha". The utterance audio is
then re-transcribed with faster-whisper (accurate) to get the actual command,
which is sent to /api/voice for a fast spoken reply. The mic is stopped while
WolfPack replies so it never transcribes its own voice.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave

sys.path.insert(0, "/opt/jarvis-os")

from vosk import KaldiRecognizer, Model  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402
from jarvis_os.core import voice as tts  # noqa: E402

VOSK_DIR = os.environ.get("WOLFPACK_VOSK_MODEL", "/opt/jarvis-os/data/vosk-en")
WHISPER = os.environ.get("WOLFPACK_WHISPER", "base.en")
WAKE = os.environ.get("WOLFPACK_WAKE", "alpha").lower()
VOICE_URL = os.environ.get("WOLFPACK_VOICE_URL", "http://127.0.0.1:8080/api/voice?say=0")
RATE = 16000
CHUNK = 4000


def _wake_aliases() -> set[str]:
    """Common speech-to-text misspellings of the wake word."""
    aliases = {WAKE}
    if WAKE == "alpha":
        aliases |= {"alfa", "alva"}
    return aliases


def _extract_command(wtext: str) -> str:
    """Strip the wake phrase ('Alpha' / 'okay Alpha') and return the command."""
    aliases = _wake_aliases()
    # Direct prefix: "alpha, what's up"
    first = wtext.split(" ")[0].strip(" ,.!?")
    if first in aliases:
        return wtext[len(first):].strip(" ,.!?")
    # Contained wake word: "okay alpha what's up"
    for alias in sorted(aliases, key=len, reverse=True):
        if alias in wtext:
            return wtext.split(alias, 1)[1].strip(" ,.!?")
    return ""


def _mic() -> subprocess.Popen:
    return subprocess.Popen(
        ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"],
        stdout=subprocess.PIPE,
    )


def _ask(cmd: str) -> str:
    body = json.dumps({"goal": cmd, "agent": "simple"}).encode("utf-8")
    req = urllib.request.Request(VOICE_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("summary") or data.get("answer") or "Done."
    except Exception:  # noqa: BLE001
        return "Sorry, I ran into a problem reaching my brain."


def _whisper_text(whisper: WhisperModel, audio: bytes) -> str:
    if len(audio) < RATE:  # under ~0.5s of audio, skip
        return ""
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        w = wave.open(path, "wb")
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(audio); w.close()
        segs, _ = whisper.transcribe(path, language="en", beam_size=1)
        return " ".join(s.text for s in segs).strip()
    except Exception:  # noqa: BLE001
        return ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def main() -> None:
    vmodel = Model(VOSK_DIR)
    rec = KaldiRecognizer(vmodel, RATE)
    whisper = WhisperModel(WHISPER, device="cpu", compute_type="int8")

    tts.speak_blocking(f"Wolf Pack O S online. Say {WAKE}, then your request.")
    mic = _mic()  # start AFTER announcing so it doesn't hear itself
    buf = bytearray()
    awaiting = False

    while True:
        chunk = mic.stdout.read(CHUNK)
        if not chunk:
            time.sleep(0.1)
            continue
        buf += chunk
        if len(buf) > RATE * 2 * 25:  # keep last ~12s if someone rambles
            buf = bytearray(buf[-RATE * 2 * 12:])
        if not rec.AcceptWaveform(chunk):
            continue

        vtext = json.loads(rec.Result()).get("text", "").strip()
        utt = bytes(buf)
        buf = bytearray()
        if not vtext:  # Vosk found no speech in this utterance -> just silence
            continue
        # Accurate transcription of EVERY utterance via Whisper; used for wake + command.
        wtext = _whisper_text(whisper, utt).lower().strip(" ,.!?")
        if not wtext:
            continue

        cmd = ""
        aliases = _wake_aliases()
        is_wake = wtext.split(" ")[0] in aliases or any(a in wtext for a in aliases)
        if awaiting:
            awaiting = False
            cmd = wtext
        elif is_wake:
            print(f"[wake] {wtext}", flush=True)
            cmd = _extract_command(wtext)
            if not cmd:  # bare wake word -> acknowledge, then capture the next utterance
                mic.terminate(); mic.wait()
                tts.speak_blocking("Yes?")
                mic = _mic(); rec = KaldiRecognizer(vmodel, RATE); buf = bytearray()
                awaiting = True
                continue
        else:
            print(f"[skip] {wtext}", flush=True)
            continue

        if not cmd:
            continue
        print(f"[command] {cmd}", flush=True)
        mic.terminate(); mic.wait()             # stop listening while replying
        reply = _ask(cmd)
        tts.speak_blocking(reply)
        mic = _mic(); rec = KaldiRecognizer(vmodel, RATE); buf = bytearray()


if __name__ == "__main__":
    main()
