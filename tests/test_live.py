"""The live console's server side: /api/analyze (text only) and /api/clips."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from conftest import make_scenario
from voicebench.dashboard.app import create_app
from voicebench.dashboard.live import MAX_BODY_BYTES, MAX_TEXT_CHARS, AnalyzeRequest, analyze, wav_peaks
from voicebench.metrics import wer
from voicebench.nlu.matcher import match
from voicebench.schema import ResultSource, Scenario
from voicebench.scoring import score

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(ROOT / "results", ROOT / "audio" / "v1", repo_root=ROOT))


# ---------------------------------------------------------------- pure functions

def test_analyze_uses_the_project_matcher_and_wer():
    req = AnalyzeRequest(transcript="please send 5000 rupees to rahul", domain="banking",
                         reference="please send five thousand rupees to rahul")
    out = analyze(req)
    pred = match(req.transcript, "banking")
    assert out["intent"] == pred.intent == "transfer_money"
    assert out["slots"] == pred.slots == {"amount": "5000", "recipient": "rahul"}
    assert out["wer"] == round(wer(req.reference, req.transcript), 4)
    assert out["transcript_script"] == "latin" and out["domain"] == "banking"
    assert "scenario" not in out


def test_analyze_without_or_with_an_empty_reference_has_no_wer():
    assert analyze(AnalyzeRequest(transcript="hello", domain="food"))["wer"] is None
    out = analyze(AnalyzeRequest(transcript="hello", domain="food", reference="?!"))
    assert out["wer"] is None and "no words" in out["wer_note"]


def test_analyze_for_a_scenario_matches_benchmark_scoring():
    s = Scenario.model_validate(make_scenario())
    for text in ("please send five thousand rupees to rahul", "please send money", ""):
        out = analyze(AnalyzeRequest(transcript=text, domain="food"), s)  # the scenario's domain wins
        r = score(s, text, ResultSource.MEASURED)
        assert out["domain"] == "banking"
        assert out["scenario"]["task_success"] == r.task_success
        assert out["scenario"]["intent_correct"] == r.intent_correct
        assert out["intent"] == r.predicted_intent and out["slots"] == r.predicted_slots
        assert out["wer"] == round(r.wer, 4)


@pytest.mark.parametrize("bad", [
    {"transcript": "x", "domain": "casino"},                          # domain not whitelisted
    {"transcript": "x" * (MAX_TEXT_CHARS + 1), "domain": "banking"},  # too long
    {"transcript": "x", "domain": "banking", "reference": "y" * (MAX_TEXT_CHARS + 1)},
    {"transcript": "x", "domain": "banking", "audio": "AAAA"},         # unknown field
    {"transcript": "a\x00b", "domain": "banking"},                     # control character
    {"transcript": "x", "domain": "banking", "scenario_id": "../etc"},
    {"domain": "banking"},
])
def test_request_validation(bad):
    with pytest.raises(ValidationError):
        AnalyzeRequest.model_validate(bad)


def test_wav_peaks_of_a_committed_clip():
    peaks = wav_peaks(ROOT / "audio" / "v1" / "v1-001.wav")
    assert len(peaks) == 96 and max(peaks) == 1.0 and min(peaks) >= 0


# ---------------------------------------------------------------- endpoints

def test_api_analyze_returns_text_analysis_and_never_caches(client):
    r = client.post("/api/analyze", json={"transcript": "mera balance kitna hai savings account", "domain": "banking"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["intent"] == match("mera balance kitna hai savings account", "banking").intent


def test_api_analyze_rejects_bad_input_without_echoing_it(client):
    secret = "my card number is 4111 1111 1111 1111"
    r = client.post("/api/analyze", json={"transcript": secret, "domain": "casino"})
    assert r.status_code == 422 and secret not in r.text and "domain" in r.text
    assert client.post("/api/analyze", content=b"{not json", headers={"content-type": "application/json"}).status_code == 422
    big = json.dumps({"transcript": "a" * MAX_BODY_BYTES, "domain": "banking"})
    assert client.post("/api/analyze", content=big, headers={"content-type": "application/json"}).status_code == 413


def test_api_analyze_scores_a_benchmark_scenario(client):
    clips = {c["id"]: c for c in client.get("/api/clips").json()["clips"]}
    c = clips["v1-001"]
    r = client.post("/api/analyze", json={"transcript": c["reference"], "domain": c["domain"], "scenario_id": "v1-001"}).json()
    assert r["scenario"]["expected_intent"] == c["expected_intent"] and r["wer"] == 0.0
    assert client.post("/api/analyze", json={"transcript": "x", "domain": "banking", "scenario_id": "v1-999"}).status_code == 404


def test_api_clips_carries_the_stored_baseline(client):
    data = client.get("/api/clips").json()
    assert set(data["baseline"]) == {"auto", "hint"}
    assert len(data["clips"]) == 50
    run = json.loads((ROOT / "results" / f"{data['baseline']['auto']['run_id']}.json").read_text(encoding="utf-8"))
    stored = {r["scenario_id"]: r for r in run["results"]}
    for c in data["clips"]:
        assert c["audio"] == f"/audio/{c['id']}.wav"
        assert c["baseline"]["auto"]["transcript"] == stored[c["id"]]["transcript"]
        assert c["baseline"]["auto"]["task_success"] == stored[c["id"]]["task_success"]
