"""Offline text-to-speech through the espeak-ng command line tool.

espeak-ng is a formant synthesiser: robotic, but free (GPL-3.0), offline,
deterministic for a given version, and it has a Hindi voice that switches to
English pronunciation for Latin-script words, which suits code-switched text.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from voicebench.audio.signal import SAMPLE_RATE, read_wav

# Scenario language -> espeak-ng voice. hi-en uses the Hindi voice: espeak-ng
# reads Devanagari with Hindi rules and Latin words with English rules.
CALLER_VOICES = {"en": "en-us", "hi": "hi", "hi-en": "hi"}
# Agent prompts (barge-in) use a different voice variant so the two speakers differ.
AGENT_VARIANT = "+f3"


class TTSUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class EspeakTTS:
    binary: str = "espeak-ng"
    words_per_minute: int = 160

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def version(self) -> str:
        out = self._run(["--version"]).stdout
        m = re.search(r"eSpeak NG text-to-speech:\s*([\w.+~-]+)", out)
        return f"espeak-ng {m.group(1)}" if m else out.strip()

    def voice_for(self, language: str, agent: bool = False) -> str:
        try:
            voice = CALLER_VOICES[language]
        except KeyError:
            raise ValueError(f"no voice configured for language {language!r}") from None
        return voice + AGENT_VARIANT if agent else voice

    def synthesize(self, text: str, voice: str) -> np.ndarray:
        """Return mono float32 audio at 16 kHz."""
        if not text.strip():
            raise ValueError("text is empty")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "tts.wav"
            self._run(["-v", voice, "-s", str(self.words_per_minute), "-w", str(out), text])
            audio = read_wav(out, SAMPLE_RATE)
        if not np.any(audio):
            raise RuntimeError(f"espeak-ng produced silence for voice {voice!r}")
        return audio

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        if not self.available():
            raise TTSUnavailable(
                f"{self.binary} not found; install it (e.g. `sudo apt-get install espeak-ng`)"
            )
        return subprocess.run([self.binary, *args], check=True, capture_output=True, text=True)
