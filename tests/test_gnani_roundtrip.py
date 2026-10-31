"""TTS + STT round trip with mocks: orchestration, scoring against the reference, audio manifest. Offline."""

import hashlib
import json
from pathlib import Path

import pytest

from gnani_mock import MockGnani, fixture, make_client, wav_bytes
from voicebench.gnani import lanes
from voicebench.gnani.budget import Budget, BudgetExceeded, GnaniRunAborted
from voicebench.gnani.roundtrip import GnaniRoundTripTranscriber
from voicebench.loader import load_scenarios
from voicebench.report import format_table, summarise
from voicebench.runner import save

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "scenarios" / "v1.jsonl"


def _echo_stt(texts):
    """STT replies that give back the reference of each scenario in turn (a perfect round trip)."""
    replies = [(200, {**fixture("stt_ok_v3.json"), "transcript": t}) for t in texts]
    return replies


def _setup(tmp_path, ids, stt=None, tts=None, cap=10):
    scenarios = load_scenarios(SCENARIOS)
    picked = lanes.pick_scenarios(scenarios, lanes.items_for("roundtrip", cap), ids)
    mock = MockGnani(stt=stt or _echo_stt([s.reference for s in picked]), tts=tts)
    t = GnaniRoundTripTranscriber(make_client(mock), Budget(cap), tmp_path / "cache")
    return scenarios, picked, mock, t


def test_roundtrip_orchestration(tmp_path):
    scenarios, picked, mock, t = _setup(tmp_path, ["v1-002", "v1-011", "v1-021"])
    langs = [s.language.value for s in picked]
    assert langs == ["en", "hi", "hi-en"]
    m = lanes.run_roundtrip(t, picked, len(scenarios), str(SCENARIOS), "pytest")
    # one TTS and one STT request per scenario, no warm-up call
    assert mock.count("/api/v1/tts/inference") == 3 and mock.count("/stt/v3") == 3 and m.warmup_runs == 0
    tts_bodies = [json.loads(r.content) for r in mock.requests if r.url.path.endswith("inference")]
    assert [b["text"] for b in tts_bodies] == [s.reference for s in picked]
    assert [(b["voice"], b["language"]) for b in tts_bodies] == [("Kaveri", "en-IN"), ("Nalini", "hi-IN"),
                                                                 ("Poorvi", "hi-IN")]
    stt_codes = [r.content.split(b'name="language_code"\r\n\r\n')[1].split(b"\r\n")[0].decode()
                 for r in mock.requests if r.url.path == "/stt/v3"]
    assert stt_codes == ["en-IN", "hi-IN", "hi-IN,en-IN"]
    # Scored against the original references with the normal scoring.
    assert all(r.wer == 0 for r in m.results)
    assert m.asr_model == "gnani-roundtrip-timbre-v2.5-prisma-v3.0"
    assert m.asr_config["lane"] == "tts-stt-roundtrip" and "together" in m.asr_config["measures"]
    assert m.tts_engine == "gnani.ai timbre-v2.5 (external API)"
    assert "round trip" in m.notes and "EXTERNAL API RUN" in m.notes
    ext = m.asr_config["external_api"]
    assert ext["requests"] == 6 and ext["tts_requests"] == 3 and ext["tts_characters"] == sum(
        len(s.reference) for s in picked)

    path = save(m, tmp_path / "results")
    am = lanes.save_roundtrip_audio_manifest(t, path)
    assert am.parent.name == "audio-manifests" and am.name == path.name
    manifest = json.loads(am.read_text(encoding="utf-8"))
    assert manifest["run_id"] == path.stem and len(manifest["files"]) == 3
    for f in manifest["files"]:
        wav = Path(f["path"])
        assert wav.is_file() and str(wav).startswith(str(tmp_path / "cache"))
        assert hashlib.sha256(wav.read_bytes()).hexdigest() == f["sha256"]
    assert "EXTERNAL API RUN" in format_table(summarise(m, scenarios))


def test_roundtrip_wer_reflects_the_transcript(tmp_path):
    _, picked, _, t = _setup(tmp_path, ["v1-002"], stt=[(200, fixture("stt_ok_v3_hindi.json"))])
    m = lanes.run_roundtrip(t, picked, 50, str(SCENARIOS), "pytest")
    assert m.results[0].wer > 0 and m.results[0].task_success is False


def test_roundtrip_cap_and_402(tmp_path):
    _, picked, mock, t = _setup(tmp_path, ["v1-002", "v1-011"], cap=4)
    t.budget = t.stt.budget = Budget(3)
    with pytest.raises(BudgetExceeded):
        lanes.run_roundtrip(t, picked, 50, str(SCENARIOS), "pytest")
    assert len(mock.requests) == 3

    _, picked, mock, t = _setup(tmp_path, ["v1-002", "v1-011"], tts=[(402, fixture("err_402_credit.json"))])
    with pytest.raises(GnaniRunAborted) as info:
        lanes.run_roundtrip(t, picked, 50, str(SCENARIOS), "pytest")
    assert info.value.out_of_credit and len(mock.requests) == 1


def test_roundtrip_tts_audio_over_30_s_is_not_sent_to_stt(tmp_path):
    _, picked, mock, t = _setup(tmp_path, ["v1-002"], tts=[(200, wav_bytes(31))])
    m = lanes.run_roundtrip(t, picked, 50, str(SCENARIOS), "pytest")
    assert m.results[0].error.startswith("ClipTooLong") and mock.count("/stt/v3") == 0


def test_two_language_hint_needs_prisma_v3(tmp_path):
    with pytest.raises(ValueError, match="prisma-v3.0"):
        GnaniRoundTripTranscriber(make_client(MockGnani()), Budget(2), tmp_path, stt_model="prisma-v2.5")
    t = GnaniRoundTripTranscriber(make_client(MockGnani()), Budget(2), tmp_path, stt_model="prisma-v2.5",
                                  stt_languages={"hi-en": "hi-IN"})
    assert t.stt_languages["hi-en"] == "hi-IN"


def test_default_subset_spreads_over_languages_and_conditions():
    scenarios = load_scenarios(SCENARIOS)
    picked = lanes.pick_scenarios(scenarios, 9)
    cells = {(s.language.value, s.condition.value) for s in picked}
    assert len(picked) == 9 and len(cells) == len({(s.language.value, s.condition.value) for s in scenarios})
    assert picked == lanes.pick_scenarios(scenarios, 9)
    with pytest.raises(ValueError, match="unknown"):
        lanes.pick_scenarios(scenarios, 3, ["v1-999"])
    with pytest.raises(ValueError, match="allows 1"):
        lanes.pick_scenarios(scenarios, 1, ["v1-001", "v1-002"])
