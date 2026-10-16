"""Find numbers in normalised English / Hindi / romanised-Hindi tokens.

Two readings are produced for each maximal run of number tokens:

- a run of two or more single-digit words ("four eight two one",
  "दो दो नौ") is read digit by digit -> "4821" (order ids, PNRs);
- anything else is read as a quantity -> "fifteen hundred" = 1500,
  "दो हज़ार" = 2000.

Hindi number words for 1-100 are irregular; only the ones listed below are
covered. That limit is real and shows up in results if a model writes, say,
"सत्तासी".
"""

from __future__ import annotations

from dataclasses import dataclass

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

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
# Romanised words that are also common English/Hinglish words. They count as
# numbers only inside a run that already contains another number token.
_AMBIGUOUS = {"do", "das", "char", "teen", "ek", "oh", "nau", "saat"}


@dataclass(frozen=True)
class NumberSpan:
    start: int  # token index, inclusive
    end: int  # token index, exclusive
    value: str  # digits only
    digit_sequence: bool  # read digit by digit (an id), not as a quantity


def _token_kind(tok: str) -> str | None:
    if tok.translate(_DEV_DIGITS).isdigit():
        return "digits"
    if tok in UNITS:
        return "unit"
    if tok in MULTIPLIERS:
        return "mult"
    return None


def _quantity(tokens: list[str]) -> int:
    total, current = 0, 0
    for tok in tokens:
        if tok in UNITS:
            current += UNITS[tok]
        elif tok in HUNDRED:
            current = (current or 1) * 100
        elif tok in THOUSAND:
            total += (current or 1) * 1000
            current = 0
        elif tok in LAKH:
            total += (current or 1) * 100_000
            current = 0
        else:  # digit string inside a run, e.g. "5 हज़ार"
            current += int(tok.translate(_DEV_DIGITS))
    return total + current


def find_numbers(tokens: list[str]) -> list[NumberSpan]:
    spans: list[NumberSpan] = []
    i = 0
    while i < len(tokens):
        kind = _token_kind(tokens[i])
        if kind is None:
            i += 1
            continue
        j = i
        while j < len(tokens) and _token_kind(tokens[j]) is not None:
            # a digit string ends a run ("4821 5590" are two ids)
            if j > i and _token_kind(tokens[j]) == "digits" and _token_kind(tokens[j - 1]) == "digits":
                break
            j += 1
        run = tokens[i:j]
        if len(run) == 1 and run[0] in _AMBIGUOUS:
            i = j
            continue
        if len(run) == 1 and _token_kind(run[0]) == "digits":
            spans.append(NumberSpan(i, j, run[0].translate(_DEV_DIGITS), digit_sequence=True))
        elif len(run) >= 2 and all(t in UNITS and UNITS[t] <= 9 for t in run):
            spans.append(NumberSpan(i, j, "".join(str(UNITS[t]) for t in run), digit_sequence=True))
        elif all(t in MULTIPLIERS for t in run):
            pass  # a bare "hundred" or "हज़ार" is not a number on its own
        else:
            spans.append(NumberSpan(i, j, str(_quantity(run)), digit_sequence=False))
        i = j
    return spans
