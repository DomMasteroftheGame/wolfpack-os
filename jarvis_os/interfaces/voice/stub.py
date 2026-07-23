"""Voice interface placeholder.

Install voice extras:
    pip install -e '.[voice]'

Then implement wake-word detection, STT, and TTS here.
"""

from jarvis_os.core.runtime import Runtime


class VoiceInterface:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime

    async def run(self) -> None:
        raise NotImplementedError("Voice interface not implemented yet.")
