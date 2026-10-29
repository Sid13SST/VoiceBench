"""Keyword and gazetteer tables for the rule-based matcher.

Surface forms are written already normalised (lower case, no punctuation).
Each canonical value lists English, Devanagari and romanised-Hindi forms that
a caller, or an ASR model, might produce.

These tables were written in the same week as scenarios/v1.jsonl and by the
same author, so they cover the v1 vocabulary by design. Scores on v1 show how
much ASR errors hurt a matcher that understands the clean text. They do not
show how well the matcher would generalise to new callers.
"""

from __future__ import annotations

# Intent keywords: (phrase, weight). A phrase ending in "*" matches any token
# that starts with it (भेज* matches भेज, भेजो, भेजना).
INTENT_KEYWORDS: dict[str, list[tuple[str, int]]] = {
    # banking
    "check_balance": [("balance", 3), ("बैलेंस", 3), ("बकाया", 3), ("kitna paisa", 2)],
    "transfer_money": [
        ("transfer", 3), ("ट्रांसफर", 3), ("send", 2), ("भेज*", 2), ("bhej*", 2), ("pay to", 2),
    ],
    "block_card": [
        ("block", 3), ("ब्लॉक", 3), ("ब्लाक", 3), ("lost", 1), ("stolen", 1), ("चोरी", 1),
        ("chori", 1), ("खो", 1),
    ],
    "report_fraud": [
        ("fraud", 4), ("धोखाधड़ी", 4), ("धोखा*", 4), ("dhokha*", 4), ("फ्रॉड", 4),
        ("unauthori*", 3), ("बिना बताए", 2), ("कट गए", 2), ("kat gaye", 2), ("deducted", 2),
    ],
    # food
    "order_food": [
        ("want to order", 2), ("order करना", 2), ("order karna", 2), ("ऑर्डर करना", 2),
        ("चाहिए", 1), ("chahiye", 1), ("मँगवा*", 2), ("मंगवा*", 2), ("mangwa*", 2),
        ("can i get", 2), ("i want", 1), ("plates", 1),
    ],
    "track_order": [
        ("where is", 3), ("कहाँ", 3), ("कहां", 3), ("kahan", 3), ("track", 3), ("status", 2),
        ("स्टेटस", 2), ("नहीं आया", 3), ("nahi aaya", 3), ("not arrived", 3),
    ],
    "cancel_order": [("cancel", 4), ("कैंसल", 4), ("रद्द", 4), ("radd", 4)],
    # travel
    "book_ticket": [("book", 3), ("बुक", 3), ("ticket", 2), ("टिकट", 2), ("tickets", 2)],
    "cancel_booking": [("cancel", 4), ("कैंसल", 4), ("रद्द", 4), ("radd", 4)],
    "check_pnr_status": [("pnr", 4), ("पीएनआर", 4), ("p n r", 4), ("status", 2), ("स्टेटस", 2)],
    # support
    "reset_password": [
        ("password", 3), ("पासवर्ड", 3), ("reset", 2), ("रीसेट", 2), ("forgot", 1), ("भूल", 1),
    ],
    "report_issue": [
        ("not working", 2), ("काम नहीं", 2), ("kaam nahi", 2), ("नहीं चल", 2), ("नहीं हो रहा", 1),
        ("nahi ho raha", 1), ("problem", 2), ("समस्या", 2), ("दिक्कत", 2), ("failed", 2),
        ("नहीं आ रहा", 2), ("nahi aa raha", 2),
    ],
    "talk_to_agent": [
        ("agent", 3), ("एजेंट", 3), ("human", 3), ("इंसान", 3), ("insaan", 3), ("customer care", 3),
        ("कस्टमर केयर", 3), ("real person", 3), ("बात करनी", 2), ("baat karni", 2),
    ],
}

# Slot gazetteers: canonical value -> surface forms.
ACCOUNT_TYPES = {
    "savings": ["savings", "saving", "सेविंग्स", "सेविंग", "बचत", "bachat"],
    "current": ["current", "करंट", "चालू", "chalu"],
}
CARD_TYPES = {
    "debit": ["debit", "डेबिट"],
    "credit": ["credit", "क्रेडिट"],
}
# The bank's saved beneficiaries for this (fictional) caller.
BENEFICIARIES = {
    "rahul": ["rahul", "राहुल"],
    "priya": ["priya", "प्रिया"],
    "amit": ["amit", "अमित"],
    "neha": ["neha", "नेहा"],
    "vikram": ["vikram", "विक्रम"],
}
# The restaurant's menu.
MENU = {
    "veg biryani": ["veg biryani", "वेज बिरयानी", "veg biriyani", "vegetable biryani"],
    "masala dosa": ["masala dosa", "मसाला डोसा", "masala dosai"],
    "paneer butter masala": ["paneer butter masala", "पनीर बटर मसाला"],
    "margherita pizza": ["margherita pizza", "margarita pizza", "मार्गरीटा पिज़्ज़ा", "मार्गरिटा पिज़्ज़ा"],
}
TRAVEL_MODES = {
    "train": ["train", "ट्रेन", "रेल", "rail"],
    "bus": ["bus", "बस"],
    "flight": ["flight", "फ्लाइट", "फ़्लाइट", "हवाई जहाज", "plane"],
}
CITIES = {
    "delhi": ["delhi", "दिल्ली", "new delhi"],
    "mumbai": ["mumbai", "मुंबई", "मुम्बई", "bombay"],
    "jaipur": ["jaipur", "जयपुर"],
    "pune": ["pune", "पुणे"],
    "bengaluru": ["bengaluru", "bangalore", "बेंगलुरु", "बैंगलोर", "बेंगलुरू"],
    "lucknow": ["lucknow", "लखनऊ"],
    "kanpur": ["kanpur", "कानपुर"],
    "goa": ["goa", "गोवा"],
    "agra": ["agra", "आगरा"],
    "kolkata": ["kolkata", "कोलकाता", "calcutta"],
    "chennai": ["chennai", "चेन्नई", "madras"],
}
SOURCE_MARKERS_BEFORE = {"from"}  # "from delhi"
SOURCE_MARKERS_AFTER = {"से", "se"}  # "दिल्ली से"
# Words that introduce an id rather than an amount: "from account 1234".
ID_NUMBER_MARKERS = {
    "account", "acct", "खाता", "खाते", "अकाउंट", "एकाउंट", "khata", "khaata", "khate",
    "card", "कार्ड", "order", "ऑर्डर", "आर्डर", "pnr", "पीएनआर", "number", "नंबर", "नम्बर",
}
# Words between such a marker and the id: "card ending 4321", "card ending in 4321".
ID_NUMBER_ENDING = (("ending",), ("ending", "in"))
WEEKDAYS = {
    "monday": ["monday", "सोमवार", "somvar"],
    "tuesday": ["tuesday", "मंगलवार", "mangalvar"],
    "wednesday": ["wednesday", "बुधवार", "budhvar"],
    "thursday": ["thursday", "गुरुवार", "बृहस्पतिवार", "guruvar"],
    "friday": ["friday", "शुक्रवार", "shukravar"],
    "saturday": ["saturday", "शनिवार", "shanivar"],
    "sunday": ["sunday", "रविवार", "ravivar", "इतवार"],
    "today": ["today", "आज", "aaj"],
    # "कल" means both yesterday and tomorrow; in a booking it means tomorrow.
    "tomorrow": ["tomorrow", "कल", "kal"],
}
MONTHS = {
    "january": ["january", "जनवरी"], "february": ["february", "फरवरी", "फ़रवरी"],
    "march": ["march", "मार्च"], "april": ["april", "अप्रैल"], "may": ["may", "मई"],
    "june": ["june", "जून"], "july": ["july", "जुलाई"], "august": ["august", "अगस्त"],
    "september": ["september", "सितंबर", "सितम्बर"], "october": ["october", "अक्टूबर"],
    "november": ["november", "नवंबर", "नवम्बर"], "december": ["december", "दिसंबर", "दिसम्बर"],
}
DEVICES = {
    "app": ["app", "ऐप", "एप", "application"],
    "router": ["router", "राउटर", "wifi", "वाईफाई"],
    "laptop": ["laptop", "लैपटॉप", "लैपटाप"],
    "phone": ["phone", "फ़ोन", "फोन", "mobile", "मोबाइल"],
}
# Issue phrases (substring match on the normalised text).
ISSUES = {
    "payment failed": ["payment failed", "payment fail", "पेमेंट फेल", "भुगतान विफल"],
    "no internet": [
        "no internet", "internet not working", "internet नहीं", "इंटरनेट नहीं", "internet nahi",
    ],
    "not charging": ["not charging", "charge नहीं", "चार्ज नहीं", "charge nahi"],
    "not loading": ["not loading", "load नहीं", "लोड नहीं", "load nahi"],
}
