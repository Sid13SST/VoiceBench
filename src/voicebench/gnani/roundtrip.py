"""TTS + STT round trip: Timbre speaks a scenario's reference, Prisma transcribes it.

The round-trip transcript is scored against the original reference with
the normal scoring (``voicebench.scoring.score``: WER, plus intent and
slots with the built-in matcher), through ``runner.run()``. So the result
measures both services together: a word lost can be Timbre's or Prisma's,
and the run cannot say which.

The synthesized WAVs are written to a git-ignored cache directory and
never committed; an audio manifest with each file's sha256 is written
next to the run file.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Optional

import soundfile as sf

from voicebench.asr import Transcript
from voicebench.gnani.budget import Budget
from voicebench.gnani.client import BASE_URL, STT_PATH, TTS_PATH, GnaniClient
from voicebench.gnani import COST_NOTE
from voicebench.gnani.transcriber import (
    CODE_SWITCHED,
    GnaniPrismaTranscriber,
    call_gnani,
    external_api_block,
)
from voicebench.schema import Scenario

DEFAULT_TTS_MODEL = "timbre-v2.5"
# timbre-v2.5 voices by the language group the Gnani voice catalog lists
# them under (Hindi, English, Hinglish). Change with --voice-en/-hi/-hi-en.
DEFAULT_VOICES = {"en": "Kaveri", "hi": "Nalini", "hi-en": "Poorvi"}
TTS_LANGUAGES = {"en": "en-IN", "hi": "hi-IN", "hi-en": "hi-IN"}
# STT language_code per scenario language. The scenario's language is
# known here, so hi-en gets the two-language hint (prisma-v3.0 only).
STT_LANGUAGES = {"en": "en-IN", "hi": "hi-IN", "hi-en": CODE_SWITCHED}
DEFAULT_CACHE_DIR = ".cache/gnani/roundtrip"
SAMPLE_RATE = 16000


class GnaniRoundTripTranscriber:
    """``transcribe_scenario`` = synthesize the reference with Timbre, then transcribe that audio with Prisma."""

    def __init__(
        self,
        client: GnaniClient,
        budget: Budget,
        cache_dir: str | Path,
        tts_model: str = DEFAULT_TTS_MODEL,
        voices: Optional[dict[str, str]] = None,
        speed: float = 1.0,
        stt_model: str = "prisma-v3.0",
        stt_format: str = "verbatim",
        stt_languages: Optional[dict[str, str]] = None,
    ):
        self.client = client
        self.budget = budget
        self.cache_dir = Path(cache_dir)
        self.tts_model = tts_model
        self.voices = {**DEFAULT_VOICES, **(voices or {})}
        self.speed = speed
        self.stt_languages = {**STT_LANGUAGES, **(stt_languages or {})}
        # The per-scenario language_code is always passed explicitly (stt_languages); the
        # transcriber's own "auto" code is never used here.
        self.stt = GnaniPrismaTranscriber(client, budget, model=stt_model, format=stt_format,
                                          auto_language_code=CODE_SWITCHED if stt_model == "prisma-v3.0" else "hi-IN")
        for lang, code in self.stt_languages.items():  # fail before any TTS credit is spent
            if "," in code and stt_model != "prisma-v3.0":
                raise ValueError(f"STT language_code {code!r} for {lang} needs prisma-v3.0, not {stt_model}")
        self.name = f"gnani-roundtrip-{tts_model}-{stt_model}"
        self.files: list[dict[str, Any]] = []

    cost_note = COST_NOTE

    def describe(self) -> dict[str, Any]:
        stt = self.stt.describe()
        return {
            "name": self.name,
            "lane": "tts-stt-roundtrip",
            "measures": "Timbre TTS and Prisma STT together; errors cannot be attributed to either one",
            "backend": "gnani-rest-tts+stt",
            "backend_version": f"{self.tts_model}+{self.stt.model}",
            "device": "cloud",
            "tts": {"model": self.tts_model, "voices": self.voices, "languages": TTS_LANGUAGES,
                    "speed": self.speed, "sample_rate": SAMPLE_RATE},
            "stt": {"model": self.stt.model, "format": self.stt.format, "language_codes": self.stt_languages,
                    "models_reported_by_api": stt["models_reported_by_api"]},
            "external_api": external_api_block(self.budget, self.client,
                                               [BASE_URL + TTS_PATH, BASE_URL + STT_PATH]),
        }

    def synthesize(self, s: Scenario) -> tuple[bytes, float]:
        lang = s.language.value
        entry = self.budget.reserve("tts", s.id)
        entry.update({"model": self.tts_model, "voice": self.voices[lang], "language": TTS_LANGUAGES[lang]})
        self.budget.tts_characters += len(s.reference)
        reply = call_gnani(self.budget, entry, self.client.synthesize, s.reference, model=self.tts_model,
                           voice=self.voices[lang], language=TTS_LANGUAGES[lang], speed=self.speed,
                           sample_rate=SAMPLE_RATE)
        audio = reply.content
        info = sf.info(io.BytesIO(audio))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{s.id}.wav"
        path.write_bytes(audio)
        self.files.append({
            "scenario_id": s.id,
            "path": path.as_posix(),
            "sha256": hashlib.sha256(audio).hexdigest(),
            "bytes": len(audio),
            "duration_s": round(info.duration, 3),
            "sample_rate": info.samplerate,
            "channels": info.channels,
            "language": lang,
            "voice": self.voices[lang],
            "text": s.reference,
        })
        return audio, info.duration

    def transcribe_scenario(self, s: Scenario) -> Transcript:
        audio, duration_s = self.synthesize(s)
        # The scenario language is known here, so its code is sent directly.
        return self.stt.transcribe_bytes(audio, f"{s.id}.wav", duration_s, s.language.value, s.id,
                                         language_code=self.stt_languages[s.language.value])

    def audio_manifest(self, run_id: str) -> dict[str, Any]:
        return {
            "kind": "gnani-roundtrip-audio",
            "run_id": run_id,
            "note": "Audio synthesized by the Gnani Timbre API. The WAVs stay in the git-ignored cache and are "
                    "not committed; the sha256 values identify them. A re-synthesis need not be byte-identical.",
            "tts": {"model": self.tts_model, "voices": self.voices, "languages": TTS_LANGUAGES,
                    "speed": self.speed, "sample_rate": SAMPLE_RATE},
            "files": self.files,
        }
