from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from conftest import make_scenario
from voicebench.schema import (
    Condition,
    Language,
    RunManifest,
    Scenario,
    ScenarioResult,
)


def test_valid_clean_scenario(scenario_dict):
    s = Scenario.model_validate(scenario_dict)
    assert s.language is Language.EN
    assert s.condition is Condition.CLEAN
    assert s.expected_slots == {"amount": "5000", "recipient": "rahul"}


def test_reference_whitespace_is_normalised():
    s = Scenario.model_validate(make_scenario(reference="  send   money\tto rahul "))
    assert s.reference == "send money to rahul"


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"id": "001"}, "must look like"),
        ({"id": "v2-001"}, "does not match version"),
        ({"expected_intent": "order_food"}, "not a banking intent"),
        ({"expected_slots": {"pnr": "123"}}, "not allowed"),
        ({"expected_slots": {"amount": " "}}, "empty value"),
        ({"reference": "   "}, "blank"),
        ({"language": "fr"}, "language"),
        ({"unknown_field": 1}, "extra"),
    ],
)
def test_invalid_scenarios_rejected(overrides, fragment):
    with pytest.raises(ValidationError) as exc:
        Scenario.model_validate(make_scenario(**overrides))
    assert fragment.lower() in str(exc.value).lower()


def test_noise_requires_valid_snr_and_type():
    ok = make_scenario(condition="noise", snr_db=5, noise_type="pink")
    assert Scenario.model_validate(ok).snr_db == 5
    for bad in (
        make_scenario(condition="noise", noise_type="pink"),
        make_scenario(condition="noise", snr_db=20, noise_type="pink"),
        make_scenario(condition="noise", snr_db=10),
        make_scenario(snr_db=10),
    ):
        with pytest.raises(ValidationError):
            Scenario.model_validate(bad)


def test_interruption_block_rules():
    barge = make_scenario(
        condition="interruption",
        interruption={"kind": "barge_in", "agent_prompt": "How can I help?", "caller_onset_ms": 600},
    )
    assert Scenario.model_validate(barge).interruption.caller_onset_ms == 600
    selfcorr = make_scenario(condition="interruption", interruption={"kind": "self_correction"})
    Scenario.model_validate(selfcorr)

    for bad in (
        make_scenario(condition="interruption"),
        make_scenario(interruption={"kind": "self_correction"}),
        make_scenario(condition="interruption", interruption={"kind": "barge_in"}),
        make_scenario(
            condition="interruption",
            interruption={"kind": "self_correction", "caller_onset_ms": 100},
        ),
    ):
        with pytest.raises(ValidationError):
            Scenario.model_validate(bad)


def test_script_convention():
    Scenario.model_validate(make_scenario(language="hi", reference="राहुल को पाँच हज़ार रुपये भेजो"))
    Scenario.model_validate(make_scenario(language="hi-en", reference="राहुल को 5000 rupees transfer करो"))
    with pytest.raises(ValidationError, match="Devanagari"):
        Scenario.model_validate(make_scenario(language="hi", reference="rahul ko paise bhejo"))
    with pytest.raises(ValidationError, match="mix"):
        Scenario.model_validate(make_scenario(language="hi-en", reference="send money to rahul"))
    with pytest.raises(ValidationError, match="must not contain"):
        Scenario.model_validate(make_scenario(reference="send पैसे"))


def test_scenario_is_immutable(scenario_dict):
    s = Scenario.model_validate(scenario_dict)
    with pytest.raises(ValidationError):
        s.reference = "changed"


def _result(**kw):
    base = {"scenario_id": "v1-001", "scenario_version": "v1", "source": "fixture"}
    base.update(kw)
    return base


def test_task_success_must_be_consistent():
    ScenarioResult.model_validate(_result(intent_correct=True, slots_correct=False, task_success=False))
    with pytest.raises(ValidationError):
        ScenarioResult.model_validate(_result(intent_correct=True, slots_correct=False, task_success=True))


def test_negative_metrics_rejected():
    with pytest.raises(ValidationError):
        ScenarioResult.model_validate(_result(wer=-0.1))
    with pytest.raises(ValidationError):
        ScenarioResult.model_validate(_result(latency_ms=-1))


def _manifest(results, source="fixture"):
    return {
        "run_id": "test",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "source": source,
        "command": "pytest",
        "scenarios_file": "scenarios/v1.jsonl",
        "scenarios_sha256": "0" * 64,
        "asr_model": "none",
        "results": results,
    }


def test_manifest_rejects_mixed_sources_and_duplicates():
    RunManifest.model_validate(_manifest([_result()]))
    with pytest.raises(ValidationError, match="same source"):
        RunManifest.model_validate(_manifest([_result()], source="measured"))
    with pytest.raises(ValidationError, match="duplicate"):
        RunManifest.model_validate(_manifest([_result(), _result()]))
