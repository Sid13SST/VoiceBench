"""Deterministic scoring tests. All transcripts here are hand-written fixtures."""

import pytest

from conftest import make_scenario
from voicebench.schema import ResultSource, Scenario
from voicebench.scoring import failed, score, slots_match

FIX = ResultSource.FIXTURE


@pytest.fixture
def transfer():
    return Scenario.model_validate(make_scenario())  # "please send five thousand rupees to rahul"


def test_perfect_transcript(transfer):
    r = score(transfer, "please send five thousand rupees to rahul", FIX)
    assert r.wer == 0.0
    assert r.intent_correct and r.slots_correct and r.task_success
    assert r.transcript_script == "latin"
    assert r.source is FIX


def test_digits_cost_wer_but_not_the_task(transfer):
    r = score(transfer, "Please send 5000 rupees to Rahul.", FIX)
    assert r.wer == pytest.approx(2 / 7)  # "five thousand" -> "5000": 1 sub + 1 del
    assert r.task_success


def test_wrong_slot_fails_task_but_keeps_intent(transfer):
    r = score(transfer, "please send five thousand rupees to rohan", FIX)
    assert r.intent_correct and not r.slots_correct and not r.task_success
    assert r.wer == pytest.approx(1 / 7)


def test_wrong_intent(transfer):
    r = score(transfer, "please check my balance", FIX)
    assert r.predicted_intent == "check_balance"
    assert not r.intent_correct and not r.task_success


def test_empty_transcript(transfer):
    r = score(transfer, "", FIX)
    assert r.wer == 1.0
    assert r.predicted_intent is None and not r.task_success
    assert r.transcript_script == "none"


def test_script_mismatch_is_recorded():
    s = Scenario.model_validate(
        make_scenario(language="hi-en", reference="मेरा credit card block कर दो", expected_intent="block_card",
                      expected_slots={"card_type": "credit"})
    )
    r = score(s, "मेरा क्रेडिट कार्ड ब्लॉक कर दो", FIX)
    assert r.transcript_script == "devanagari"
    assert r.wer == pytest.approx(3 / 6)  # three English words written in Devanagari
    assert r.task_success  # the matcher reads both scripts


def test_slots_match_ignores_extra_predictions():
    assert slots_match({"amount": "5000"}, {"amount": "5000", "recipient": "x"})
    assert not slots_match({"amount": "5000"}, {})
    assert slots_match({}, {"anything": "1"})


def test_failed_result(transfer):
    r = failed(transfer, FIX, "boom")
    assert r.error == "boom" and r.task_success is False and r.wer is None
