import pytest

from voicebench.nlu.numbers import find_numbers
from voicebench.textnorm import tokens


def values(text):
    return [(s.value, s.digit_sequence) for s in find_numbers(tokens(text))]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("send five thousand rupees", [("5000", False)]),
        ("fifteen hundred rupees", [("1500", False)]),
        ("two thousand five hundred", [("2500", False)]),
        ("one lakh", [("100000", False)]),
        ("दो हज़ार रुपये", [("2000", False)]),
        ("दस हजार", [("10000", False)]),
        ("paanch hazaar bhejo", [("5000", False)]),
        ("5 हज़ार", [("5000", False)]),
        ("order four eight two one", [("4821", True)]),
        ("दो दो नौ शून्य शून्य एक सात सात चार पाँच", [("2290017745", True)]),
        ("order 4821", [("4821", True)]),
        ("cancel order 7-3-1-0 please", [("7310", True)]),  # Whisper's digit-by-digit style
        ("order 3, 1, 2, 7 cancel", [("3127", True)]),
        ("4821 5590", [("4821", True), ("5590", True)]),  # multi-digit strings stay separate
        ("पीएनआर ४५२१", [("4521", True)]),
        ("rs 5000", [("5000", True)]),
        ("two masala dosa wait make that three", [("2", False), ("3", False)]),
        ("एक वेज बिरयानी", [("1", False)]),
        ("twenty december", [("20", False)]),
        ("no numbers here", []),
        ("a hundred", []),  # bare multiplier
        ("i do want it", []),  # ambiguous romanised word alone
        ("ek do teen", [("123", True)]),
        ("amit को fifteen hundred rupees transfer कर दो", [("1500", False)]),  # verb दो
        ("ऑर्डर कैंसल कर दो", []),
        ("मुझे दो पिज़्ज़ा चाहिए", [("2", False)]),  # number दो
    ],
)
def test_find_numbers(text, expected):
    assert values(text) == expected


def test_comma_grouped_digits_need_preprocessing():
    # "5,000" normalises to "5 000"; the matcher joins digit groups before this.
    assert values("5,000") == [("5", True), ("000", True)]
