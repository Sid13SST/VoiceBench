"""Runner tests. Fake transcribers produce fixture results only."""

import json
from pathlib import Path

import numpy as np
import pytest

from conftest import make_scenario
from voicebench.asr import ASRUnavailable, Transcript
from voicebench.audio.signal import write_wav
from voicebench.cli import main
from voicebench.report import format_table, summarise
from voicebench.runner import ReferenceTranscriber, load_run, run, save
from voicebench.schema import ResultSource, Scenario

FIX = ResultSource.FIXTURE
ROOT = Path(__file__).resolve().parents[1]


class ScriptedTranscriber:
    """Returns fixed text per file name; records the language it was given."""

    name = "scripted"

    def __init__(self, texts):
        self.texts = texts
        self.languages = []

    def describe(self):
        return {"name": self.name, "backend": "fixture", "device": "none"}

    def transcribe_file(self, path, language=None):
        self.languages.append(language)
        text = self.texts[Path(path).stem]
        if isinstance(text, Exception):
            raise text
        return Transcript(text, self.name, "en", 1.0, language, latency_ms=12.5, audio_duration_s=1.0)


@pytest.fixture
def setup(tmp_path):
    rows = [
        make_scenario(id="v1-001"),
        make_scenario(id="v1-002", language="hi", reference="राहुल को पाँच हज़ार रुपये भेजो",
                      condition="noise", snr_db=5, noise_type="white"),
        make_scenario(id="v1-003", reference="please block my credit card", expected_intent="block_card",
                      expected_slots={"card_type": "credit"}),
    ]
    sfile = tmp_path / "v1.jsonl"
    sfile.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    audio = tmp_path / "audio"
    for r in rows:
        write_wav(audio / f"{r['id']}.wav", np.zeros(1600, np.float32))
    return [Scenario.model_validate(r) for r in rows], sfile, audio


def test_run_scores_each_scenario(setup):
    scenarios, sfile, audio = setup
    asr = ScriptedTranscriber({
        "v1-001": "please send five thousand rupees to rahul",
        "v1-002": "rahul ko paanch hazaar",  # intent keyword lost
        "v1-003": RuntimeError("decoder crashed"),
    })
    m = run(scenarios, audio, asr, str(sfile), "pytest", source=FIX)
    by_id = {r.scenario_id: r for r in m.results}
    assert by_id["v1-001"].task_success and by_id["v1-001"].latency_ms == 12.5
    assert not by_id["v1-002"].task_success and by_id["v1-002"].predicted_intent is None
    assert by_id["v1-003"].error == "RuntimeError: decoder crashed" and by_id["v1-003"].task_success is False
    assert m.source is FIX and m.language_policy == "auto"
    assert m.scenarios_sha256 and m.asr_model == "scripted"


def test_language_policy(setup):
    scenarios, sfile, audio = setup
    texts = {s.id: s.reference for s in scenarios}
    asr = ScriptedTranscriber(texts)
    run(scenarios, audio, asr, str(sfile), "pytest", source=FIX, language_policy="hint")
    assert asr.languages == ["en", "hi", "en"]
    asr = ScriptedTranscriber(texts)
    run(scenarios, audio, asr, str(sfile), "pytest", source=FIX)
    assert asr.languages == [None, None, None]
    with pytest.raises(ValueError):
        run(scenarios, audio, asr, str(sfile), "pytest", language_policy="guess")


def test_missing_audio_is_a_per_scenario_error(setup):
    scenarios, sfile, audio = setup
    (audio / "v1-002.wav").unlink()
    m = run(scenarios, audio, ScriptedTranscriber({s.id: s.reference for s in scenarios}), str(sfile), "t", source=FIX)
    assert "missing audio" in m.results[1].error


def test_asr_unavailable_aborts_run(setup):
    scenarios, sfile, audio = setup

    class Broken(ScriptedTranscriber):
        def transcribe_file(self, path, language=None):
            raise ASRUnavailable("no weights")

    with pytest.raises(ASRUnavailable):
        run(scenarios, audio, Broken({}), str(sfile), "t", source=FIX)


def test_save_load_and_summarise(setup, tmp_path):
    scenarios, sfile, audio = setup
    asr = ScriptedTranscriber({
        "v1-001": "please send five thousand rupees to rahul",
        "v1-002": "राहुल को पाँच हज़ार रुपये भेजो",
        "v1-003": "please block my debit card",
    })
    m = run(scenarios, audio, asr, str(sfile), "t", source=FIX)
    path = save(m, tmp_path / "results")
    again = load_run(path)
    assert again == m
    s = summarise(again, scenarios)
    assert s["overall"]["n"] == 3 and s["overall"]["task_success"] == 2
    assert s["by_language"]["en"]["task_success"] == 1
    assert s["by_condition"]["noise"]["corpus_wer"] == 0.0
    assert s["overall"]["corpus_wer"] == pytest.approx(1 / 18)  # 1 sub over 7 + 6 + 5 reference words
    assert "fixture" in format_table(s)


def test_oracle_run_on_v1_end_to_end(tmp_path, capsys):
    """Pipeline check on the real scenario file with reference text as input."""
    code = main(["run", "--asr", "oracle", "--scenarios", str(ROOT / "scenarios" / "v1.jsonl"),
                 "--audio", str(ROOT / "audio" / "v1"), "--out", str(tmp_path), "--command", "pytest"])
    assert code == 0
    out = capsys.readouterr().out
    assert "oracle-reference" in out
    saved = list(tmp_path.glob("*.json"))
    assert len(saved) == 1
    m = load_run(saved[0])
    assert len(m.results) == 50 and all(r.wer == 0 for r in m.results)
    assert main(["report", str(saved[0])]) == 0


def test_cli_run_reports_unavailable_model(tmp_path, capsys):
    pytest.importorskip("faster_whisper")
    code = main(["run", "--model", str(tmp_path / "missing"), "--offline",
                 "--scenarios", str(ROOT / "scenarios" / "v1.jsonl"), "--audio", str(ROOT / "audio" / "v1"),
                 "--out", str(tmp_path / "r")])
    assert code == 2
    assert not (tmp_path / "r").exists()
