import numpy as np
import pytest

from voicebench.audio.tts import EspeakTTS, TTSUnavailable

tts = EspeakTTS()
needs_espeak = pytest.mark.skipif(not tts.available(), reason="espeak-ng not installed")


def test_voice_mapping():
    assert tts.voice_for("en") == "en-us"
    assert tts.voice_for("hi") == "hi"
    assert tts.voice_for("hi-en") == "hi"
    assert tts.voice_for("en", agent=True) == "en-us+f3"
    with pytest.raises(ValueError):
        tts.voice_for("fr")


def test_missing_binary_raises_clear_error():
    with pytest.raises(TTSUnavailable, match="not found"):
        EspeakTTS(binary="definitely-not-espeak").synthesize("hello", "en-us")


def test_empty_text_rejected():
    with pytest.raises(ValueError):
        tts.synthesize("  ", "en-us")


@needs_espeak
def test_version_string():
    assert tts.version().startswith("espeak-ng ")


@needs_espeak
@pytest.mark.parametrize("text, voice", [("check my balance", "en-us"), ("मेरा बैलेंस बताइए", "hi"), ("मेरा credit card block करो", "hi")])
def test_synthesis_is_nonsilent_and_deterministic(text, voice):
    a = tts.synthesize(text, voice)
    b = tts.synthesize(text, voice)
    assert a.dtype == np.float32
    assert 0.3 < len(a) / 16_000 < 10
    assert np.max(np.abs(a)) > 0.05
    np.testing.assert_array_equal(a, b)
