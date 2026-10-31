"""Gnani Prisma as a VoiceBench transcriber (the hook in docs/ADAPTERS.md).

``runner.run()`` and ``realspeech.run_realspeech()`` call
``transcribe_file(path, language)`` with ``language`` either None (policy
``auto``) or a Whisper code (policy ``hint``: ``"en"`` or ``"hi"``; the
runner already sends code-switched ``hi-en`` scenarios as ``"hi"``).
Prisma needs a ``language_code`` on every request, so:

======================  =====================================================
VoiceBench language     Prisma ``language_code``
======================  =====================================================
``"en"``                ``"en-IN"``
``"hi"``                ``"hi-IN"``
None (policy ``auto``)  ``"hi-IN,en-IN"`` with ``prisma-v3.0`` (a hint that
                        the speech is Hindi, English or both, not a lock);
                        refused with ``prisma-v2.5``, which takes one code
======================  =====================================================

``detected_language`` is Prisma's ``detected_language_code`` (prisma-v3.0
only) cut to its language part (``"hi-IN"`` -> ``"hi"``), so it compares
with Whisper's codes; without it, it is None.

Latency is measured on this machine around the whole HTTP exchange
(upload, queueing, decoding, download, and any 429 waits), so it includes
the network and is not comparable with local Whisper latency.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import soundfile as sf

from voicebench.asr import Transcript
from voicebench.gnani import COMPARABILITY, COST_NOTE, MAX_CLIP_S, PROVIDER
from voicebench.gnani.budget import Budget, GnaniRunAborted
from voicebench.gnani.client import BASE_URL, STT_PATH, GnaniClient, GnaniError

LANGUAGE_CODES = {"en": "en-IN", "hi": "hi-IN"}
CODE_SWITCHED = "hi-IN,en-IN"
DEFAULT_MODEL = "prisma-v3.0"


class ClipTooLong(ValueError):
    """Over the 30 s REST limit; not sent, so it costs nothing."""


def language_code_for(language: Optional[str], model: Optional[str], auto_code: str = CODE_SWITCHED) -> str:
    if language is None:
        if ("," in auto_code or auto_code == "indic-auto") and model != "prisma-v3.0":
            raise ValueError(f"{model or 'the default model'} needs one language code; "
                             "use --language-policy hint or model prisma-v3.0")
        return auto_code
    try:
        return LANGUAGE_CODES[language]
    except KeyError:
        raise ValueError(f"no Gnani language code for {language!r}; known: {sorted(LANGUAGE_CODES)}") from None


def short_language(code: Optional[str]) -> Optional[str]:
    return code.split("-", 1)[0].lower() if isinstance(code, str) and code else None


def external_api_block(budget: Budget, client: GnaniClient, endpoints: list[str]) -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "endpoints": endpoints,
        "comparability": COMPARABILITY,
        "http_attempts": client.http_attempts,
        **budget.as_dict(),
    }


def call_gnani(budget: Budget, entry: dict[str, Any], fn, *args: Any, **kwargs: Any):
    """Run one client call, filling in the budget log entry; fatal API errors abort the run."""
    try:
        reply = fn(*args, **kwargs)
    except GnaniError as exc:
        entry.update({"status": exc.status_code, "error": exc.error_code or type(exc).__name__})
        if exc.fatal:
            raise GnaniRunAborted(exc) from None
        raise
    entry.update({"status": reply.status_code, "attempts": reply.attempts, "request_id": reply.request_id})
    if reply.usage_headers:
        entry["usage_headers"] = reply.usage_headers
    return reply


class GnaniPrismaTranscriber:
    def __init__(
        self,
        client: GnaniClient,
        budget: Budget,
        model: Optional[str] = DEFAULT_MODEL,
        format: str = "verbatim",
        auto_language_code: str = CODE_SWITCHED,
    ):
        language_code_for(None, model, auto_language_code)  # fail now, not on the first request
        self.client = client
        self.budget = budget
        self.model = model
        self.format = format
        self.auto_language_code = auto_language_code
        self.name = f"gnani-{model or 'prisma-default'}"
        self._served_models: set[str] = set()

    cost_note = COST_NOTE

    def describe(self) -> dict[str, Any]:
        # runner.run and run_realspeech call this after the loop, so the
        # request counts below cover the whole run, warm-up included.
        return {
            "name": self.name,
            "backend": "gnani-rest-stt",
            "backend_version": self.model or "api default",
            "device": "cloud",
            "model": self.model,
            "format": self.format,
            "language_codes": {**LANGUAGE_CODES, "auto": self.auto_language_code},
            "models_reported_by_api": sorted(self._served_models),
            "external_api": external_api_block(self.budget, self.client, [BASE_URL + STT_PATH]),
        }

    def transcribe_bytes(self, audio: bytes, filename: str, duration_s: float,
                         language: Optional[str], item: str, language_code: Optional[str] = None) -> Transcript:
        """``language_code``, when given, is sent as is instead of being derived from ``language``."""
        if duration_s > MAX_CLIP_S:
            raise ClipTooLong(f"{item}: {duration_s:.1f} s is over the {MAX_CLIP_S:.0f} s REST STT limit; not sent")
        code = language_code or language_code_for(language, self.model, self.auto_language_code)
        entry = self.budget.reserve("stt", item)
        entry.update({"language_code": code, "audio_s": round(duration_s, 3)})
        self.budget.audio_seconds_sent += duration_s
        start = time.perf_counter()
        reply = call_gnani(self.budget, entry, self.client.transcribe, audio, filename,
                           language_code=code, model=self.model, format=self.format)
        latency_ms = (time.perf_counter() - start) * 1000
        body = reply.json or {}
        if isinstance(body.get("model"), str):
            self._served_models.add(body["model"])
        if body.get("truncated") is True:
            entry["truncated"] = True
        return Transcript(
            text=body["transcript"].strip(),
            model=self.name,
            detected_language=short_language(body.get("detected_language_code")),
            language_probability=None,
            requested_language=language,
            latency_ms=latency_ms,
            audio_duration_s=duration_s,
        )

    def transcribe_file(self, path: str | Path, language: Optional[str] = None) -> Transcript:
        path = Path(path)
        duration_s = sf.info(str(path)).duration
        return self.transcribe_bytes(path.read_bytes(), path.name, duration_s, language, path.stem)
