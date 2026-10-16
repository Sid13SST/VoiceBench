"""Score one transcript against one scenario."""

from __future__ import annotations

from typing import Optional

from voicebench.metrics import wer
from voicebench.nlu.matcher import match
from voicebench.schema import ResultSource, Scenario, ScenarioResult
from voicebench.textnorm import script_profile


def slots_match(expected: dict[str, str], predicted: dict[str, str]) -> bool:
    """Every expected slot must be present with exactly the expected value.

    Extra predicted slots are not penalised: the agent would just confirm or
    ignore them.
    """
    return all(predicted.get(k) == v for k, v in expected.items())


def score(
    scenario: Scenario,
    transcript: str,
    source: ResultSource,
    latency_ms: Optional[float] = None,
    audio_duration_s: Optional[float] = None,
    detected_language: Optional[str] = None,
    cost_usd: Optional[float] = None,
) -> ScenarioResult:
    pred = match(transcript, scenario.domain)
    intent_ok = pred.intent == scenario.expected_intent
    slots_ok = slots_match(scenario.expected_slots, pred.slots)
    return ScenarioResult(
        scenario_id=scenario.id,
        scenario_version=scenario.version,
        source=source,
        transcript=transcript,
        detected_language=detected_language,
        transcript_script=script_profile(transcript),
        wer=wer(scenario.reference, transcript),
        predicted_intent=pred.intent,
        predicted_slots=pred.slots,
        intent_correct=intent_ok,
        slots_correct=slots_ok,
        task_success=intent_ok and slots_ok,
        latency_ms=None if latency_ms is None else round(latency_ms, 1),
        audio_duration_s=audio_duration_s,
        cost_usd=cost_usd,
    )


def failed(scenario: Scenario, source: ResultSource, error: str) -> ScenarioResult:
    """A scenario the pipeline could not process. It counts as a task failure."""
    return ScenarioResult(
        scenario_id=scenario.id,
        scenario_version=scenario.version,
        source=source,
        task_success=False,
        error=error,
    )
