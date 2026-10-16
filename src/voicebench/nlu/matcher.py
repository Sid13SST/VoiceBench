"""Rule-based intent classifier and slot filler.

This stands in for the language-understanding part of a voice agent. It is
given the transcript and the business domain (an agent is deployed for one
business: a bank, a restaurant, a travel desk or a support line) and returns
an intent and slots in the canonical form used by the scenarios.

Rules, all of them deliberately simple:

- intent: sum the weights of the keywords found for each of the domain's
  intents (plus a boost when a menu item or an issue phrase is found); the
  highest score wins, ties go to the first-listed intent, and a zero score
  means no intent.
- most slots: the *last* mention wins, which handles self-corrections
  ("two thousand no sorry four thousand" -> 4000).
- device and issue: the first mention wins (the device named first is the
  subject: "my phone's app is not loading" -> phone).
- source city: the city after "from" or before "से"; destination: the last
  other city mentioned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from voicebench.nlu import lexicon as lx
from voicebench.nlu.numbers import NumberSpan, find_numbers
from voicebench.schema import INTENTS, Domain
from voicebench.textnorm import normalise

_DIGIT_GROUP_RE = re.compile(r"(?<=\d),(?=\d)")


@dataclass(frozen=True)
class Mention:
    start: int
    end: int
    value: str


@dataclass
class Prediction:
    intent: str | None
    slots: dict[str, str] = field(default_factory=dict)
    scores: dict[str, int] = field(default_factory=dict)


def _phrase_tokens(gazetteer: dict[str, list[str]]) -> list[tuple[list[str], str]]:
    forms = [(normalise(f).split(), canon) for canon, fs in gazetteer.items() for f in fs]
    return sorted(forms, key=lambda x: -len(x[0]))  # longest first


def find_mentions(tokens: list[str], gazetteer: dict[str, list[str]]) -> list[Mention]:
    """Non-overlapping gazetteer matches, left to right, longest form first."""
    forms = _phrase_tokens(gazetteer)
    out: list[Mention] = []
    i = 0
    while i < len(tokens):
        for form, canon in forms:
            if tokens[i : i + len(form)] == form:
                out.append(Mention(i, i + len(form), canon))
                i += len(form)
                break
        else:
            i += 1
    return out


def _has_phrase(tokens: list[str], phrase: str) -> bool:
    words = normalise(phrase.rstrip("*")).split()
    prefix = phrase.endswith("*")
    n = len(words)
    for i in range(len(tokens) - n + 1):
        window = tokens[i : i + n]
        if prefix:
            if window[:-1] == words[:-1] and window[-1].startswith(words[-1]):
                return True
        elif window == words:
            return True
    return False


def _first_phrase(text: str, phrases: dict[str, list[str]]) -> str | None:
    best: tuple[int, str] | None = None
    padded = f" {text} "
    for canon, forms in phrases.items():
        for form in forms:
            pos = padded.find(f" {normalise(form)} ")
            if pos >= 0 and (best is None or pos < best[0]):
                best = (pos, canon)
    return best[1] if best else None


def classify(tokens: list[str], domain: Domain, text: str) -> tuple[str | None, dict[str, int]]:
    scores: dict[str, int] = {}
    has_item = bool(find_mentions(tokens, lx.MENU))
    has_issue = _first_phrase(text, lx.ISSUES) is not None
    for intent in INTENTS[domain]:
        score = sum(w for phrase, w in lx.INTENT_KEYWORDS[intent] if _has_phrase(tokens, phrase))
        if intent == "order_food" and has_item:
            score += 2
        if intent == "report_issue" and has_issue:
            score += 2
        scores[intent] = score
    best = max(scores.values(), default=0)
    if best == 0:
        return None, scores
    return next(i for i, s in scores.items() if s == best), scores


def _last(mentions: list[Mention]) -> str | None:
    return mentions[-1].value if mentions else None


def _cities(tokens: list[str]) -> tuple[str | None, str | None]:
    mentions = find_mentions(tokens, lx.CITIES)
    source = None
    for m in mentions:
        before = tokens[m.start - 1] if m.start > 0 else None
        after = tokens[m.end] if m.end < len(tokens) else None
        if before in lx.SOURCE_MARKERS_BEFORE or after in lx.SOURCE_MARKERS_AFTER:
            source = m.value
            break
    others = [m for m in mentions if m.value != source]
    return source, (others[-1].value if others else None)


def _date(tokens: list[str], numbers: list[NumberSpan]) -> str | None:
    found: list[tuple[int, str]] = [(m.start, m.value) for m in find_mentions(tokens, lx.WEEKDAYS)]
    by_end = {n.end: n for n in numbers}
    for m in find_mentions(tokens, lx.MONTHS):
        n = by_end.get(m.start)
        if n and 1 <= int(n.value) <= 31:
            found.append((n.start, f"{int(n.value)} {m.value}"))
    return max(found)[1] if found else None


def extract_slots(intent: str, domain: Domain, tokens: list[str], text: str) -> dict[str, str]:
    allowed = INTENTS[domain][intent]
    numbers = find_numbers(tokens)
    slots: dict[str, str | None] = {}

    if "amount" in allowed:
        slots["amount"] = numbers[-1].value if numbers else None
    if "recipient" in allowed:
        slots["recipient"] = _last(find_mentions(tokens, lx.BENEFICIARIES))
    if "account_type" in allowed:
        slots["account_type"] = _last(find_mentions(tokens, lx.ACCOUNT_TYPES))
    if "card_type" in allowed:
        slots["card_type"] = _last(find_mentions(tokens, lx.CARD_TYPES))
    if "item" in allowed:
        slots["item"] = _last(find_mentions(tokens, lx.MENU))
    if "quantity" in allowed:
        qty = [n for n in numbers if not n.digit_sequence and 1 <= int(n.value) <= 50]
        slots["quantity"] = qty[-1].value if qty else None
    if "order_id" in allowed:
        ids = [n for n in numbers if n.digit_sequence and len(n.value) >= 3]
        slots["order_id"] = ids[-1].value if ids else None
    if "pnr" in allowed:
        pnrs = [n for n in numbers if n.digit_sequence and len(n.value) == 10]
        slots["pnr"] = pnrs[-1].value if pnrs else None
    if "mode" in allowed:
        slots["mode"] = _last(find_mentions(tokens, lx.TRAVEL_MODES))
    if "source" in allowed or "destination" in allowed:
        source, destination = _cities(tokens)
        if "source" in allowed:
            slots["source"] = source
        if "destination" in allowed:
            slots["destination"] = destination
    if "date" in allowed:
        slots["date"] = _date(tokens, numbers)
    if "device" in allowed:
        dev = find_mentions(tokens, lx.DEVICES)
        slots["device"] = dev[0].value if dev else None
    if "issue" in allowed:
        slots["issue"] = _first_phrase(text, lx.ISSUES)

    return {k: v for k, v in slots.items() if v is not None}


def match(transcript: str, domain: Domain | str) -> Prediction:
    domain = Domain(domain)
    text = normalise(_DIGIT_GROUP_RE.sub("", transcript))
    tokens = text.split()
    intent, scores = classify(tokens, domain, text)
    slots = extract_slots(intent, domain, tokens, text) if intent else {}
    return Prediction(intent=intent, slots=slots, scores=scores)
