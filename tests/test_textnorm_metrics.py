import pytest

from voicebench.metrics import corpus_wer, percentile, wer
from voicebench.textnorm import normalise, script_profile, tokens


def test_normalise_basic():
    assert normalise("  Hello, World!  ") == "hello world"
    assert normalise("मेरा ऑर्डर कहाँ है?") == "मेरा ऑर्डर कहाँ है"
    assert normalise("ठीक है। धन्यवाद॥") == "ठीक है धन्यवाद"


def test_normalise_keeps_devanagari_marks():
    # virama, nukta and vowel signs are combining marks and must survive
    word = "क्रेडिट"
    assert normalise(word) == word
    assert tokens("ज़रूर, हाँ") == ["ज़रूर", "हाँ"]


def test_normalise_nfc():
    decomposed = "क़"  # ka + nukta
    assert normalise(decomposed) == normalise("क़")


def test_script_profile():
    assert script_profile("send money") == "latin"
    assert script_profile("पैसे भेजो") == "devanagari"
    assert script_profile("मेरा credit card") == "mixed"
    assert script_profile("1234 !!") == "none"
    # Whisper once answered a Hindi clip in Telugu script: not hidden in "none"
    assert script_profile("నినినినినిని") == "other"


@pytest.mark.parametrize(
    "ref, hyp, expected",
    [
        ("send money to rahul", "send money to rahul", 0.0),
        ("send money to rahul", "Send money, to Rahul.", 0.0),
        ("send money to rahul", "send money rahul", 0.25),       # 1 deletion
        ("send money to rahul", "send the money to rahul", 0.25),  # 1 insertion
        ("send money to rahul", "send honey to rahul", 0.25),    # 1 substitution
        ("send money to rahul", "", 1.0),
        ("five thousand", "5000", 1.0),                          # numbers not rewritten
        ("a b", "x y z w", 2.0),                                  # can exceed 1
        ("मेरा बैलेंस बताइए", "मेरा balance बताइए", 1 / 3),       # script not transliterated
    ],
)
def test_wer(ref, hyp, expected):
    assert wer(ref, hyp) == pytest.approx(expected)


def test_wer_rejects_empty_reference():
    with pytest.raises(ValueError):
        wer("  ...", "hello")


def test_corpus_wer_is_edit_weighted():
    # 1 error in 4 words + 0 errors in 1 word = 1/5, not mean(0.25, 0) = 0.125
    assert corpus_wer([("a b c d", "a b c x"), ("e", "e")]) == pytest.approx(0.2)
    assert corpus_wer([("a b c", "")]) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        corpus_wer([])


def test_percentile_nearest_rank():
    xs = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert percentile(xs, 50) == 50
    assert percentile(xs, 95) == 100
    assert percentile(xs, 0) == 10
    assert percentile([], 50) is None
    with pytest.raises(ValueError):
        percentile(xs, 101)


def test_latency_stats_nearest_rank_and_rtf():
    from voicebench.report import latency_stats
    from voicebench.schema import ScenarioResult

    def r(i, lat, dur):
        return ScenarioResult(scenario_id=f"v1-{i:03d}", scenario_version="v1", source="fixture",
                              latency_ms=lat, audio_duration_s=dur)

    results = [r(i, 1000.0 * i, 2.0) for i in range(1, 21)] + [r(21, None, 2.0), r(22, 500.0, None)]
    s = latency_stats(results)
    assert s["n_timed"] == 20  # untimed and zero-duration items are skipped
    assert s["latency_p50_ms"] == 10_000 and s["latency_p95_ms"] == 19_000
    assert s["rtf_p50"] == 5.0 and s["rtf_p95"] == 9.5
    assert latency_stats([])["latency_p50_ms"] is None
