"""Text normalisation used before computing WER and matching intents.

Kept deliberately small and explicit so the WER numbers are easy to
interpret: Unicode NFC, lower case, punctuation (including the Devanagari
danda) replaced by spaces, whitespace collapsed. Numbers are *not* rewritten,
so "5000" vs "five thousand" counts as a word error. Scripts are not
transliterated, so "बैलेंस" vs "balance" counts as an error. Both are
reported separately (see ``script_profile``) instead of being hidden.
"""

from __future__ import annotations

import re
import unicodedata

_PUNCT_RE = re.compile(r"[^\w\s]|_", re.UNICODE)
_DANDA_RE = re.compile(r"[।॥]")  # । ॥
_DEV_RE = re.compile(r"[ऀ-ॿ]")
_LAT_RE = re.compile(r"[a-z]")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = _DANDA_RE.sub(" ", text)
    out = []
    for ch in text:
        if unicodedata.category(ch).startswith("M"):
            out.append(ch)  # vowel signs, virama, nukta, anusvara...
        elif _PUNCT_RE.match(ch):
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())


_NUKTA = "\u093c"
_CANDRABINDU, _ANUSVARA = "\u0901", "\u0902"


def fold_spelling_variants(text: str) -> str:
    """Drop the nukta and write chandrabindu as anusvara: "बड़ी" -> "बडी", "हूँ" -> "हूं".

    For matching words, not for WER (``normalise`` keeps both marks, so WER
    still counts these as errors). On real Hindi speech (FLEURS hi_in),
    Whisper small writes the nukta of an otherwise correct word far less
    often than it drops it, and uses anusvara where references use
    chandrabindu, so a keyword list has to accept both spellings. Folding
    both sides does that without listing every variant by hand. Expects
    NFC text, where a nukta letter such as ज़ is ज + U+093C.
    """
    return text.replace(_NUKTA, "").replace(_CANDRABINDU, _ANUSVARA)


def tokens(text: str) -> list[str]:
    return normalise(text).split()


def script_profile(text: str) -> str:
    """'devanagari', 'latin', 'mixed', 'other' or 'none', judged per word.

    'other' is any other script with letters: Whisper once answered a Hindi
    clip in Telugu script, which should not be hidden in 'none' ('none'
    keeps meaning no letters at all, e.g. an empty or digits-only transcript).
    """
    dev = lat = other = 0
    for word in tokens(text):
        if _DEV_RE.search(word):
            dev += 1
        elif _LAT_RE.search(word):
            lat += 1
        elif any(c.isalpha() for c in word):
            other += 1
    if dev and lat:
        return "mixed"
    if dev:
        return "devanagari"
    if lat:
        return "latin"
    if other:
        return "other"
    return "none"
