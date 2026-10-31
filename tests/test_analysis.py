"""Failure categorisation tests. All results here are hand-written fixtures."""

from datetime import datetime, timezone

import pytest

from conftest import make_scenario
from voicebench.analysis import agent_prompt_recall, analyse_case, analyse_run, format_analysis, has_repetition_loop
from voicebench.schema import RunManifest, Scenario, ScenarioResult


@pytest.mark.parametrize(
    "text, expected",
    [
        ("may god be with you may god be with you may god be with you may god be with you", True),
        ("आब आब आब आब आब", True),
        ("नि" * 12, True),
        ("t-t-t-t-t-t-t-t-t-t-t-t", True),
        ("send two thousand no sorry four thousand", False),
        ("ok ok ok", False),  # three repeats is not a loop
        ("no no no no i said four", False),  # natural self-correction is not a loop
        ("art art art art art art art", True),  # a real loop transcript (v1-045) repeats 7+ times
        ("transfer 1000000000000 rupees", False),  # long numbers are not loops
        ("", False),
    ],
)
def test_repetition_loop(text, expected):
    assert has_repetition_loop(text) is expected


def scen(**kw):
    return Scenario.model_validate(make_scenario(**kw))


def res(**kw):
    base = {"scenario_id": "v1-001", "scenario_version": "v1", "source": "fixture",
            "transcript": "please send five thousand rupees to rahul", "detected_language": "en",
            "predicted_intent": "transfer_money", "intent_correct": True, "slots_correct": True, "task_success": True}
    base.update(kw)
    return ScenarioResult.model_validate(base)


BARGE = {"kind": "barge_in", "agent_prompt": "welcome to the bank say balance for balance", "caller_onset_ms": 900}


def test_agent_prompt_recall():
    s = scen(condition="interruption", interruption=BARGE)
    assert agent_prompt_recall(s, "welcome to the bank say balance for balance") == pytest.approx(1.0)
    # prompt words also in the reference ("to") are not counted: 5 of the 6 remaining words
    assert agent_prompt_recall(s, "welcome to the bank say balance") == pytest.approx(5 / 6)
    assert agent_prompt_recall(s, "please send five thousand rupees to rahul") == 0.0
    assert agent_prompt_recall(scen(), "anything") is None  # not a barge-in


def test_primary_category_order():
    hi = scen(language="hi", reference="राहुल को पाँच हज़ार रुपये भेजो")
    # wrong language beats no_intent and loop
    c = analyse_case(hi, res(transcript="may god be with you " * 5, detected_language="en", predicted_intent=None,
                             intent_correct=False, slots_correct=False, task_success=False), "auto")
    assert c.primary == "wrong_language"
    assert set(c.flags) == {"wrong_language", "repetition_loop", "no_intent"}
    # language is not judged under the hint policy
    c = analyse_case(hi, res(transcript="may god be with you " * 5, detected_language="hi", predicted_intent=None,
                             intent_correct=False, slots_correct=False, task_success=False), "hint")
    assert c.primary == "repetition_loop"


def test_slot_error_lists_slots_and_errors_win():
    s = scen()
    c = analyse_case(s, res(predicted_slots={"amount": "500", "recipient": "rahul"}, slots_correct=False,
                            task_success=False), "auto")
    assert c.primary == "slot_error" and c.wrong_slots == ["amount"]
    c = analyse_case(s, res(error="boom", transcript=None, predicted_intent=None, intent_correct=None,
                            slots_correct=None, task_success=False), "auto")
    assert c.primary == "pipeline_error"


def test_flags_on_passes_and_leak():
    s = scen(condition="interruption", interruption=BARGE, reference="get me a human agent",
             expected_intent="transfer_money", expected_slots={})
    c = analyse_case(s, res(transcript="welcome to the bank say balance human"), "auto")
    assert c.passed and c.primary is None and "agent_prompt_leak" in c.flags


def test_analyse_run_counts_and_format():
    scenarios = [scen(), scen(id="v1-002", language="hi", reference="राहुल को पाँच हज़ार रुपये भेजो")]
    run = RunManifest(
        run_id="fx", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source="fixture", command="t",
        scenarios_file="s", scenarios_sha256="0" * 64, asr_model="x", language_policy="auto",
        results=[res(), res(scenario_id="v1-002", detected_language="hu", predicted_intent=None,
                            intent_correct=False, slots_correct=False, task_success=False)],
    )
    a = analyse_run(run, scenarios)
    assert a["failures"] == 1 and a["primary"]["wrong_language"] == 1
    assert a["primary_by_language"] == {"hi": {"wrong_language": 1}}
    text = format_analysis(a)
    assert "1 of 2 scenarios failed" in text and "v1-002" in text
