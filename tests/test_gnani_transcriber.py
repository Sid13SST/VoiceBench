"""Gnani Prisma transcriber: the docs/ADAPTERS.md hook, language mapping, and runs through the
unchanged runner and real-speech lane. Offline (mock transport)."""

import json
from pathlib import Path

import httpx
import pytest

from gnani_mock import MockGnani, fixture, make_client, wav_bytes
from voicebench import realspeech as rs
from voicebench.asr import ASRUnavailable, Transcript
from voicebench.gnani import lanes
from voicebench.gnani.budget import Budget, BudgetExceeded, GnaniRunAborted
from voicebench.gnani.transcriber import (
    CODE_SWITCHED,
    ClipTooLong,
    GnaniPrismaTranscriber,
    language_code_for,
    short_language,
)
from voicebench.loader import load_scenarios
from voicebench.report import format_table, summarise
from voicebench.runner import load_run, save

ROOT = Path(__file__).resolve().parents[1]


def _fields(request: httpx.Request) -> dict[str, str]:
    out = {}
    for part in request.content.split(b"\r\n--"):
        if b'name="' in part and b"filename=" not in part:
            head, _, body = part.partition(b"\r\n\r\n")
            out[head.split(b'name="')[1].split(b'"')[0].decode()] = body.split(b"\r\n")[0].decode()
    return out


def _transcriber(mock, max_requests=10, **kwargs):
    return GnaniPrismaTranscriber(make_client(mock), Budget(max_requests), **kwargs)


@pytest.mark.parametrize("language,model,code", [
    ("en", "prisma-v3.0", "en-IN"),
    ("hi", "prisma-v3.0", "hi-IN"),
    ("hi", "prisma-v2.5", "hi-IN"),
    (None, "prisma-v3.0", "hi-IN,en-IN"),
])
def test_language_mapping(language, model, code):
    assert language_code_for(language, model) == code


def test_language_mapping_refusals():
    with pytest.raises(ValueError, match="one language code"):
        language_code_for(None, "prisma-v2.5")
    with pytest.raises(ValueError, match="one language code"):
        language_code_for(None, "prisma-v2.5", "indic-auto")
    assert language_code_for(None, "prisma-v2.5", "hi-IN") == "hi-IN"
    with pytest.raises(ValueError, match="no Gnani language code"):
        language_code_for("ta", "prisma-v3.0")
    with pytest.raises(ValueError):
        GnaniPrismaTranscriber(make_client(MockGnani()), Budget(1), model="prisma-v2.5")
    assert short_language("hi-IN") == "hi" and short_language(None) is None and short_language("") is None


def test_adapter_contract(tmp_path):
    mock = MockGnani()
    t = _transcriber(mock)
    d = t.describe()
    assert d["name"] == "gnani-prisma-v3.0" and d["device"] == "cloud" and d["backend_version"] == "prisma-v3.0"
    assert d["external_api"]["provider"] == "gnani.ai"
    assert "not comparable" in d["external_api"]["comparability"]
    assert not hasattr(t, "transcribe_scenario")  # the runner must use transcribe_file
    assert not hasattr(t, "cost_usd")  # no cost is fabricated
    assert "app.gnani.ai" in t.cost_note

    wav = tmp_path / "v1-002.wav"
    wav.write_bytes(wav_bytes(1.5))
    out = t.transcribe_file(wav, language="en")
    assert isinstance(out, Transcript)
    assert out.text == fixture("stt_ok_v3.json")["transcript"]
    assert out.detected_language == "en" and out.requested_language == "en"
    assert out.audio_duration_s == pytest.approx(1.5) and out.latency_ms >= 0
    assert out.model == "gnani-prisma-v3.0"
    assert _fields(mock.requests[0])["language_code"] == "en-IN"
    t.transcribe_file(wav)  # policy auto
    assert _fields(mock.requests[1])["language_code"] == CODE_SWITCHED
    d = t.describe()
    assert d["external_api"]["requests"] == 2 and d["external_api"]["audio_seconds_sent"] == pytest.approx(3.0)
    assert d["models_reported_by_api"] == ["prisma-v3.0"]
    assert "credit_usage" in d["external_api"] and "credit_headers_by_item" not in d["external_api"]


def test_missing_detected_language_is_none(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(wav_bytes())
    t = _transcriber(MockGnani(stt=[(200, fixture("stt_ok_v25.json"))]), model="prisma-v2.5",
                     auto_language_code="hi-IN")
    assert t.transcribe_file(wav).detected_language is None


def test_clips_over_30_s_are_not_sent(tmp_path):
    mock = MockGnani()
    t = _transcriber(mock)
    wav = tmp_path / "long.wav"
    wav.write_bytes(wav_bytes(30.5))
    with pytest.raises(ClipTooLong):
        t.transcribe_file(wav, "hi")
    assert mock.requests == [] and t.budget.requests == 0


def test_402_aborts_and_401_aborts(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(wav_bytes())
    for status, name in ((402, "err_402_credit.json"), (401, "err_401_invalid_key.json")):
        t = _transcriber(MockGnani(stt=[(status, fixture(name))]))
        with pytest.raises(GnaniRunAborted) as info:
            t.transcribe_file(wav, "hi")
        assert isinstance(info.value, ASRUnavailable)
        assert info.value.out_of_credit == (status == 402)
        assert t.budget.log[0]["status"] == status


@pytest.fixture
def synthetic_subset():
    scenarios = load_scenarios(ROOT / "scenarios" / "v1.jsonl")
    return scenarios, lanes.pick_scenarios(scenarios, lanes.items_for("synthetic", 4))


def test_synthetic_lane_through_the_unchanged_runner(synthetic_subset, tmp_path):
    scenarios, picked = synthetic_subset
    assert len(picked) == 3
    mock = MockGnani()
    t = _transcriber(mock, max_requests=4)
    m = lanes.run_synthetic(t, picked, len(scenarios), str(ROOT / "audio" / "v1"),
                            str(ROOT / "scenarios" / "v1.jsonl"), "pytest", "hint")
    # 3 scenarios + the runner's untimed warm-up call = the cap of 4
    assert mock.count("/stt/v3") == 4 and m.warmup_runs == 1
    assert m.asr_model == "gnani-prisma-v3.0" and m.device == "cloud" and "gnani-prisma-v3.0" in m.run_id
    assert m.understander == "builtin"  # the built-in matcher really scored these transcripts
    assert m.asr_config["external_api"]["requests"] == 4
    assert m.notes.startswith("EXTERNAL API RUN (gnani.ai)") and "3 of 50 scenarios" in m.notes
    assert all(r.cost_usd is None for r in m.results)
    assert [r.scenario_id for r in m.results] == [s.id for s in picked]
    path = save(m, tmp_path)
    again = load_run(path)
    table = format_table(summarise(again, scenarios))
    assert "EXTERNAL API RUN (gnani.ai)" in table and "not comparable" in table


def test_request_cap_aborts_the_run(synthetic_subset):
    scenarios, picked = synthetic_subset
    mock = MockGnani()
    t = _transcriber(mock, max_requests=3)  # one short of 3 items + warm-up
    with pytest.raises(BudgetExceeded):
        lanes.run_synthetic(t, picked, len(scenarios), str(ROOT / "audio" / "v1"),
                            str(ROOT / "scenarios" / "v1.jsonl"), "pytest", "hint")
    assert mock.count("/stt/v3") == 3


def test_402_mid_run_aborts_without_further_requests(synthetic_subset):
    scenarios, picked = synthetic_subset
    mock = MockGnani(stt=[(200, fixture("stt_ok_v3.json")), (200, fixture("stt_ok_v3.json")),
                          (402, fixture("err_402_credit.json")), (200, fixture("stt_ok_v3.json"))])
    t = _transcriber(mock)
    with pytest.raises(GnaniRunAborted):
        lanes.run_synthetic(t, picked, len(scenarios), str(ROOT / "audio" / "v1"),
                            str(ROOT / "scenarios" / "v1.jsonl"), "pytest", "auto")
    assert mock.count("/stt/v3") == 3


def test_429_exhausted_is_one_scenarios_error_not_an_abort(synthetic_subset):
    scenarios, picked = synthetic_subset
    rate = (429, fixture("err_429_rate.json"))
    ok = (200, fixture("stt_ok_v3.json"))
    # warm-up ok, first scenario: 3 x 429, then ok
    mock = MockGnani(stt=[ok, rate, rate, rate, ok])
    t = _transcriber(mock)
    m = lanes.run_synthetic(t, picked, len(scenarios), str(ROOT / "audio" / "v1"),
                            str(ROOT / "scenarios" / "v1.jsonl"), "pytest", "auto")
    assert m.results[0].error.startswith("GnaniRateLimited")
    assert all(r.error is None for r in m.results[1:])
    assert m.asr_config["external_api"]["http_attempts"] == 6 and m.asr_config["external_api"]["requests"] == 4


def _realspeech_repo(tmp_path, n=6):
    clips = []
    audio = tmp_path / "audio"
    audio.mkdir()
    for i in range(n):
        f = f"{i:04d}.wav"
        (audio / f).write_bytes(wav_bytes(31 if i == 1 else 2))
        clips.append({"id": f"{i:04d}", "file": f, "sentence_id": i, "reference": "मेरे खाते में कितना पैसा है",
                      "num_samples": (31 if i == 1 else 2) * 16000, "gender": "FEMALE", "sha256": "0" * 64})
    manifest = {"kind": rs.KIND, "dataset": {"name": "FLEURS", "hf_repo": "google/fleurs", "revision": "r",
                                             "config": "hi_in", "split": "test", "license": "CC-BY-4.0"},
                "clips": clips}
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    split = {"dev": [c["id"] for c in clips[:4]], "heldout": [c["id"] for c in clips[4:]]}
    return manifest, str(mpath), split, audio


def test_realspeech_subset_uses_dev_clips_under_30_s(tmp_path):
    manifest, mpath, split, _ = _realspeech_repo(tmp_path)
    sub = lanes.realspeech_subset(manifest, split, 2, mpath)
    assert [c["id"] for c in sub["clips"]] == ["0000", "0002"]  # 0001 is 31 s
    assert sub["subset"]["of"] == mpath and sub["kind"] == rs.KIND
    with pytest.raises(ValueError, match="held-out"):
        lanes.realspeech_subset(manifest, split, 2, mpath, ids=["0004"])
    with pytest.raises(ValueError, match="30 s"):
        lanes.realspeech_subset(manifest, split, 2, mpath, ids=["0001"])
    with pytest.raises(ValueError, match="allows 1"):
        lanes.realspeech_subset(manifest, split, 1, mpath, ids=["0000", "0002"])
    p1 = lanes.write_subset(tmp_path / "out", sub)
    assert lanes.write_subset(tmp_path / "out", sub) == p1 and rs.load_manifest(p1)["clips"] == sub["clips"]


def test_realspeech_lane_through_the_unchanged_runner(tmp_path):
    manifest, mpath, split, audio = _realspeech_repo(tmp_path)
    sub = lanes.realspeech_subset(manifest, split, lanes.items_for("realspeech", 4), mpath)
    path = lanes.write_subset(tmp_path / "out", sub)
    mock = MockGnani(stt=[(200, fixture("stt_ok_v3_hindi.json"))])
    t = _transcriber(mock, max_requests=4)
    run = rs.run_realspeech(sub, str(path), audio, t, "pytest", language_policy="auto")
    assert mock.count("/stt/v3") == 4  # 3 clips + warm-up
    assert run.asr_model == "gnani-prisma-v3.0" and "gnani-prisma-v3.0" in run.run_id
    assert all(r.detected_language == "hi" and r.wer == 0 for r in run.results)
    s = rs.summarise_realspeech(run)
    assert s["external_api"] == "gnani.ai" and s["n_detected_hi"] == 3
    assert "EXTERNAL API RUN (gnani.ai)" in rs.format_realspeech(s)


def test_local_runs_are_not_labelled_external():
    local = load_run(ROOT / "results" / "20261018T132344Z-faster-whisper-small-auto.json")
    s = summarise(local, load_scenarios(ROOT / "scenarios" / "v1.jsonl"))
    assert "external_api" not in s and "EXTERNAL" not in format_table(s)
    real = rs.load_realspeech_run(next((ROOT / "results" / "realspeech").glob("*-auto.json")))
    assert "external_api" not in rs.summarise_realspeech(real)
