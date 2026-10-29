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
    assert asr.languages == [None, "en", "hi", "en"]  # first call is the untimed warm-up
    asr = ScriptedTranscriber(texts)
    run(scenarios, audio, asr, str(sfile), "pytest", source=FIX)
    assert asr.languages == [None, None, None, None]
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


def test_rescore_keeps_transcripts_and_links_back(setup):
    from voicebench.runner import rescore

    scenarios, sfile, audio = setup
    asr = ScriptedTranscriber({
        "v1-001": "please send five thousand rupees to rahul",
        "v1-002": "राहुल को पाँच हज़ार रुपये भेजो",
        "v1-003": RuntimeError("decoder crashed"),
    })
    first = run(scenarios, audio, asr, str(sfile), "t", source=FIX)
    # Simulate a stale score from older matcher code.
    stale = first.model_copy(update={"results": [
        first.results[0].model_copy(update={"task_success": False, "slots_correct": False}),
        *first.results[1:],
    ]})
    again = rescore(stale, scenarios, "voicebench rescore x")
    assert again.rescored_from == first.run_id
    assert again.run_id.startswith(first.run_id + "-rescored-")
    assert [r.transcript for r in again.results] == [r.transcript for r in first.results]
    assert again.results[0].task_success is True  # recomputed
    assert again.results[0].latency_ms == first.results[0].latency_ms
    assert again.results[2].error == "RuntimeError: decoder crashed"  # errors kept as they were


def test_warmup_cost_and_hardware_recorded(setup):
    scenarios, sfile, audio = setup

    class Costed(ScriptedTranscriber):
        cost_note = "test pricing"

        def cost_usd(self, audio_duration_s):
            return 0.5 * audio_duration_s

    asr = Costed({s.id: s.reference for s in scenarios})
    m = run(scenarios, audio, asr, str(sfile), "t", source=FIX)
    assert m.warmup_runs == 1
    assert len(asr.languages) == len(scenarios) + 1
    assert len(m.results) == len(scenarios)  # warm-up output is discarded
    assert [r.cost_usd for r in m.results] == [0.5, 0.5, 0.5]
    assert m.cost_note == "test pricing"
    assert m.wall_time_s is not None and m.wall_time_s >= 0
    assert {"cpu", "logical_cpus", "ram_gb", "os", "python"} <= set(m.hardware)


def test_failed_warmup_does_not_abort_run(setup):
    scenarios, sfile, audio = setup
    asr = ScriptedTranscriber({"v1-001": RuntimeError("bad file"), "v1-002": "x", "v1-003": "y"})
    m = run(scenarios, audio, asr, str(sfile), "t", source=FIX)
    assert m.warmup_runs == 0
    assert m.results[0].error == "RuntimeError: bad file"


def test_oracle_run_has_no_warmup_or_cost(setup):
    scenarios, sfile, audio = setup
    m = run(scenarios, audio, ReferenceTranscriber(), str(sfile), "t", source=FIX)
    assert m.warmup_runs == 0 and m.cost_note is None
    assert all(r.cost_usd is None and r.latency_ms is None for r in m.results)


def _score_failing_on(failing_id):
    from voicebench import runner

    real = runner.score

    def score(s, *args, **kwargs):
        if s.id == failing_id:
            raise ValueError("boom")
        return real(s, *args, **kwargs)

    return score


def test_scoring_error_is_recorded_and_other_scenarios_complete(setup, monkeypatch):
    scenarios, sfile, audio = setup
    monkeypatch.setattr("voicebench.runner.score", _score_failing_on("v1-002"))
    asr = ScriptedTranscriber({
        "v1-001": "send ² thousand to rahul",  # used to raise inside the matcher
        "v1-002": "राहुल को पाँच हज़ार रुपये भेजो",
        "v1-003": "please block my credit card",
    })
    m = run(scenarios, audio, asr, str(sfile), "pytest", source=FIX)
    by_id = {r.scenario_id: r for r in m.results}
    assert [r.scenario_id for r in m.results] == ["v1-001", "v1-002", "v1-003"]
    assert by_id["v1-001"].error is None and by_id["v1-001"].predicted_intent == "transfer_money"
    assert by_id["v1-002"].error == "ValueError: boom" and by_id["v1-002"].task_success is False
    assert by_id["v1-003"].task_success is True


def test_scenario_with_empty_normalised_reference_fails_alone(setup):
    scenarios, sfile, audio = setup
    # Validation now rejects such a reference; build one past it to check the runner.
    bad = Scenario.model_construct(**{**scenarios[0].model_dump(), "reference": "?!"})
    m = run([bad, scenarios[2]], audio, ReferenceTranscriber(), str(sfile), "pytest", source=FIX)
    assert m.results[0].error == "ValueError: reference is empty after normalisation"
    assert m.results[1].task_success is True


def test_rescore_records_a_scoring_error_and_continues(setup, monkeypatch):
    from voicebench.runner import rescore

    scenarios, sfile, audio = setup
    asr = ScriptedTranscriber({s.id: s.reference for s in scenarios})
    first = run(scenarios, audio, asr, str(sfile), "t", source=FIX)
    monkeypatch.setattr("voicebench.runner.score", _score_failing_on("v1-002"))
    again = rescore(first, scenarios, "voicebench rescore x")
    assert [r.error for r in again.results] == [None, "ValueError: boom", None]
    assert again.results[0].task_success and again.results[2].task_success
