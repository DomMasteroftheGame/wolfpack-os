"""Voice interface for Jarvis OS.

Install voice extras:
    pip install -e '.[voice]'

Linux users also need the PortAudio system library so PyAudio can build/use
its audio backend:
    sudo apt install portaudio19-dev python3-dev  # Debian/Ubuntu
    # then reinstall the voice extras:
    pip install --force-reinstall -e '.[voice]'
"""

import asyncio
import logging
import sys
from typing import Any

from jarvis_os.core.runtime import Runtime

logger = logging.getLogger(__name__)


class VoiceInterface:
    """Speech-to-text / text-to-speech interface."""

    def __init__(self, runtime: Runtime, wake_word: str | None = None):
        self.runtime = runtime
        # The voice agent speaks AS the configured persona. With selected_persona:
        # ceo the runtime is Alpha (Pack Leader) — the single voice the user talks to;
        # Alpha decides who does what and delegates via [DELEGATE:agentId].
        self.name = getattr(runtime.config.personality, "name", None) or "Alpha"
        # Address it by name ("Alpha, …") — defaults to the persona name.
        self.wake_word = (wake_word or self.name).lower() if (wake_word or self.name) else None

        # Lazy imports so the module can be parsed without voice extras installed.
        import speech_recognition as sr  # noqa: PLC0415
        import pyttsx3  # noqa: PLC0415

        self._sr = sr
        self._pyttsx3 = pyttsx3
        self.recognizer = sr.Recognizer()
        try:
            self.microphone = sr.Microphone()
        except (AttributeError, ModuleNotFoundError) as exc:
            self._die(
                "Voice requires PyAudio, which is missing or could not initialize.\n"
                "Install PortAudio system headers and the voice extras:\n"
                "  sudo apt install portaudio19-dev python3-dev\n"
                "  pip install --force-reinstall -e '.[voice]'\n"
                f"Original error: {exc}"
            )
        self.tts_engine = pyttsx3.init()

    def _die(self, message: str) -> None:
        """Print a clear fatal error and exit so the launcher doesn't dump a stack trace."""
        print(f"\n[Voice] {message}\n", file=sys.stderr)
        logger.error(message)
        raise SystemExit(1)

    async def run(self) -> None:
        self._speak(f"{self.name} online. I lead the pack — tell me what you need and I'll route it.")
        while True:
            print("Listening...")
            command = await self._listen()
            if command is None:
                self._speak("I didn't catch that.")
                continue

            text = command.lower().strip()
            logger.info("Heard: %s", text)

            if text in {"exit", "quit", "stop"}:
                self._speak("Goodbye.")
                break

            if self.wake_word and self.wake_word not in text:
                logger.info("Wake word '%s' not detected; ignoring.", self.wake_word)
                continue

            try:
                result = await self.runtime.handle(command)
            except Exception:  # noqa: BLE001
                logger.exception("Runtime failed to handle command")
                self._speak("Sorry, I ran into an error processing that.")
                continue

            summary = result.get("summary", "Done.")
            self._speak(summary)

        self.runtime.shutdown()

    async def _listen(self) -> str | None:
        """Capture and transcribe a single utterance."""

        def _capture() -> Any:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                return self.recognizer.listen(source)

        try:
            audio = await asyncio.to_thread(_capture)
            print("Processing speech...")
            text = await asyncio.to_thread(
                self.recognizer.recognize_google,
                audio,
            )
            return str(text)
        except self._sr.UnknownValueError:
            return None
        except self._sr.RequestError as exc:
            logger.error("Speech recognition request failed: %s", exc)
            return None

    def _speak(self, text: str) -> None:
        """Speak the given text."""
        print(f"{self.name}: {text}")
        self.tts_engine.say(text)
        self.tts_engine.runAndWait()
