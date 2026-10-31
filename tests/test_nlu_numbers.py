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
        ("i want 2 masala dosa", [("2", False)]),  # a lone numeral is a quantity, not an id
        ("12 idli", [("12", False)]),
        ("order 2 7 3", [("273", True)]),  # spaced single digits still join into an id
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


@pytest.mark.parametrize(
    "text, expected",
    [
        # str.isdigit() is true for these, but int() fails on the superscript
        ("send ² thousand to rahul", []),
        ("book a train to goa on ² may", []),
        # other non-ASCII, non-Devanagari digits are ignored, not read as an id
        ("track order ١٢٣٤", []),  # Arabic-Indic
        ("track order ①②③④", []),  # circled
        ("order ①②③④ 4821", [("4821", True)]),
        ("पीएनआर ४५२१", [("4521", True)]),  # Devanagari digits still count
    ],
)
def test_only_ascii_and_devanagari_digits_are_digits(text, expected):
    assert values(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        # groups of one or two digits join into one id (Whisper writes a PNR read in pairs this way)
        ("pnr 45 21 37 86 90", [("4521378690", True)]),
        ("order 31 27", [("3127", True)]),
        # unchanged: a group of three or more digits is not joined to a neighbour by a space
        ("track order 4821 5590", [("4821", True), ("5590", True)]),
        ("track order 12 4821", [("12", True), ("4821", True)]),
        ("cancel order 7 3 1 0", [("7310", True)]),
        ("i want 2 masala dosa", [("2", False)]),
        # Judgement call, left as it was: "3 127" could be one id 3127 or a stray 3
        # and id 127. Spaces only join groups of one or two digits ("7 3 1 0",
        # "45 21 37"), and "4821 5590" / "12 4821" stay apart, so a 3-digit group
        # stays apart here too. With a hyphen ("3-127") it is one id, like "31-27"
        # (see test_nlu_matcher.py).
        ("cancel order 3 127", [("3", True), ("127", True)]),
    ],
)
def test_short_digit_groups_join(text, expected):
    assert values(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        # English "do" before a digit string is the verb, not "two" added to the number
        ("can you do 3 plates of masala dosa", [("3", False)]),
        ("do 12 idli", [("12", False)]),
        ("can you do 4821 please", [("4821", True)]),
        # unchanged: romanised "do" as two, next to another number word or alone
        ("do teen samosa", [("23", True)]),
        ("ek do teen", [("123", True)]),
        ("do samosa chahiye", []),  # "do" alone is ambiguous and was never read as a number
        ("do hazaar bhejo", [("2000", False)]),
        ("दो 3 समोसा", [("5", False)]),  # Devanagari दो is not the English verb: unchanged
    ],
)
def test_english_do_before_digits(text, expected):
    assert values(text) == expected


def test_english_do_before_digits_gives_the_right_quantity():
    from voicebench.nlu.matcher import match

    assert match("can you do 3 plates of masala dosa", "food").slots == {"item": "masala dosa", "quantity": "3"}


def test_every_hindi_number_word_from_one_to_ninety_nine_is_listed():
    from voicebench.nlu.numbers import UNITS

    devanagari = {v for k, v in UNITS.items() if not k.isascii()}
    assert set(range(100)) <= devanagari


@pytest.mark.parametrize(
    "text, expected",
    [
        # Reference numbers of FLEURS dev clips (1963, 1889, 31, 53) as a
        # correct transcript would say them: none of these parsed before.
        ("उन्नीस सौ तिरसठ में बाँध बनने के बाद", [("1963", False)]),
        ("अठारह सौ नवासी में यह बंदरगाह", [("1889", False)]),
        ("एक हज़ार नौ सौ तिरसठ में", [("1963", False)]),
        ("पचास किलोमीटर इकतीस मील दूर", [("50", False), ("31", False)]),
        ("तिरपन साल के", [("53", False)]),
        ("निन्यानबे और निन्यानवे", [("99", False), ("99", False)]),  # -नबे and -नवे
        ("अड़तालीस", [("48", False)]),
        ("अडतालीस", [("48", False)]),  # nukta dropped
    ],
)
def test_hindi_two_digit_words_and_years(text, expected):
    assert values(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        # FLEURS dev clip 834255654721637854, both policies: 400 written as "चार्सो"
        ("अब लग्बक चार्सो रोयल, बंगाल ताइगर्स", [("400", False)]),
        ("चारसौ", [("400", False)]),
        ("चार्सौ", [("400", False)]),
        ("उन्नीससौ तिरसठ", [("1963", False)]),
        ("पांच सो रुपये", [("500", False)]),  # "सो" for "सौ" after a number
        ("दो सो", [("200", False)]),
        ("दो हज़ार पांच सो", [("2500", False)]),
        # "सो" alone is the word "so" / "sleep", not a hundred
        ("सो साल से पुराने", []),
        ("वो सो गया", []),
        ("सो हम चलें", []),
        ("हज़ार सो", []),  # a bare multiplier, then the word
    ],
)
def test_hundreds_written_jointly_or_with_short_vowel(text, expected):
    assert values(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Misspellings Whisper wrote on FLEURS dev clips. They are not guessed:
        # a fuzzy match would also read "साथ" (with) as "साठ" (60).
        "सथटर से जाड़ा",  # सत्तर, 70
        "ती साजार चीतल",  # तीस हज़ार, 30000
        "तप्पन्साल के",  # तिरपन साल, 53
        "पान्सो कांगलो",  # पाँच सौ, 500
        "ब्रिटेन के साथ जहाजों",
        "परसो आना",  # day after tomorrow, nasal dropped; "पर" is not a number
    ],
)
def test_misspelled_number_words_are_not_guessed(text):
    assert values(text) == []
