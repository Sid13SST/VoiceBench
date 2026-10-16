"""Data models for scenarios and evaluation results.

A *scenario* is one simulated caller turn: what the caller says (the reference
utterance), the acoustic condition it is heard under, and what a correct voice
agent should extract from it (intent + slots).

A *result* is what one run of the harness produced for one scenario. Results
carry a ``source`` field so measured numbers can never be confused with
hand-written fixtures used in tests.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCENARIO_ID_RE = re.compile(r"^v(\d+)-\d{3}$")
DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
LATIN_RE = re.compile(r"[A-Za-z]")

ALLOWED_SNR_DB = (5, 10)


class Language(str, Enum):
    EN = "en"
    HI = "hi"
    HI_EN = "hi-en"


class Domain(str, Enum):
    BANKING = "banking"
    FOOD = "food"
    TRAVEL = "travel"
    SUPPORT = "support"


class Condition(str, Enum):
    CLEAN = "clean"
    NOISE = "noise"
    INTERRUPTION = "interruption"


class NoiseType(str, Enum):
    WHITE = "white"
    PINK = "pink"
    BABBLE = "babble"


class InterruptionKind(str, Enum):
    # The caller starts talking while the agent's prompt is still playing,
    # so the recording contains overlapping agent speech.
    BARGE_IN = "barge_in"
    # The caller cuts themselves off and corrects what they said; the
    # expected slots reflect the corrected (final) value.
    SELF_CORRECTION = "self_correction"


# Intent -> slots that may appear for it. Every scenario's intent must belong
# to its domain and its slot keys must be a subset of the intent's slots.
INTENTS: dict[Domain, dict[str, frozenset[str]]] = {
    Domain.BANKING: {
        "check_balance": frozenset({"account_type"}),
        "transfer_money": frozenset({"amount", "recipient"}),
        "block_card": frozenset({"card_type"}),
        "report_fraud": frozenset({"amount"}),
    },
    Domain.FOOD: {
        "order_food": frozenset({"item", "quantity"}),
        "track_order": frozenset({"order_id"}),
        "cancel_order": frozenset({"order_id"}),
    },
    Domain.TRAVEL: {
        "book_ticket": frozenset({"mode", "source", "destination", "date"}),
        "cancel_booking": frozenset({"mode", "date"}),
        "check_pnr_status": frozenset({"pnr"}),
    },
    Domain.SUPPORT: {
        "reset_password": frozenset(),
        "report_issue": frozenset({"device", "issue"}),
        "talk_to_agent": frozenset(),
    },
}


class Interruption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: InterruptionKind
    # Text of the agent prompt the caller talks over (barge_in only).
    agent_prompt: Optional[str] = None
    # How far into the agent prompt the caller starts speaking (barge_in only).
    caller_onset_ms: Optional[int] = Field(default=None, ge=0, le=10_000)

    @model_validator(mode="after")
    def _check_kind_fields(self) -> "Interruption":
        if self.kind is InterruptionKind.BARGE_IN:
            if not self.agent_prompt or self.caller_onset_ms is None:
                raise ValueError("barge_in needs agent_prompt and caller_onset_ms")
        else:
            if self.agent_prompt is not None or self.caller_onset_ms is not None:
                raise ValueError("self_correction must not set agent_prompt/caller_onset_ms")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    version: str
    language: Language
    domain: Domain
    condition: Condition
    reference: str = Field(min_length=1)
    expected_intent: str
    expected_slots: dict[str, str] = Field(default_factory=dict)
    snr_db: Optional[int] = None
    noise_type: Optional[NoiseType] = None
    interruption: Optional[Interruption] = None
    notes: Optional[str] = None

    @field_validator("reference")
    @classmethod
    def _strip_reference(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("reference must not be blank")
        return v

    @field_validator("expected_slots")
    @classmethod
    def _slot_values_nonempty(cls, v: dict[str, str]) -> dict[str, str]:
        for key, value in v.items():
            if not value.strip():
                raise ValueError(f"slot {key!r} has an empty value")
        return v

    @model_validator(mode="after")
    def _check_consistency(self) -> "Scenario":
        m = SCENARIO_ID_RE.match(self.id)
        if not m:
            raise ValueError(f"id {self.id!r} must look like 'v1-001'")
        if f"v{m.group(1)}" != self.version:
            raise ValueError(f"id {self.id!r} does not match version {self.version!r}")

        domain_intents = INTENTS[self.domain]
        if self.expected_intent not in domain_intents:
            raise ValueError(
                f"intent {self.expected_intent!r} is not a {self.domain.value} intent; "
                f"expected one of {sorted(domain_intents)}"
            )
        extra = set(self.expected_slots) - domain_intents[self.expected_intent]
        if extra:
            raise ValueError(f"slots {sorted(extra)} not allowed for {self.expected_intent!r}")

        if self.condition is Condition.NOISE:
            if self.snr_db not in ALLOWED_SNR_DB:
                raise ValueError(f"noise scenarios need snr_db in {ALLOWED_SNR_DB}")
            if self.noise_type is None:
                raise ValueError("noise scenarios need noise_type")
        elif self.snr_db is not None or self.noise_type is not None:
            raise ValueError("snr_db/noise_type are only allowed for noise scenarios")

        if self.condition is Condition.INTERRUPTION:
            if self.interruption is None:
                raise ValueError("interruption scenarios need an interruption block")
        elif self.interruption is not None:
            raise ValueError("interruption block only allowed for interruption scenarios")

        self._check_script()
        return self

    def _check_script(self) -> None:
        """Catch obvious language mislabels.

        Convention: Hindi words are written in Devanagari and English words in
        Latin script, so code-switched (hi-en) references contain both.
        """
        has_dev = bool(DEVANAGARI_RE.search(self.reference))
        has_lat = bool(LATIN_RE.search(self.reference))
        if self.language is Language.EN and has_dev:
            raise ValueError("en reference must not contain Devanagari")
        if self.language is Language.HI and not has_dev:
            raise ValueError("hi reference must be written in Devanagari")
        if self.language is Language.HI_EN and not (has_dev and has_lat):
            raise ValueError("hi-en reference must mix Devanagari and Latin script")


class ResultSource(str, Enum):
    # Produced by actually running the pipeline on audio.
    MEASURED = "measured"
    # Hand-written, used only for tests and examples; never reported as a result.
    FIXTURE = "fixture"


class ScenarioResult(BaseModel):
    """Outcome of one scenario in one run."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    scenario_version: str
    source: ResultSource
    transcript: Optional[str] = None
    # Language Whisper detected (or was told), and the script of the transcript
    # ("devanagari" / "latin" / "mixed" / "none"), so script mismatches on
    # code-switched speech can be separated from recognition errors.
    detected_language: Optional[str] = None
    transcript_script: Optional[str] = None
    wer: Optional[float] = Field(default=None, ge=0)
    predicted_intent: Optional[str] = None
    predicted_slots: dict[str, str] = Field(default_factory=dict)
    intent_correct: Optional[bool] = None
    slots_correct: Optional[bool] = None
    # Task completion = right intent AND all expected slots right.
    task_success: Optional[bool] = None
    latency_ms: Optional[float] = Field(default=None, ge=0)
    audio_duration_s: Optional[float] = Field(default=None, ge=0)
    cost_usd: Optional[float] = Field(default=None, ge=0)
    # Set when the pipeline failed for this scenario; metrics are then None.
    error: Optional[str] = None

    @model_validator(mode="after")
    def _check_task_success(self) -> "ScenarioResult":
        if (
            self.task_success is not None
            and self.intent_correct is not None
            and self.slots_correct is not None
            and self.task_success != (self.intent_correct and self.slots_correct)
        ):
            raise ValueError("task_success must equal intent_correct and slots_correct")
        return self


class RunManifest(BaseModel):
    """Everything needed to reproduce and interpret a run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: datetime
    source: ResultSource
    command: str
    git_commit: Optional[str] = None
    scenarios_file: str
    scenarios_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asr_model: str
    asr_model_version: Optional[str] = None
    asr_config: dict[str, Any] = Field(default_factory=dict)
    # "auto" (Whisper detects the language) or "hint" (the scenario language is passed in).
    language_policy: Optional[str] = None
    device: Optional[str] = None
    tts_engine: Optional[str] = None
    notes: Optional[str] = None
    results: list[ScenarioResult]

    @model_validator(mode="after")
    def _check_results(self) -> "RunManifest":
        ids = [r.scenario_id for r in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate scenario_id in results")
        for r in self.results:
            if r.source is not self.source:
                raise ValueError("every result must have the same source as its run")
        return self

