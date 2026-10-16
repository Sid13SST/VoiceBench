from pathlib import Path

import pytest

from voicebench.loader import load_scenarios
from voicebench.nlu.matcher import find_mentions, match
from voicebench.nlu import lexicon as lx
from voicebench.textnorm import tokens


@pytest.mark.parametrize(
    "text, domain, intent, slots",
    [
        # Whisper-style output: digits, capitals, punctuation
        ("Please send Rs. 5,000 to Rahul.", "banking", "transfer_money", {"amount": "5000", "recipient": "rahul"}),
        ("Transfer ₹1500 to Amit", "banking", "transfer_money", {"amount": "1500", "recipient": "amit"}),
        # romanised Hindi
        ("rahul ko paanch hazaar bhej do", "banking", "transfer_money", {"amount": "5000", "recipient": "rahul"}),
        ("mera bachat khate ka balance batao", "banking", "check_balance", {"account_type": "savings"}),
        ("मेरा क्रेडिट कार्ड खो गया है ब्लॉक करो", "banking", "block_card", {"card_type": "credit"}),
        ("someone did a fraud of twenty thousand on my account", "banking", "report_fraud", {"amount": "20000"}),
        # food
        ("Order number 4821, where is it?", "food", "track_order", {"order_id": "4821"}),
        ("I want two masala dosa", "food", "order_food", {"item": "masala dosa", "quantity": "2"}),
        ("cancel my order 7310", "food", "cancel_order", {"order_id": "7310"}),
        # travel
        ("Book a flight from Bangalore to Delhi on Friday", "travel", "book_ticket",
         {"mode": "flight", "source": "bengaluru", "destination": "delhi", "date": "friday"}),
        ("मुंबई से पुणे की ट्रेन कल के लिए बुक करो", "travel", "book_ticket",
         {"mode": "train", "source": "mumbai", "destination": "pune", "date": "tomorrow"}),
        ("cancel my bus on 5 march", "travel", "cancel_booking", {"mode": "bus", "date": "5 march"}),
        ("PNR 4521378690 status", "travel", "check_pnr_status", {"pnr": "4521378690"}),
        # support
        ("My laptop is not charging", "support", "report_issue", {"device": "laptop", "issue": "not charging"}),
        ("I want to talk to a human", "support", "talk_to_agent", {}),
    ],
)
def test_match_variants(text, domain, intent, slots):
    p = match(text, domain)
    assert p.intent == intent
    for key, value in slots.items():
        assert p.slots.get(key) == value, (key, p.slots)


def test_self_correction_last_mention_wins():
    p = match("send two thousand no sorry four thousand to vikram", "banking")
    assert p.slots["amount"] == "4000"
    p = match("debit card नहीं क्रेडिट कार्ड ब्लॉक करो", "banking")
    assert p.slots["card_type"] == "credit"
    p = match("book a train from delhi to jaipur no no agra", "travel")
    assert (p.slots["source"], p.slots["destination"]) == ("delhi", "agra")


def test_no_keywords_gives_no_intent_and_no_slots():
    p = match("hello hello can you hear me", "banking")
    assert p.intent is None and p.slots == {}
    assert match("", "food").intent is None


def test_domain_limits_intents():
    # "cancel" maps to cancel_order in food and cancel_booking in travel
    assert match("cancel it", "food").intent == "cancel_order"
    assert match("cancel it", "travel").intent == "cancel_booking"


def test_slots_restricted_to_intent():
    p = match("block my debit card i sent 5000 to rahul", "banking")
    assert p.intent == "block_card"
    assert set(p.slots) <= {"card_type"}


def test_find_mentions_prefers_longest_form():
    m = find_mentions(tokens("new delhi to mumbai"), lx.CITIES)
    assert [(x.start, x.end, x.value) for x in m] == [(0, 2, "delhi"), (3, 4, "mumbai")]


def test_unparseable_slot_is_omitted_not_guessed():
    p = match("transfer some money to rahul", "banking")
    assert "amount" not in p.slots and p.slots["recipient"] == "rahul"


V1 = Path(__file__).resolve().parents[1] / "scenarios" / "v1.jsonl"


def test_lexicon_covers_every_v1_reference():
    """Coverage check, not an accuracy claim: the lexicon was written for v1.

    If the matcher cannot read the *reference* text, an ASR-driven failure on
    that scenario could not be told apart from a matcher gap.
    """
    misses = []
    for s in load_scenarios(V1):
        p = match(s.reference, s.domain)
        if p.intent != s.expected_intent or any(p.slots.get(k) != v for k, v in s.expected_slots.items()):
            misses.append((s.id, p.intent, p.slots))
    assert misses == []
