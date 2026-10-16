"""Speech-to-text adapters.

The baseline is a small Whisper model run locally through faster-whisper
(CTranslate2). Nothing here calls a paid or remote API. Model weights are
downloaded from the Hugging Face Hub on first use, or loaded from a local
directory if ``model`` is a path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Optional, Protocol

import numpy as np

from voicebench.audio.signal import SAMPLE_RATE, read_wav

# Scenario language -> Whisper language code when the caller's language is
# given to the model as a hint. Whisper has no code-switched "hi-en" code,
# so hi-en is decoded as Hindi.
WHISPER_LANGUAGE_HINT = {"en": "en", "hi": "hi", "hi-en": "hi"}


class ASRUnavailable(RuntimeError):
    """The ASR backend or its model weights cannot be loaded."""


@dataclass(frozen=True)
class Transcript:
    text: str
    model: str
    detected_language: Optional[str]
    language_probability: Optional[float]
    requested_language: Optional[str]
    latency_ms: float
    audio_duration_s: float


class Transcriber(Protocol):
    name: str

    def describe(self) -> dict[str, Any]: ...

    def transcribe(self, audio: np.ndarray, language: Optional[str] = None) -> Transcript: ...


class FasterWhisperTranscriber:
    def __init__(
        self,
        model: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 5,
        local_files_only: bool = False,
        _model: Any = None,  # injected in tests
    ):
        self.name = f"faster-whisper/{Path(model).name if Path(model).exists() else model}"
        self.model_ref = model
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.local_files_only = local_files_only
        self._model = _model

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ASRUnavailable("faster-whisper is not installed; run `pip install -e '.[asr]'`") from exc
        try:
            self._model = WhisperModel(
                self.model_ref,
                device=self.device,
                compute_type=self.compute_type,
                local_files_only=self.local_files_only,
            )
        except Exception as exc:  # network blocked, missing files, bad path...
            raise ASRUnavailable(
                f"could not load Whisper model {self.model_ref!r}: {type(exc).__name__}: {exc}. "
                "The weights come from huggingface.co on first use; if that host is unreachable, "
                "download a CTranslate2 Whisper model elsewhere and pass its directory as the model."
            ) from exc
        return self._model

    def describe(self) -> dict[str, Any]:
        try:
            fw_version = metadata.version("faster-whisper")
        except metadata.PackageNotFoundError:
            fw_version = None
        return {
            "name": self.name,
            "model": self.model_ref,
            "backend": "faster-whisper",
            "backend_version": fw_version,
            "device": self.device,
            "compute_type": self.compute_type,
            "beam_size": self.beam_size,
        }

    def transcribe(self, audio: np.ndarray, language: Optional[str] = None) -> Transcript:
        model = self._load()
        start = time.perf_counter()
        segments, info = model.transcribe(
            audio,
            language=language,
            beam_size=self.beam_size,
            # Deterministic decoding: no temperature fallback sampling.
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()  # segments is lazy
        latency_ms = (time.perf_counter() - start) * 1000
        return Transcript(
            text=text,
            model=self.name,
            detected_language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            requested_language=language,
            latency_ms=latency_ms,
            audio_duration_s=len(audio) / SAMPLE_RATE,
        )

    def transcribe_file(self, path: str | Path, language: Optional[str] = None) -> Transcript:
        return self.transcribe(read_wav(path), language=language)
