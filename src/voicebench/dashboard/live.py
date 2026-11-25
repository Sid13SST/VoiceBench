"""Server side of the live test console: text in, the project's own matcher and WER out.

The browser transcribes the audio itself (Whisper via transformers.js) and
sends only the text here. Nothing in this module stores or logs a request:
the transcript and reference are validated, scored and returned.

Only stdlib, pydantic and the scoring modules are imported, so the
dashboard deployment stays free of numpy / scipy / the ASR stack.
"""

from __future__ import annotations

import re
import wave
from array import array
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from voicebench.metrics import wer
from voicebench.nlu.matcher import match
from voicebench.schema import Domain, ResultSource, Scenario, ScenarioResult
from voicebench.scoring import score
from voicebench.textnorm import normalise, script_profile

MAX_TEXT_CHARS = 2000
MAX_BODY_BYTES = 16_384
SCENARIO_ID_RE = re.compile(r"^v\d+-\d{3}$")


class AnalyzeRequest(BaseModel):
    """What the console sends: text only, never audio."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    transcript: str = Field(max_length=MAX_TEXT_CHARS)
    domain: Domain
    reference: Optional[str] = Field(default=None, max_length=MAX_TEXT_CHARS)
    scenario_id: Optional[str] = Field(default=None, max_length=16)

    @field_validator("scenario_id")
    @classmethod
    def _scenario_id_shape(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not SCENARIO_ID_RE.match(v):
            raise ValueError("scenario_id must look like v1-001")
        return v

    @field_validator("transcript", "reference")
    @classmethod
    def _no_control_chars(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and any(ord(c) < 32 and c not in "\t\n\r" for c in v):
            raise ValueError("control characters are not allowed")
        return v


def _wer_or_reason(reference: str, transcript: str) -> tuple[Optional[float], Optional[str]]:
    if not normalise(reference):
        return None, "the reference has no words after normalisation"
    return round(wer(reference, transcript), 4), None


def analyze(req: AnalyzeRequest, scenario: Optional[Scenario] = None) -> dict[str, Any]:
    """Intent and slots from the built-in matcher, WER against the reference, and task success for a scenario.

    For a benchmark scenario the result comes from ``voicebench.scoring.score``,
    the same function the benchmark runs use, so the live verdict follows the
    same rule (right intent and every expected slot right). The scenario's own
    domain is used, whatever ``req.domain`` says.
    """
    out: dict[str, Any] = {
        "transcript_chars": len(req.transcript),
        "transcript_script": script_profile(req.transcript),
        "normalised_transcript": normalise(req.transcript),
        "matcher": "voicebench.nlu.matcher (built-in, rule-based)",
    }
    if scenario is not None:
        r: ScenarioResult = score(scenario, req.transcript, ResultSource.MEASURED)
        out.update({
            "domain": scenario.domain.value,
            "intent": r.predicted_intent,
            "slots": r.predicted_slots,
            "scenario": {
                "id": scenario.id,
                "expected_intent": scenario.expected_intent,
                "expected_slots": scenario.expected_slots,
                "intent_correct": r.intent_correct,
                "slots_correct": r.slots_correct,
                "task_success": r.task_success,
            },
        })
        reference = req.reference or scenario.reference
    else:
        pred = match(req.transcript, req.domain)
        out.update({"domain": req.domain.value, "intent": pred.intent, "slots": pred.slots})
        reference = req.reference
    out["reference_given"] = bool(reference)
    out["wer"], out["wer_note"] = _wer_or_reason(reference, req.transcript) if reference else (None, None)
    return out


def wav_peaks(path: str | Path, buckets: int = 96) -> list[float]:
    """Peak amplitude per bucket (0..1) of a 16-bit PCM WAV, using only the stdlib."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            return []
        channels = w.getnchannels()
        samples = array("h", w.readframes(w.getnframes()))
    if channels > 1:
        samples = samples[::channels]
    if not samples:
        return []
    step = max(1, len(samples) // buckets)
    peaks = [max(abs(x) for x in samples[i:i + step]) for i in range(0, step * buckets, step) if samples[i:i + step]]
    top = max(peaks) or 1
    return [round(p / top, 3) for p in peaks]
