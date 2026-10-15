"""Checks on the shipped scenario set itself, so accidental edits fail CI."""

from collections import Counter
from pathlib import Path

import pytest

from voicebench.loader import load_scenarios
from voicebench.schema import Condition, InterruptionKind

V1 = Path(__file__).resolve().parents[1] / "scenarios" / "v1.jsonl"


@pytest.fixture(scope="module")
def v1():
    return load_scenarios(V1, expected_version="v1")


def test_v1_size_and_ids(v1):
    assert len(v1) == 50
    assert [s.id for s in v1] == [f"v1-{i:03d}" for i in range(1, 51)]


def test_v1_condition_split(v1):
    assert Counter(s.condition for s in v1) == {
        Condition.CLEAN: 30,
        Condition.NOISE: 10,
        Condition.INTERRUPTION: 10,
    }
    assert Counter(s.snr_db for s in v1 if s.condition is Condition.NOISE) == {5: 5, 10: 5}
    kinds = Counter(s.interruption.kind for s in v1 if s.interruption)
    assert kinds == {InterruptionKind.BARGE_IN: 5, InterruptionKind.SELF_CORRECTION: 5}


def test_v1_covers_every_language_domain_and_condition(v1):
    languages = {s.language.value for s in v1}
    domains = {s.domain.value for s in v1}
    assert languages == {"en", "hi", "hi-en"}
    assert domains == {"banking", "food", "travel", "support"}
    for cond in Condition:
        assert {s.language.value for s in v1 if s.condition is cond} == languages


def test_v1_clean_split_is_balanced_by_language(v1):
    clean = Counter(s.language.value for s in v1 if s.condition is Condition.CLEAN)
    assert clean == {"en": 10, "hi": 10, "hi-en": 10}


def test_v1_references_follow_transcript_convention(v1):
    for s in v1:
        assert s.reference == s.reference.lower(), s.id
        assert not any(ch in s.reference for ch in ".,?!।"), s.id
        assert not any(ch.isdigit() for ch in s.reference), s.id


def test_v1_slot_values_are_canonical_ascii(v1):
    for s in v1:
        for value in s.expected_slots.values():
            assert value.isascii() and value == value.lower(), (s.id, value)
