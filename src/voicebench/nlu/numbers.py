"""Find numbers in normalised English / Hindi / romanised-Hindi tokens.

Two readings are produced for each maximal run of number tokens:

- a run of two or more single-digit words ("four eight two one",
  "दो दो नौ") is read digit by digit -> "4821" (order ids, PNRs), and so
  is a run of digit strings ("4821", "7 3 1 0", "45 21 37") - except a lone numeral
  of one or two digits ("2", "12") with no digit string next to it,
  which is a quantity;
- anything else is read as a quantity -> "fifteen hundred" = 1500,
  "दो हज़ार" = 2000.

Hindi number words for 1-99 are irregular (each of 21-99 is its own word,
not "twenty one"), so all of them are listed in their standard spelling,
plus the spelling variants dictionaries give. A year is said as hundreds:
"उन्नीस सौ तिरसठ" = 19 x 100 + 63 = 1963. Two written forms of the
hundreds that Whisper produces on real speech are also read:

- the unit and "सौ" written as one word, "चारसौ" or with a virama on the
  unit, "चार्सौ" (= चार सौ, 400);
- "सो" for "सौ" (the vowel written short). "सो" is also a common word
  ("so", "sleep"), so it counts only right after a number, "चार सो" or
  "चार्सो", never alone.

Misspelled number words ("सथटर" for सत्तर) are not guessed at: a fuzzy
match would also read "साथ" (with) as "साठ" (60).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from voicebench.textnorm import fold_spelling_variants as _fold

UNITS: dict[str, int] = {
    # English
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    # Hindi, Devanagari (common spelling variants included)
    "शून्य": 0, "ज़ीरो": 0, "जीरो": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4,
    "पाँच": 5, "पांच": 5, "छह": 6, "छः": 6, "छे": 6, "सात": 7, "आठ": 8,
    "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12, "तेरह": 13, "चौदह": 14,
    "पंद्रह": 15, "पन्द्रह": 15, "सोलह": 16, "सत्रह": 17, "अठारह": 18,
    "उन्नीस": 19, "बीस": 20, "पच्चीस": 25, "तीस": 30, "चालीस": 40,
    "पचास": 50, "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90,
    # Hindi 21-99 (the 1-20 and round tens above are not repeated)
    "इक्कीस": 21, "बाईस": 22, "तेईस": 23, "चौबीस": 24, "छब्बीस": 26,
    "सत्ताईस": 27, "अट्ठाईस": 28, "उनतीस": 29,
    "इकतीस": 31, "बत्तीस": 32, "तैंतीस": 33, "चौंतीस": 34, "पैंतीस": 35,
    "छत्तीस": 36, "सैंतीस": 37, "अड़तीस": 38, "उनतालीस": 39,
    "इकतालीस": 41, "बयालीस": 42, "तैंतालीस": 43, "चौवालीस": 44, "चवालीस": 44,
    "पैंतालीस": 45, "छियालीस": 46, "सैंतालीस": 47, "अड़तालीस": 48, "उनचास": 49,
    "इक्यावन": 51, "बावन": 52, "तिरपन": 53, "तिरेपन": 53, "चौवन": 54, "चौव्वन": 54,
    "पचपन": 55, "छप्पन": 56, "सत्तावन": 57, "अट्ठावन": 58, "उनसठ": 59,
    "इकसठ": 61, "बासठ": 62, "तिरसठ": 63, "चौंसठ": 64, "पैंसठ": 65,
    "छियासठ": 66, "सड़सठ": 67, "सरसठ": 67, "अड़सठ": 68, "उनहत्तर": 69,
    "इकहत्तर": 71, "बहत्तर": 72, "तिहत्तर": 73, "चौहत्तर": 74, "पचहत्तर": 75,
    "छिहत्तर": 76, "सतहत्तर": 77, "अठहत्तर": 78, "उन्यासी": 79, "उनासी": 79,
    "इक्यासी": 81, "बयासी": 82, "तिरासी": 83, "चौरासी": 84, "पचासी": 85,
    "छियासी": 86, "सत्तासी": 87, "अट्ठासी": 88, "नवासी": 89,
    # 91-99 end in -नबे or -नवे; both spellings are standard
    "इक्यानबे": 91, "बानबे": 92, "तिरानबे": 93, "चौरानबे": 94, "पचानबे": 95,
    "छियानबे": 96, "सत्तानबे": 97, "अट्ठानबे": 98, "निन्यानबे": 99,
    "इक्यानवे": 91, "बानवे": 92, "तिरानवे": 93, "चौरानवे": 94, "पचानवे": 95,
    "छियानवे": 96, "सत्तानवे": 97, "अट्ठानवे": 98, "निन्यानवे": 99,
    # Hindi, romanised (as an ASR model may write it)
    "shunya": 0, "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4,
    "paanch": 5, "panch": 5, "chhe": 6, "chhah": 6, "saat": 7, "aath": 8,
    "nau": 9, "das": 10, "barah": 12, "baarah": 12, "pandrah": 15, "bees": 20,
    "pachas": 50, "pachaas": 50,
}
HUNDRED = {"hundred", "सौ", "sau"}
THOUSAND = {"thousand", "हज़ार", "हजार", "hazaar", "hazar", "hajar"}
LAKH = {"lakh", "lac", "लाख"}
MULTIPLIERS = HUNDRED | THOUSAND | LAKH
# Lookups use folded spellings, so "हजार" and "हज़ार", "पांच" and "पाँच"
# are the same word whichever one a transcript uses.
_UNITS = {_fold(k): v for k, v in UNITS.items()}
_HUNDRED = {_fold(w) for w in HUNDRED}
_THOUSAND = {_fold(w) for w in THOUSAND}
_LAKH = {_fold(w) for w in LAKH}
_MULTIPLIERS = _HUNDRED | _THOUSAND | _LAKH
# "सो" for "सौ": a hundred only right after another number token.
_HUNDRED_AFTER_NUMBER = {"सो"}
# Endings of a unit and its hundred written as one word: "चारसौ", "चार्सो".
_FUSED_HUNDRED_ENDINGS = ("सौ", "सो")
_VIRAMA = "\u094d"

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
# Only ASCII and Devanagari digits. str.isdigit() also accepts "²", "①" or
# Arabic-Indic digits; int() rejects some of those, and none of them is a
# digit a v1 caller says, so they are ignored like any other unknown token.
_DIGITS_RE = re.compile(r"[0-9०-९]+")
# Romanised words that are also common English/Hinglish words. They count as
# numbers only inside a run that already contains another number token.
_AMBIGUOUS = {"do", "das", "char", "teen", "ek", "oh", "nau", "saat"}
# "दो" is also the imperative "give/do": "कर दो", "बता दो", "भेज दो". Alone
# after one of these verbs it is read as the verb, not the number two.
_DO_WORDS = {"दो", "do"}
_LIGHT_VERBS = {"कर", "kar", "दे", "de", "बता", "bata", "भेज", "bhej", "ले", "le", "हटा", "बदल"}


@dataclass(frozen=True)
class NumberSpan:
    start: int  # token index, inclusive
    end: int  # token index, exclusive
    value: str  # digits only
    digit_sequence: bool  # read digit by digit (an id), not as a quantity


def _fused_hundred(tok: str) -> int | None:
    """Value of a folded token that is a unit 1-99 and its hundred as one word ("चार्सो" -> 400)."""
    for ending in _FUSED_HUNDRED_ENDINGS:
        if tok.endswith(ending) and len(tok) > len(ending):
            stem = tok[: -len(ending)]
            # "चार्" + "सो": the virama only marks the unit's last consonant
            # as having no vowel before the next word's consonant.
            stem = stem[:-1] if stem.endswith(_VIRAMA) else stem
            n = _UNITS.get(stem)
            if n is not None and 1 <= n <= 99 and not stem.isascii():
                return n * 100
    return None


def _unit_value(tok: str) -> int | None:
    """Value of a folded word that adds to the running number: a unit, or a fused hundred."""
    n = _UNITS.get(tok)
    return n if n is not None else _fused_hundred(tok)


def _token_kind(tok: str) -> str | None:
    if _DIGITS_RE.fullmatch(tok):
        return "digits"
    tok = _fold(tok)
    if _unit_value(tok) is not None:
        return "unit"
    if tok in _MULTIPLIERS:
        return "mult"
    return None


def _single_digit_word(tok: str) -> bool:
    n = None if _DIGITS_RE.fullmatch(tok) else _unit_value(_fold(tok))
    return n is not None and n <= 9


def _continues_run(tokens: list[str], j: int, i: int) -> bool:
    """tokens[j] extends the number run that started at i."""
    if _token_kind(tokens[j]) is not None:
        return True
    # "चार सो": "सो" is a hundred only after a unit or digits
    return j > i and _fold(tokens[j]) in _HUNDRED_AFTER_NUMBER and _token_kind(tokens[j - 1]) in ("unit", "digits")


def _quantity(tokens: list[str]) -> int:
    total, current = 0, 0
    for tok in tokens:
        tok = _fold(tok)
        if _unit_value(tok) is not None:
            current += _unit_value(tok)
        elif tok in _HUNDRED or tok in _HUNDRED_AFTER_NUMBER:
            current = (current or 1) * 100
        elif tok in _THOUSAND:
            total += (current or 1) * 1000
            current = 0
        elif tok in _LAKH:
            total += (current or 1) * 100_000
            current = 0
        else:  # digit string inside a run, e.g. "5 हज़ार"
            current += int(tok.translate(_DEV_DIGITS))
    return total + current


def _lone_small_numeral(tokens: list[str], i: int, j: int) -> bool:
    """tokens[i:j] is one 1-2 digit string ("2", "12"), not part of a longer digit group."""
    if j - i != 1 or _token_kind(tokens[i]) != "digits":
        return False
    tok = tokens[i]
    neighbours = [tokens[k] for k in (i - 1, j) if 0 <= k < len(tokens)]
    return len(tok) <= 2 and tok[0] not in "0०" and all(_token_kind(t) != "digits" for t in neighbours)


def find_numbers(tokens: list[str]) -> list[NumberSpan]:
    spans: list[NumberSpan] = []
    i = 0
    while i < len(tokens):
        kind = _token_kind(tokens[i])
        if kind is None:
            i += 1
            continue
        j = i
        while j < len(tokens) and _continues_run(tokens, j, i):
            # a digit string ends a run ("4821 5590" are two ids), except that
            # groups of one or two digits join up: Whisper writes "7310" read
            # digit by digit as "7-3-1-0" or "7, 3, 1, 0", which normalise to
            # "7 3 1 0", and a PNR read in pairs as "45 21 37 86 90".
            if (
                j > i
                and _token_kind(tokens[j]) == "digits"
                and _token_kind(tokens[j - 1]) == "digits"
                and not (len(tokens[j]) <= 2 and len(tokens[j - 1]) <= 2)
            ):
                break
            j += 1
        run = tokens[i:j]
        # Romanised "do" right before a digit string is the English verb
        # ("can you do 3 plates"), not "two" to add to it: start after it.
        if run[0] == "do" and len(run) > 1 and _token_kind(run[1]) == "digits":
            i += 1
            continue
        if len(run) == 1 and run[0] in _AMBIGUOUS:
            i = j
            continue
        if len(run) == 1 and run[0] in _DO_WORDS and i > 0 and tokens[i - 1] in _LIGHT_VERBS:
            i = j
            continue
        if _lone_small_numeral(tokens, i, j):
            spans.append(NumberSpan(i, j, run[0].translate(_DEV_DIGITS), digit_sequence=False))
        elif all(_token_kind(t) == "digits" for t in run):
            spans.append(NumberSpan(i, j, "".join(run).translate(_DEV_DIGITS), digit_sequence=True))
        elif len(run) >= 2 and all(_single_digit_word(t) for t in run):
            spans.append(NumberSpan(i, j, "".join(str(_UNITS[_fold(t)]) for t in run), digit_sequence=True))
        elif all(_fold(t) in _MULTIPLIERS for t in run):
            pass  # a bare "hundred" or "हज़ार" is not a number on its own
        else:
            spans.append(NumberSpan(i, j, str(_quantity(run)), digit_sequence=False))
        i = j
    return spans
