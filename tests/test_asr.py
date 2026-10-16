import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from voicebench.asr import WHISPER_LANGUAGE_HINT, ASRUnavailable, FasterWhisperTranscriber


class FakeWhisper:
    """Mimics faster_whisper.WhisperModel.transcribe: lazy segments + info."""

    def __init__(self, texts, language="hi", prob=0.9):
        self.texts, self.language, self.prob = texts, language, prob
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        segments = (SimpleNamespace(text=t) for t in self.texts)
        return segments, SimpleNamespace(language=kwargs["language"] or self.language, language_probability=self.prob)


def test_joins_segments_and_reports_metadata():
    fake = FakeWhisper([" मेरा debit card ", "block करो "])
    asr = FasterWhisperTranscriber("small", _model=fake)
    t = asr.transcribe(np.zeros(32_000, np.float32))
    assert t.text == "मेरा debit card block करो"
    assert t.detected_language == "hi"
    assert t.requested_language is None
    assert t.audio_duration_s == pytest.approx(2.0)
    assert t.latency_ms >= 0
    assert t.model == "faster-whisper/small"


def test_decoding_is_deterministic_and_language_is_passed():
    fake = FakeWhisper(["hello"])
    FasterWhisperTranscriber("small", beam_size=3, _model=fake).transcribe(np.zeros(16_000, np.float32), language="en")
    call = fake.calls[0]
    assert call["language"] == "en"
    assert call["temperature"] == 0.0
    assert call["beam_size"] == 3


def test_empty_output_is_empty_string():
    t = FasterWhisperTranscriber("small", _model=FakeWhisper([])).transcribe(np.zeros(100, np.float32))
    assert t.text == ""


def test_language_hint_mapping():
    assert WHISPER_LANGUAGE_HINT == {"en": "en", "hi": "hi", "hi-en": "hi"}


def test_describe_records_versions():
    d = FasterWhisperTranscriber("small", compute_type="int8").describe()
    assert d["backend"] == "faster-whisper"
    assert d["model"] == "small" and d["compute_type"] == "int8"


def test_unloadable_model_raises_asr_unavailable(tmp_path):
    pytest.importorskip("faster_whisper")
    asr = FasterWhisperTranscriber(str(tmp_path / "no-such-model"), local_files_only=True)
    with pytest.raises(ASRUnavailable, match="could not load"):
        asr.transcribe(np.zeros(16_000, np.float32))


# Real-model smoke test. Runs only when VOICEBENCH_ASR_MODEL names a model that
# loads (a local CTranslate2 directory, or a name already in the HF cache).
REAL_MODEL = os.environ.get("VOICEBENCH_ASR_MODEL")


@pytest.mark.skipif(not REAL_MODEL, reason="set VOICEBENCH_ASR_MODEL to run the real-model smoke test")
def test_real_model_transcribes_an_english_clip():
    asr = FasterWhisperTranscriber(REAL_MODEL, local_files_only=True)
    wav = Path(__file__).resolve().parents[1] / "audio" / "v1" / "v1-002.wav"
    t = asr.transcribe_file(wav, language="en")
    assert t.text  # content is checked by the scoring stage, not here


def test_cli_transcribe_reports_unavailable_model(tmp_path, capsys):
    pytest.importorskip("faster_whisper")
    from voicebench.cli import main

    wav = Path(__file__).resolve().parents[1] / "audio" / "v1" / "v1-002.wav"
    code = main(["transcribe", str(wav), "--model", str(tmp_path / "missing"), "--offline"])
    assert code == 2
    assert "could not load" in capsys.readouterr().err


def test_model_revision_is_none_for_local_dir(tmp_path):
    assert FasterWhisperTranscriber(str(tmp_path)).describe()["model_revision"] is None
