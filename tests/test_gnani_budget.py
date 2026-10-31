"""Budget guard: opt-in enforcement, request cap, accounting. Offline."""

import pytest

from voicebench.asr import ASRUnavailable
from voicebench.gnani import lanes
from voicebench.gnani.budget import Budget, BudgetExceeded, LiveRunRefused, require_live
from voicebench.gnani.client import API_KEY_ENV


def test_live_needs_both_the_flag_and_the_key():
    with pytest.raises(LiveRunRefused, match="--live"):
        require_live(False, {API_KEY_ENV: "k"})
    with pytest.raises(LiveRunRefused, match="GNANI_API_KEY is not set"):
        require_live(True, {})
    assert require_live(True, {API_KEY_ENV: "k"}) == "k"


def test_cap_is_enforced_before_sending():
    b = Budget(2)
    b.reserve("stt", "a")
    b.reserve("tts", "b")
    with pytest.raises(BudgetExceeded) as info:
        b.reserve("stt", "c")
    assert isinstance(info.value, ASRUnavailable)  # so runner.run aborts instead of recording an error
    assert b.requests == 2 and b.remaining == 0 and [e["item"] for e in b.log] == ["a", "b"]
    with pytest.raises(ValueError):
        Budget(0)


def test_accounting_and_summary():
    b = Budget(10)
    e = b.reserve("stt", "v1-001")
    b.audio_seconds_sent += 3.25
    e["usage_headers"] = {"x-credits-used": "1"}
    b.reserve("tts", "v1-002")
    b.tts_characters += 40
    d = b.as_dict()
    assert d["requests"] == 2 and d["stt_requests"] == 1 and d["tts_requests"] == 1
    assert d["audio_seconds_sent"] == 3.25 and d["tts_characters"] == 40
    assert d["credit_headers_by_item"] == {"v1-001": {"x-credits-used": "1"}}
    assert "credit_usage" not in d
    s = b.summary(http_attempts=3)
    assert "2 of 10 allowed requests" in s and "3.2 s of audio" in s and "app.gnani.ai" in s
    assert "3 HTTP attempts" in s


def test_no_credit_figure_without_headers():
    d = Budget(1).as_dict()
    assert "credit_headers_by_item" not in d and "Usage page" in d["credit_usage"]


@pytest.mark.parametrize("lane,cap,n", [("synthetic", 10, 9), ("realspeech", 2, 1), ("roundtrip", 10, 5),
                                        ("roundtrip", 3, 1)])
def test_items_fit_the_cap(lane, cap, n):
    assert lanes.items_for(lane, cap) == n


@pytest.mark.parametrize("lane,cap", [("synthetic", 1), ("roundtrip", 1)])
def test_cap_too_small(lane, cap):
    with pytest.raises(ValueError):
        lanes.items_for(lane, cap)
